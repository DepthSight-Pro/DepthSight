// frontend/src/lib/livePnl.ts
// Indicative live-PnL overlays computed from exchange ticks.
// Backend snapshots stay the source of truth; ticks only move numbers locally.

import { normalizeExchangeKey } from "@/lib/exchanges";
import {
	normalizeLiveMarket,
	type LiveMarket,
} from "@/services/liveMarks/types";

/** Normalizes any venue string ("Bybit_Testnet", "binance"...) to a stable
 * match key ("" when no venue is known). Tick and position exchanges come
 * from different sources and must map to the same key. */
const normEx = (exchange: unknown): string => {
	if (exchange === null || exchange === undefined) return "";
	const raw = String(exchange);
	return normalizeExchangeKey(raw) ?? raw.trim().toLowerCase();
};

/** Reads the market scope off a position-like row (market_type, marketType,
 * or exchange-suffix fallback like "weex_spot"). Defaults to "futures". */
export const readMarketOf = (p: unknown): LiveMarket => {
	if (!p || typeof p !== "object") return "futures";
	const row = p as Record<string, unknown>;
	return normalizeLiveMarket(
		row.market_type ?? row.marketType ?? row.market ?? row.exchange,
	);
};

/** Marks-cache / lookup key: "SYMBOL|EXCHANGE|fut|spot" — futures and spot
 * ticks for the same symbol never overwrite each other on any venue. */
export const markKey = (
	symbol: unknown,
	exchange: unknown,
	market?: unknown,
): string => {
	const ex = normEx(exchange);
	const mkt = normalizeLiveMarket(market ?? exchange);
	return `${String(symbol)}|${ex}|${mkt === "spot" ? "spot" : "fut"}`;
};

export interface LiveMarkLike {
	price: number;
	ts: number;
	exchange: string;
	market?: LiveMarket;
}

export const calcLivePnl = (
	direction: string,
	entry: number,
	mark: number,
	size: number,
): number => {
	if (!Number.isFinite(entry) || !Number.isFinite(mark) || !Number.isFinite(size))
		return 0;
	const diff = mark - entry;
	return direction === "SHORT" ? -diff * size : diff * size;
};

export type PositionLike = {
	symbol: string;
	direction?: unknown;
	side?: unknown;
	entry_price?: unknown;
	size?: unknown;
	pnl?: unknown;
	mode?: unknown;
	strategy?: unknown;
	strategy_name?: unknown;
	api_key_id?: unknown;
	exchange?: unknown;
	market_type?: unknown;
	marketType?: unknown;
	/** Source strategy config id. Positions and strategy cards are linked by
	 * config id: `strategy`/`strategy_name` is a CLASS name (e.g.
	 * "VisualBuilderStrategy") shared by every visual strategy, so name-based
	 * buckets mix PnL across unrelated cards. */
	config_id?: unknown;
};

/** Override mark_price/pnl from live ticks (identity-safe, memo-friendly). */
export function applyLiveMarksToPositions<T extends PositionLike>(
	positions: T[] | undefined,
	marks: Record<string, LiveMarkLike>,
): T[] | undefined {
	if (!positions || Object.keys(marks).length === 0) return positions;
	let changed = false;
	const out = positions.map((p) => {
		// Venue-scoped tick only: a tick from another exchange (same symbol)
		// must never move this position's PnL. WEEX additionally scopes by
		// market, so spot ticks never move futures positions and vice versa.
		const tick =
			marks[markKey(p.symbol, p.exchange, readMarketOf(p))];
		if (!tick) return p;
		changed = true;
		return {
			...p,
			mark_price: tick.price,
			pnl: calcLivePnl(
				String(p.direction ?? p.side ?? "LONG"),
				Number(p.entry_price),
				tick.price,
				Number(p.size),
			),
			_live: true,
		} as T;
	});
	return changed ? out : positions;
}

const modeName = (mode: unknown, name: unknown): string =>
	`${String(mode ?? "").toLowerCase()}|${String(name ?? "").toLowerCase()}`;

const stratKey = (
	mode: unknown,
	exchange: unknown,
	name: unknown,
): string => `${modeName(mode, name)}|${normEx(exchange)}`;

export type StrategyLike = {
	strategy_name?: unknown;
	name?: unknown;
	mode?: unknown;
	pnl?: unknown;
	unrealized_pnl?: unknown;
	realized_pnl?: unknown;
	total_pnl?: unknown;
	open_positions?: unknown;
	exchange?: unknown;
	api_key_id?: unknown;
	/** Running instance's source config id (same string as the position's
	 * `config_id`). Cards without it fall back to legacy name matching. */
	config_id?: unknown;
};

/** Normalizes an api key id to a bucket fragment ("" when unknown). */
const normApiKey = (apiKeyId: unknown): string => {
	if (apiKeyId === null || apiKeyId === undefined || apiKeyId === "") return "";
	return String(apiKeyId);
};

/** Aggregated position PnL for one side (snapshot or live), attributed per
 * strategy card:
 * - `byConfig`: per `mode|exchange|api_key|config_id` — the exact bucket
 *   (positions carry the source config id, so same-named strategies never
 *   share PnL, and the api key scope keeps sibling accounts on one
 *   exchange from absorbing each other's unrealized PnL),
 * - `legacyEx`/`legacyAny`: name buckets (`mode|exchange|name`, `mode|name`)
 *   kept only for old snapshots written before positions carried
 *   `config_id` (they expire with the 30s Redis TTL),
 * - `venuesByName`: distinct legacy venues seen per `mode|name`. */
type SideSums = {
	byConfig: Map<string, number>;
	legacyEx: Map<string, number>;
	legacyAny: Map<string, number>;
	venuesByName: Map<string, Set<string>>;
};

