// pwa/stores/realtimeStore.ts
// Realtime engine pushes for PWA (zustand, no React Query involved).
// Snapshots are per-controller (user + api_key); lists merge by api_key_id
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

const idOf = (r: Row): string => String(r.id ?? "");

/** Per-controller seq guard (Reconnect/resubscribe stale-drop). */
const lastSeqByScope: Record<string, number> = {};
const isFresh = (scope: string, seq: unknown): boolean => {
	const n = typeof seq === "number" ? seq : Number(seq);
	if (!Number.isFinite(n)) return true; // legacy payload without seq
	if ((lastSeqByScope[scope] ?? -1) > n) return false;
	lastSeqByScope[scope] = n;
	return true;
};

/**
 * Merge a per-controller snapshot into an aggregated list:
 * drop this controller's old rows, append fresh ones, dedupe by id.
 */
const mergeRows = <T extends Row>(old: T[], apiKey: number | null, rows: T[]): T[] => {
	if (apiKey === null) return rows;
	const rest = old.filter((o) => {
		const k = o.api_key_id;
		if (k === null || k === undefined) return true; // keep rows of unknown origin
		return Number(k) !== apiKey;
	});
	const seen = new Set(rest.map((o) => idOf(o as Row)));
	const out = [...rest];
	for (const r of rows) {
		const id = idOf(r as Row);
		if (id && seen.has(id)) {
			const idx = out.findIndex((o) => idOf(o as Row) === id);
			if (idx >= 0) out[idx] = r;
		} else {
			if (id) seen.add(id);
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

	strategies: RunningStrategy[];
	setStrategies: (list: RunningStrategy[]) => void;
	applyStrategiesPush: (payload: PushEnvelope) => void;

	/** Bumped on portfolio push — screens refetch the aggregated REST view. */
	portfolioSeq: number;
	bumpPortfolio: () => void;
	/** Bumped on trades events — screens refetch history/equity. */
	tradesSeq: number;
	bumpTrades: () => void;
}

export const useRealtimeStore = create<RealtimeState>()((set) => ({
	wsConnected: false,
	setWsConnected: (v) => set({ wsConnected: v }),

	positionsByMode: { live: [], paper: [] },
	setPositions: (mode, list) =>
		set((s) => ({ positionsByMode: { ...s.positionsByMode, [mode]: list } })),
	applyPositionsPush: (payload) => {
		if (!isFresh(`positions:${String(payload.api_key_id ?? "?")}`, payload.seq))
			return;
		if (!Array.isArray(payload.data)) return;
		const apiKey =
			payload.api_key_id === null || payload.api_key_id === undefined
				? null
				: Number(payload.api_key_id);
		const rows = payload.data as Row[];
		set((s) => {
			const next = { ...s.positionsByMode };
			const buckets: Record<EngineMode, Row[]> = { live: [], paper: [] };
			for (const r of rows) buckets[normMode(r.mode)].push(r);
			next.live = mergeRows(
				next.live as unknown as Row[],
				apiKey,
				buckets.live,
			) as unknown as Position[];
			next.paper = mergeRows(
				next.paper as unknown as Row[],
				apiKey,
				buckets.paper,
			) as unknown as Position[];
			return { positionsByMode: next };
		});
	},

	strategies: [],
	setStrategies: (list) => set({ strategies: list }),
	applyStrategiesPush: (payload) => {
		if (!isFresh(`strategies:${String(payload.api_key_id ?? "?")}`, payload.seq))
			return;
		if (!Array.isArray(payload.data)) return;
		const apiKey =
			payload.api_key_id === null || payload.api_key_id === undefined
				? null
				: Number(payload.api_key_id);
		// PWA running list is live-scoped (REST has no mode param → server
		// default live). Keep paper pushes out to preserve screen behavior.
		const rows = (payload.data as Row[]).filter((r) => {
			if (r.mode === null || r.mode === undefined) return true;
			return normMode(r.mode) === "live";
		});
		set((s) => ({
			strategies: mergeRows(
				s.strategies as unknown as Row[],
				apiKey,
				rows,
			) as unknown as RunningStrategy[],
		}));
	},

	portfolioSeq: 0,
	bumpPortfolio: () => set((s) => ({ portfolioSeq: s.portfolioSeq + 1 })),
	tradesSeq: 0,
	bumpTrades: () => set((s) => ({ tradesSeq: s.tradesSeq + 1 })),
}));
