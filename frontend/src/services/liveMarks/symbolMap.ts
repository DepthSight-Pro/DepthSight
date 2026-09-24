// frontend/src/services/liveMarks/symbolMap.ts
// Unified "BTCUSDT" -> per-exchange instrument ids.
import { cleanSymbol } from "./types";

export const toOkxInstId = (symbol: string): string => {
	const s = cleanSymbol(symbol);
	// BTCUSDT -> BTC-USDT-SWAP ; already dashed passthrough
	if (s.includes("-")) return s;
	if (s.endsWith("USDT")) return `${s.slice(0, -4)}-USDT-SWAP`;
	if (s.endsWith("USDC")) return `${s.slice(0, -4)}-USDC-SWAP`;
	return s;
};

export const toBitgetInstId = (symbol: string): string => cleanSymbol(symbol);

export const toBybitTopic = (symbol: string): string =>
	`tickers.${cleanSymbol(symbol)}`;

export const toBinanceStream = (symbol: string): string =>
	`${cleanSymbol(symbol).toLowerCase()}@markPrice@1s`;