const cfgBucket = (
	mode: unknown,
	exchange: unknown,
	apiKeyId: unknown,
	configId: string,
): string => {
	const ex = normEx(exchange);
	const api = normApiKey(apiKeyId);
	const m = String(mode ?? "").toLowerCase();
	return ex
		? `${m}|${ex}|key:${api}|cfg:${configId}`
		: `${m}|key:${api}|cfg:${configId}`;
};

const sumPositions = (list: PositionLike[]): SideSums => {
	const side: SideSums = {
		byConfig: new Map(),
		legacyEx: new Map(),
		legacyAny: new Map(),
		venuesByName: new Map(),
	};
	for (const p of list) {
		const name = String(p.strategy ?? p.strategy_name ?? "");
		if (!name) continue;
		const v = Number(p.pnl) || 0;
		const ex = normEx(p.exchange);
		const mn = modeName(p.mode, name);
		const cfgId = String(p.config_id ?? "").trim();
		if (cfgId) {
			// Exact attribution: one bucket per (mode, venue, account, config).
			const k = cfgBucket(p.mode, ex, p.api_key_id, cfgId);
			side.byConfig.set(k, (side.byConfig.get(k) ?? 0) + v);
		} else if (ex) {
			// Legacy snapshot row without config_id.
			const k = stratKey(p.mode, ex, name);
			side.legacyEx.set(k, (side.legacyEx.get(k) ?? 0) + v);
			const venues = side.venuesByName.get(mn) ?? new Set<string>();
			venues.add(ex);
			side.venuesByName.set(mn, venues);
		} else {
			side.legacyAny.set(mn, (side.legacyAny.get(mn) ?? 0) + v);
		}
	}
	return side;
};

/** Resolve the position-PnL sum attributable to one strategy on one venue
 * and account. Primary match is by source config id, so two same-named
 * strategies on the same exchange never share PnL, and sibling accounts
 * running one config never absorb each other's unrealized PnL (the card
 * with no positions of its own gets `undefined` and stays untouched).
 * Name-based buckets are only a fallback for legacy snapshots without
 * `config_id`. */
const lookup = (
	side: SideSums,
	mode: unknown,
	exchange: unknown,
	name: string,
	configId?: unknown,
	apiKeyId?: unknown,
): number | undefined => {
	const ex = normEx(exchange);
	const mn = modeName(mode, name);
	const cfgId = String(configId ?? "").trim();
	if (cfgId) {
		const v = side.byConfig.get(cfgBucket(mode, ex, apiKeyId, cfgId));
		if (v !== undefined) return v;
		const cardApi = normApiKey(apiKeyId);
		if (cardApi) {
			// Account-scoped card with no positions of its own: never leak
			// another account's same-config PnL into it.
			return undefined;
		}
		// Card without an account tag (e.g. aggregated view): sum this
		// config across accounts on the same mode + venue.
		let total: number | undefined;
		const prefix = ex
			? `${String(mode ?? "").toLowerCase()}|${ex}|key:`
			: `${String(mode ?? "").toLowerCase()}|key:`;
		const suffix = `|cfg:${cfgId}`;
		for (const [k, sum] of side.byConfig) {
			if (k.startsWith(prefix) && k.endsWith(suffix)) {
				total = (total ?? 0) + sum;
			}
		}
		if (total !== undefined) return total;
		// No positions attributed to this config yet. Fall back to legacy
		// name buckets (possible only for snapshots written before
		// config_id existed); positions of OTHER same-named configs live in
		// `byConfig`, so they can never leak into the card's value here.
	}
	if (ex) {
		const v = side.legacyEx.get(stratKey(mode, ex, name));
		if (v !== undefined) return v;
		const venues = side.venuesByName.get(mn);
		if (!venues || venues.size === 0) return side.legacyAny.get(mn);
		return undefined;
	}
	const venues = side.venuesByName.get(mn);
	if (venues && venues.size === 1) {
		const [only] = venues;
		return side.legacyEx.get(`${mn}|${only}`);
	}
	if ((!venues || venues.size === 0) && side.legacyAny.has(mn)) {
		return side.legacyAny.get(mn);
	}
	return undefined;
};

/**
 * Strategy PnL = live unrealized PnL of open positions (matching Positions tab),
 * while historical closed trades are plotted on the equity sparklines.
 * Positions are attributed by source `config_id` (exact), so two same-named
 * strategies on the same exchange never share PnL.
 */
export function overlayLiveStrategyPnl<S extends StrategyLike>(
	strategies: S[] | undefined,
	snapshotPositions: PositionLike[] | undefined | null,
	livePositions: PositionLike[] | undefined | null,
): S[] | undefined {
	if (!strategies || !snapshotPositions || !livePositions) return strategies;
	if (snapshotPositions === livePositions) return strategies;

	const snap = sumPositions(snapshotPositions);
	const live = sumPositions(livePositions);
	let changed = false;
	const out = strategies.map((s) => {
		const name = String(s.strategy_name ?? s.name ?? "");
		if (!name && !s.config_id) return s;
		const liveV = lookup(
			live,
			s.mode,
			s.exchange,
			name,
			s.config_id,
			s.api_key_id,
		);
		const snapV = lookup(
			snap,
			s.mode,
			s.exchange,
			name,
			s.config_id,
			s.api_key_id,
		);
		const liveUnrealized = liveV !== undefined ? liveV : snapV;
		const targetPnl =
			liveUnrealized !== undefined
				? liveUnrealized
				: (s.open_positions === 0 ? 0 : Number(s.unrealized_pnl ?? s.pnl ?? 0));
		if (targetPnl === s.pnl) return s;
		changed = true;
		return { ...s, pnl: targetPnl, unrealized_pnl: targetPnl, _livePnl: true } as S;
	});
	return changed ? out : strategies;
}
