// pwa/services/liveMarks/symbolMap.ts
// Unified "BTCUSDT" -> per-exchange instrument ids.
import { cleanSymbol } from "./types";

export const toOkxInstId = (symbol: string): string => {
	const s = cleanSymbol(symbol);
	if (s.includes("-")) return s;
	if (s.endsWith("USDT")) return `${s.slice(0, -4)}-USDT-SWAP`;
	if (s.endsWith("USDC")) return `${s.slice(0, -4)}-USDC-SWAP`;
	return s;
};

/** BTCUSDT -> BTC-USDT (spot); SWAP-suffixed input maps to its spot form. */
export const toOkxSpotInstId = (symbol: string): string => {
	const s = cleanSymbol(symbol);
	if (s.endsWith("-SWAP")) return s.slice(0, -5);
	if (s.includes("-")) return s;
	if (s.endsWith("USDT")) return `${s.slice(0, -4)}-USDT`;
	if (s.endsWith("USDC")) return `${s.slice(0, -4)}-USDC`;
	return s;
};

export const toBinanceStream = (symbol: string): string =>
	`${cleanSymbol(symbol).toLowerCase()}@markPrice@1s`;

/** Futures alias (kept explicit now that a spot variant exists). */
export const toBinanceFuturesStream = toBinanceStream;

/** Spot 24h mini-ticker (1s, field `c` = last price; no mark price on spot). */
export const toBinanceSpotStream = (symbol: string): string =>
	`${cleanSymbol(symbol).toLowerCase()}@miniTicker`;
