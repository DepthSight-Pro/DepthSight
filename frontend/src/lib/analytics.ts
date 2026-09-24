// src/lib/analytics.ts
//
// Client-side trade analytics shared by the new dashboard pages.
// Same recipes as the legacy Analytics page (winRate, daily-annualized Sharpe).

import type { TradeData } from "@/types/api";

export interface TradeSummary {
	totalPnl: number;
	totalCommission: number;
	totalTrades: number;
	wins: number;
	losses: number;
	winRate: number; // 0..100
	sharpeRatio: number;
	sharpeInsufficient: boolean;
}

export function summarizeTrades(trades: TradeData[]): TradeSummary {
	const withPnl = (trades || []).filter(
		(t) => t.pnl !== undefined && t.pnl !== null,
	);
	const totalPnl = withPnl.reduce((sum, t) => sum + (Number(t.pnl) || 0), 0);
	const totalCommission = (trades || []).reduce(
		(sum, t) => sum + (Number(t.commission) || 0),
		0,
	);
	const wins = withPnl.filter((t) => (Number(t.pnl) || 0) > 0);
	const losses = withPnl.filter((t) => (Number(t.pnl) || 0) <= 0);
	const winRate =
		withPnl.length > 0 ? (wins.length / withPnl.length) * 100 : 0;

	// Daily-annualized Sharpe, mirrored from the Analytics page.
	const dailyPnLMap: Record<string, number> = {};
	withPnl.forEach((t) => {
		if (!t.timestamp_close) return;
		const dateKey = new Date(t.timestamp_close).toISOString().split("T")[0];
		dailyPnLMap[dateKey] = (dailyPnLMap[dateKey] || 0) + (Number(t.pnl) || 0);
	});
	const dailyReturns = Object.values(dailyPnLMap);
	let sharpeRatio = 0;
	let sharpeInsufficient = false;
	if (dailyReturns.length >= 2) {
		const avg = dailyReturns.reduce((a, b) => a + b, 0) / dailyReturns.length;
		const variance =
			dailyReturns.reduce((sum, r) => sum + (r - avg) ** 2, 0) /
			(dailyReturns.length - 1);
		const std = Math.sqrt(variance);
		if (std > 0.0001) {
			sharpeRatio = (avg / std) * Math.sqrt(365);
		} else if (avg > 0) {
			sharpeRatio = 50;
		} else if (avg < 0) {
			sharpeRatio = -50;
		}
		if (sharpeRatio > 50) sharpeRatio = 50;
		if (sharpeRatio < -50) sharpeRatio = -50;
	} else {
		sharpeInsufficient = true;
	}

	return {
		totalPnl,
		totalCommission,
		totalTrades: withPnl.length,
		wins: wins.length,
		losses: losses.length,
		winRate,
		sharpeRatio,
		sharpeInsufficient,
	};
}

/** Max drawdown in percent over an equity value series. */
export function maxDrawdownPct(equity: number[]): number {
	let peak = -Infinity;
	let maxDd = 0;
	for (const v of equity) {
		if (!Number.isFinite(v)) continue;
		if (v > peak) peak = v;
		if (peak > 0) maxDd = Math.min(maxDd, (v - peak) / peak);
	}
	return maxDd * 100;
}

export interface HeatmapRow {
	symbol: string;
	cells: number[]; // 24 UTC-hour cells, avg pnl% per cell (0 when no trades)
}

const QUOTE_SUFFIXES = ["USDT", "USDC", "USD", "BUSD", "FDUSD", "TUSD"];

export function baseAsset(symbol: string): string {
	const s = (symbol || "").toUpperCase();
	for (const q of QUOTE_SUFFIXES) {
		if (s.endsWith(q) && s.length > q.length) return s.slice(0, -q.length);
	}
	return s;
}

/**
 * Builds the 24h strategy-return heatmap from closed trades:
 * rows = top symbols by |pnl|, cells = average pnl% per UTC hour.
 * pnl% per trade ≈ pnl / (quantity × entry_price) × 100.
 */
export function heatmapFromTrades(
	trades: TradeData[],
	maxRows = 8,
): HeatmapRow[] {
	const perSymbol = new Map<string, { pnl: number; cells: number[][] }>();
	for (const t of trades || []) {
		if (!t.symbol || t.timestamp_close === undefined || t.timestamp_close === null)
			continue;
		const d = new Date(t.timestamp_close);
		if (Number.isNaN(d.getTime())) continue;
		const hour = d.getUTCHours();
		const notional =
			(Number(t.quantity) || 0) * (Number(t.entry_price) || 0);
		const pnlPct =
			notional > 0 ? ((Number(t.pnl) || 0) / notional) * 100 : 0;
		const key = baseAsset(t.symbol);
		let entry = perSymbol.get(key);
		if (!entry) {
			entry = { pnl: 0, cells: Array.from({ length: 24 }, () => []) };
			perSymbol.set(key, entry);
		}
		entry.pnl += Number(t.pnl) || 0;
		entry.cells[hour].push(pnlPct);
	}
	return [...perSymbol.entries()]
		.sort((a, b) => Math.abs(b[1].pnl) - Math.abs(a[1].pnl))
		.slice(0, maxRows)
		.map(([symbol, entry]) => ({
			symbol,
			cells: entry.cells.map((bucket) =>
				bucket.length > 0
					? +(bucket.reduce((a, b) => a + b, 0) / bucket.length).toFixed(2)
					: 0,
			),
		}));
}

const toCloseMs = (value: unknown): number | null => {
	if (value === undefined || value === null) return null;
	if (typeof value === "number") {
		const ms = value > 1_000_000_000_000 ? value : value * 1000;
		return Number.isFinite(ms) ? ms : null;
	}
	const ms = new Date(value as string).getTime();
	return Number.isFinite(ms) ? ms : null;
};

/**
 * Per-strategy cumulative realized-PnL series from closed trades, for equity
 * sparklines. Keyed by both trade.strategy (name) and trade.strategy_config_id,
 * mirroring the Analytics page matching. Series start at 0.
 */
export function cumulativePnlByStrategy(
	trades: TradeData[],
): Map<string, number[]> {
	const byKey = new Map<string, { t: number; pnl: number }[]>();
	for (const tr of trades || []) {
		const pnl = Number(tr.pnl);
		if (!Number.isFinite(pnl)) continue;
		const ts = toCloseMs(tr.timestamp_close);
		if (ts === null) continue;
		const keys = [tr.strategy, tr.strategy_config_id].filter(
			(k): k is string => !!k,
		);
		for (const key of keys) {
			let bucket = byKey.get(key);
			if (!bucket) {
				bucket = [];
				byKey.set(key, bucket);
			}
			bucket.push({ t: ts, pnl });
		}
	}
	const out = new Map<string, number[]>();
	for (const [key, fills] of byKey) {
		fills.sort((a, b) => a.t - b.t);
		let cumulative = 0;
		const series = [0];
		for (const f of fills) {
			cumulative += f.pnl;
			series.push(+cumulative.toFixed(2));
		}
		out.set(key, series);
	}
	return out;
}
