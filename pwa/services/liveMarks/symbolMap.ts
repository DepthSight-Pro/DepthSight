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

export const toBinanceStream = (symbol: string): string =>
	`${cleanSymbol(symbol).toLowerCase()}@markPrice@1s`;
