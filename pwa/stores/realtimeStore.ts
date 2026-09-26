// pwa/stores/realtimeStore.ts
// Realtime engine pushes for PWA (zustand, no React Query involved).
// Snapshots are per-controller (user + api_key + mode); lists merge by scope
// so multi-account ("all") views never lose other accounts' rows.

import { create } from "zustand";
import type { Position, RunningStrategy } from "../types";

export type EngineMode = "live" | "paper";

export interface PushEnvelope {
	user_id?: number;
	api_key_id?: number | null;
	seq?: number;
	ts_ms?: number;
	type?: string;
	data?: unknown;
}

type Row = Record<string, unknown>;

const normMode = (m: unknown): EngineMode =>
	String(m ?? "").toLowerCase() === "paper" ? "paper" : "live";

/** Per-controller seq guard (reconnect/resubscribe stale-drop). */
const lastSeqByScope: Record<string, number> = {};
const isFresh = (scope: string, seq: unknown): boolean => {
	const n = typeof seq === "number" ? seq : Number(seq);
	if (!Number.isFinite(n)) return true; // legacy payload without seq
	if ((lastSeqByScope[scope] ?? -1) > n) return false;
	lastSeqByScope[scope] = n;
	return true;
};

const apiKeyOfPayload = (payload: PushEnvelope): number | null =>
	payload.api_key_id === null || payload.api_key_id === undefined
		? null
		: Number(payload.api_key_id);

/** Identity within a controller scope: api_key + row id (no bare ids —
 * the same config/position id may legitimately exist on two accounts). */
const rowScopeKey = (apiKey: number | null, r: Row): string => {
	const id =
		r.id === undefined || r.id === null ? JSON.stringify(r) : String(r.id);
	return `${apiKey === null ? "?" : String(apiKey)}|${id}`;
};

/**
 * Merge a per-controller snapshot into an aggregated list.
 * - Known scope: drop only this controller's rows IN THE SAME MODE bucket,
 *   then append fresh ones. Cross-mode rows of the same account are kept —
 *   otherwise a paper-controller push would wipe live rows (and vice versa).
 * - Null scope (unknown controller): empty snapshots are ignored (never
 *   wipe), rows merge by id without dropping anything.
 */
const mergeRows = <T extends Row>(
	old: T[],
	apiKey: number | null,
	rows: T[],
	scopeMode: EngineMode,
): T[] => {
	if (apiKey === null) {
		if (rows.length === 0) return old;
		const byKey = new Map(old.map((o) => [rowScopeKey(null, o as Row), o]));
		for (const r of rows) byKey.set(rowScopeKey(null, r as Row), r);
		return [...byKey.values()];
	}
	const rest = old.filter((o) => {
		const k = (o as Row).api_key_id;
		if (k === null || k === undefined) return true; // keep rows of unknown origin
		if (Number(k) !== apiKey) return true;
		const om = (o as Row).mode;
		if (om === null || om === undefined) return false; // assume same scope
		return normMode(om) !== scopeMode;
	});
	const out = [...rest];
	const indexByKey = new Map(
		out.map((o, i) => [rowScopeKey(apiKey, o as Row), i]),
	);
	for (const r of rows) {
		const k = rowScopeKey(apiKey, r as Row);
		const idx = indexByKey.get(k);
		if (idx !== undefined) out[idx] = r;
		else {
			indexByKey.set(k, out.length);
			out.push(r);
		}
	}
	return out;
};

interface RealtimeState {
	wsConnected: boolean;
	setWsConnected: (v: boolean) => void;

	positionsByMode: Record<EngineMode, Position[]>;
	setPositions: (mode: EngineMode, list: Position[]) => void;
	applyPositionsPush: (payload: PushEnvelope) => void;

	strategiesByMode: Record<EngineMode, RunningStrategy[]>;
	setStrategies: (mode: EngineMode, list: RunningStrategy[]) => void;
	applyStrategiesPush: (payload: PushEnvelope) => void;
	/**
	 * Bumped when a push REDUCED the strategies list (stop/close — or a
	 * stale/duplicate publisher wiping live rows). Screens reconcile the
	 * affected scope with REST (authoritative) instead of trusting the push.
	 */
	strategyRemovalSeq: number;

	/** Bumped on portfolio push — screens refetch the aggregated REST view. */
	portfolioSeq: number;
	bumpPortfolio: () => void;
	/** Bumped on trades events — screens refetch history/equity. */
	tradesSeq: number;
	bumpTrades: () => void;
}

export const useRealtimeStore = create<RealtimeState>()((set, get) => ({
	wsConnected: false,
	setWsConnected: (v) => set({ wsConnected: v }),

	positionsByMode: { live: [], paper: [] },
	setPositions: (mode, list) =>
		set((s) => ({ positionsByMode: { ...s.positionsByMode, [mode]: list } })),
	applyPositionsPush: (payload) => {
		if (!isFresh(`positions:${String(payload.api_key_id ?? "?")}`, payload.seq))
			return;
		if (!Array.isArray(payload.data)) return;
		const apiKey = apiKeyOfPayload(payload);
		const rows = payload.data as Row[];
		set((s) => {
			const next = { ...s.positionsByMode };
			const buckets: Record<EngineMode, Row[]> = { live: [], paper: [] };
			for (const r of rows) buckets[normMode(r.mode)].push(r);
			next.live = mergeRows(
				next.live as unknown as Row[],
				apiKey,
				buckets.live,
				"live",
			) as unknown as Position[];
			next.paper = mergeRows(
				next.paper as unknown as Row[],
				apiKey,
				buckets.paper,
				"paper",
			) as unknown as Position[];
			return { positionsByMode: next };
		});
	},

	strategiesByMode: { live: [], paper: [] },
	setStrategies: (mode, list) =>
		set((s) => ({ strategiesByMode: { ...s.strategiesByMode, [mode]: list } })),
	applyStrategiesPush: (payload) => {
		if (!isFresh(`strategies:${String(payload.api_key_id ?? "?")}`, payload.seq))
			return;
		if (!Array.isArray(payload.data)) return;
		const apiKey = apiKeyOfPayload(payload);
		const rows = payload.data as Row[];
		const before =
			get().strategiesByMode.live.length + get().strategiesByMode.paper.length;
		set((s) => {
			const next = { ...s.strategiesByMode };
			const buckets: Record<EngineMode, Row[]> = { live: [], paper: [] };
			for (const r of rows) buckets[normMode(r.mode)].push(r);
			next.live = mergeRows(
				next.live as unknown as Row[],
				apiKey,
				buckets.live,
				"live",
			) as unknown as RunningStrategy[];
			next.paper = mergeRows(
				next.paper as unknown as Row[],
				apiKey,
				buckets.paper,
				"paper",
			) as unknown as RunningStrategy[];
			return { strategiesByMode: next };
		});
		const after =
			get().strategiesByMode.live.length + get().strategiesByMode.paper.length;
		if (after < before) {
			set((s) => ({ strategyRemovalSeq: s.strategyRemovalSeq + 1 }));
		}
	},

	strategyRemovalSeq: 0,
	portfolioSeq: 0,
	bumpPortfolio: () => set((s) => ({ portfolioSeq: s.portfolioSeq + 1 })),
	tradesSeq: 0,
	bumpTrades: () => set((s) => ({ tradesSeq: s.tradesSeq + 1 })),
}));
