// pwa/lib/livePnl.ts
// Indicative live-PnL overlays computed from exchange ticks.
// Backend snapshots stay the source of truth; ticks only move numbers locally.

export interface LiveMarkLike {
	price: number;
	ts: number;
	exchange: string;
}

/** Read the runtime exchange field (absent from PWA static types). */
export const readExchangeOf = (p: unknown): string | null => {
	if (!p || typeof p !== "object") return null;
	const ex = (p as unknown as Record<string, unknown>).exchange;
	return typeof ex === "string" ? ex : null;
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
};

/** Override mark_price/pnl from live ticks (identity-safe, memo-friendly). */
export function applyLiveMarksToPositions<T extends PositionLike>(
	positions: T[] | undefined,
	marks: Record<string, LiveMarkLike>,
): T[] | undefined {
	if (!positions || Object.keys(marks).length === 0) return positions;
	let changed = false;
	const out = positions.map((p) => {
		const tick = marks[String(p.symbol)];
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

const stratKey = (mode: unknown, name: unknown): string =>
	`${String(mode ?? "").toLowerCase()}|${String(name ?? "").toLowerCase()}`;

export type StrategyLike = {
	strategy_name?: unknown;
	name?: unknown;
	mode?: unknown;
	pnl?: unknown;
};

/**
 * Strategy PnL = realized + unrealized(positions). Rebase the snapshot value
 * by the delta between snapshot and live position PnL so strategy cards
 * breathe on ticks too. Matches by `mode|strategy name`, falls back to
 * name-only when either side lacks a mode.
 */
export function overlayLiveStrategyPnl<S extends StrategyLike>(
	strategies: S[] | undefined,
	snapshotPositions: PositionLike[] | undefined | null,
	livePositions: PositionLike[] | undefined | null,
): S[] | undefined {
	if (!strategies || !snapshotPositions || !livePositions) return strategies;
	if (snapshotPositions === livePositions) return strategies;

	const sumBy = (list: PositionLike[]): Map<string, number> => {
		const m = new Map<string, number>();
		for (const p of list) {
			const name = String(p.strategy ?? p.strategy_name ?? "");
			if (!name) continue;
			const v = Number(p.pnl) || 0;
			const k = stratKey(p.mode, name);
			m.set(k, (m.get(k) ?? 0) + v);
			const nk = `|${name.toLowerCase()}`;
			m.set(nk, (m.get(nk) ?? 0) + v);
		}
		return m;
	};

	const snap = sumBy(snapshotPositions);
	const live = sumBy(livePositions);
	let changed = false;
	const out = strategies.map((s) => {
		const name = String(s.strategy_name ?? s.name ?? "");
		if (!name) return s;
		const k = stratKey(s.mode, name);
		const liveV = live.get(k) ?? live.get(`|${name.toLowerCase()}`);
		if (liveV === undefined) return s;
		const snapV = snap.get(k) ?? snap.get(`|${name.toLowerCase()}`) ?? 0;
		const base = Number(s.pnl ?? 0);
		const adj = base - snapV + liveV;
		if (adj === base) return s;
		changed = true;
		return { ...s, pnl: adj, _livePnl: true } as S;
	});
	return changed ? out : strategies;
}
