// frontend/src/services/liveMarks/types.ts
// Unified live mark-price adapter interface (public tickers only, no auth).

export interface MarkTick {
	symbol: string; // unified, e.g. "BTCUSDT"
	price: number;
	ts: number; // ms
	exchange: string; // normalized source: binance|bybit|okx|bitget|weex
}

export type MarksCallback = (tick: MarkTick) => void;

export interface MarksHandle {
	/** Switch subscription set (multiplexed on one socket). */
	setSymbols: (symbols: string[]) => void;
	close: () => void;
}

export type CreateMarksAdapter = (
	onTick: MarksCallback,
) => MarksHandle;

/** Unified symbol -> exchange-specific stream id helpers live here. */
export const cleanSymbol = (symbol: string): string =>
	symbol.replace(/[^a-zA-Z0-9]/g, "").toUpperCase();
