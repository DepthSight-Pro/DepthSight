// pwa/services/liveMarks/types.ts
// Unified live mark-price adapter interface (public tickers only, no auth).

/** Per-venue market scope. Only WEEX splits sockets by market for now;
 * other venues stay futures-only (single socket, market ignored). */
export type LiveMarket = "spot" | "futures";

export interface MarkTick {
	symbol: string; // unified, e.g. "BTCUSDT"
	price: number;
	ts: number; // ms
	exchange: string; // normalized source: binance|bybit|okx|bitget|weex
	market?: LiveMarket; // defaults to "futures" when omitted
}

export type MarksCallback = (tick: MarkTick) => void;

export interface MarksHandle {
	/** Switch subscription set (multiplexed on one socket). */
	setSymbols: (symbols: string[]) => void;
	close: () => void;
}

export type CreateMarksAdapter = (onTick: MarksCallback) => MarksHandle;

export const cleanSymbol = (symbol: string): string =>
	symbol.replace(/[^a-zA-Z0-9]/g, "").toUpperCase();

/**
 * Normalizes any market-scope value ("spot", "futures_usdtm", "SWAP",
 * "weex_spot", undefined...) to "spot" | "futures".
 * Unknown/empty defaults to "futures" (same as the /positions server default).
 */
export const normalizeLiveMarket = (market: unknown): LiveMarket => {
	if (market === null || market === undefined) return "futures";
	const raw = String(market).trim().toLowerCase();
	if (!raw) return "futures";
	if (raw.includes("spot")) return "spot";
	return "futures";
};
