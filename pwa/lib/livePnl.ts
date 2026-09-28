// pwa/lib/livePnl.ts
// Indicative live-PnL overlays computed from exchange ticks.
// Backend snapshots stay the source of truth; ticks only move numbers locally.

export interface LiveMarkLike {
	price: number;
	ts: number;
	exchange: string;
	market?: string;
}

/** Read the runtime exchange field (absent from PWA static types). */
export const readExchangeOf = (p: unknown): string | null => {
	if (!p || typeof p !== "object") return null;
	const ex = (p as unknown as Record<string, unknown>).exchange;
	return typeof ex === "string" ? ex : null;
};

/**
 * Normalizes position/strategy/apiKey exchange names
 * ("bitget_futures", "Bybit_Testnet", "WEEX_USDTM"...) down to a base id.
 */
export function normalizeExchangeKey(
	exchange?: string | null,
): string | null {
	if (!exchange) return null;
	let raw = String(exchange).trim().toLowerCase();
	if (!raw) return null;
	raw = raw.replace(/_testnet$/, "");
	for (const suffix of [
		"_futures",
		"_usdtm",
		"_usdm",
		"_linear",
		"_swap",
		"_spot",
	]) {
		if (raw.endsWith(suffix)) {
			raw = raw.slice(0, -suffix.length);
			break;
		}
	}
	if (raw === "gateio" || raw === "gate_io") return "gate";
	if (
		raw === "binance" ||
		raw === "bybit" ||
		raw === "okx" ||
		raw === "bitget" ||
		raw === "weex" ||
		raw === "gate" ||
		raw === "bingx"
	) {
		return raw;
	}
	return null;
}

/** Normalizes any venue string to a stable match key ("" when no venue is known). */
const normEx = (exchange: unknown): string => {
	if (exchange === null || exchange === undefined) return "";
	const raw = String(exchange);
	return normalizeExchangeKey(raw) ?? raw.trim().toLowerCase();
};

/** Reads the market scope off a position-like row (market_type, marketType,
 * or exchange-suffix fallback like "weex_spot"). Defaults to "futures". */
export const readMarketOf = (p: unknown): string => {
	if (!p || typeof p !== "object") return "futures";
	const row = p as Record<string, unknown>;
	const raw = row.market_type ?? row.marketType ?? row.market ?? row.exchange;
	if (raw === null || raw === undefined) return "futures";
	const normalized = String(raw).trim().toLowerCase();
	if (!normalized) return "futures";
	return normalized.includes("spot") ? "spot" : "futures";
};

/** Marks-cache / lookup key: "SYMBOL|EXCHANGE|fut|spot" — futures and spot
 * ticks for the same symbol never overwrite each other on any venue. */
export const markKey = (
	symbol: unknown,
	exchange: unknown,
	market?: unknown,
): string => {
	const ex = normEx(exchange);
	const raw = market ?? exchange;
	const mkt =
		raw === null || raw === undefined
			? "futures"
			: String(raw).trim().toLowerCase().includes("spot")
				? "spot"
				: "futures";
	return `${String(symbol)}|${ex}|${mkt}`;
};

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
		const exact = marks[markKey(p.symbol, p.exchange, readMarketOf(p))];
		// Bare-symbol fallback is kept only for non-WEEX venues (legacy ticks
		// without venue). For WEEX it would leak spot ticks into futures
		// positions and vice versa.
		const tick =
			exact ?? (normEx(p.exchange) === "weex" ? undefined : marks[String(p.symbol)]);
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
	open_positions?: unknown;
	exchange?: unknown;
	/** Running instance's source config id (same string as the position's
	 * `config_id`). Cards without it fall back to legacy name matching. */
	config_id?: unknown;
};

/** Aggregated position PnL for one side (snapshot or live), attributed per
 * strategy card:
 * - `byConfig`: per `mode|exchange|config_id` — exact attribution (positions
 *   carry the source config id, so same-named strategies never share PnL),
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
	configId: string,
): string =>
	exchange === null || exchange === undefined || exchange === ""
		? `${String(mode ?? "").toLowerCase()}|cfg:${configId}`
		: `${String(mode ?? "").toLowerCase()}|${normEx(exchange)}|cfg:${configId}`;

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
			// Exact attribution: one bucket per (mode, venue, config).
			const k = cfgBucket(p.mode, ex, cfgId);
			side.byConfig.set(k, (side.byConfig.get(k) ?? 0) + v);
			if (ex) {
				const kAny = cfgBucket(p.mode, "", cfgId);
				side.byConfig.set(kAny, (side.byConfig.get(kAny) ?? 0) + v);
			}
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

/** Resolve the position-PnL sum attributable to one strategy on one venue.
 * Primary match is by source config id, so two same-named strategies on the
 * same exchange never share PnL (the card with no positions of its own gets
 * `undefined` and stays untouched instead of absorbing another card's
 * unrealized PnL). Name-based buckets are only a fallback for legacy
 * snapshots without `config_id`. */
const lookup = (
	side: SideSums,
	mode: unknown,
	exchange: unknown,
	name: string,
	configId?: unknown,
): number | undefined => {
	const ex = normEx(exchange);
	const mn = modeName(mode, name);
	const cfgId = String(configId ?? "").trim();
	if (cfgId) {
		const withEx = side.byConfig.get(cfgBucket(mode, ex, cfgId));
		if (withEx !== undefined) return withEx;
		const anyEx = side.byConfig.get(cfgBucket(mode, "", cfgId));
		if (anyEx !== undefined) return anyEx;
		// Card has a config_id, so it strictly matches its own positions.
		// Never fall back to name matching to prevent absorbing other cards' positions.
		return undefined;
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
 * Strategy PnL = realized + unrealized(positions). Rebase the snapshot value
 * by the delta between snapshot and live position PnL so strategy cards
 * breathe on ticks too. Positions are attributed by source `config_id`
 * (exact), so two same-named strategies on the same exchange never share
 * PnL; name-based matching remains only as a fallback for legacy snapshots
 * written before positions carried `config_id`.
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
		);
		const snapV = lookup(snap, s.mode, s.exchange, name, s.config_id);
		const liveUnrealized = liveV !== undefined ? liveV : snapV;
		const openPositionsCount = Number(s.open_positions ?? 0);
		const targetPnl =
			liveUnrealized !== undefined
				? liveUnrealized
				: (openPositionsCount === 0 ? 0 : Number(s.unrealized_pnl ?? s.pnl ?? 0));
		if (targetPnl === s.pnl) return s;
		changed = true;
		return { ...s, pnl: targetPnl, unrealized_pnl: targetPnl, _livePnl: true } as S;
	});
	return changed ? out : strategies;
}
