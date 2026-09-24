// frontend/src/services/liveMarks/index.ts
// Groups open symbols by exchange, keeps max 1 socket per exchange.
import { normalizeKlineExchange } from "@/services/exchangeKlineService";
import { createBinanceAdapter } from "./binance";
import { createBybitAdapter } from "./bybit";
import { createOkxAdapter } from "./okx";
import { createBitgetAdapter } from "./bitget";
import { createWeexAdapter } from "./weex";
import {
	type CreateMarksAdapter,
	type MarksCallback,
	type MarksHandle,
	cleanSymbol,
} from "./types";

const REGISTRY: Record<string, CreateMarksAdapter> = {
	binance: createBinanceAdapter,
	bybit: createBybitAdapter,
	okx: createOkxAdapter,
	bitget: createBitgetAdapter,
	weex: createWeexAdapter,
};

export interface LiveSymbol {
	symbol: string;
	exchange?: string | null;
}

export const groupByExchange = (
	items: LiveSymbol[],
): Record<string, string[]> => {
	const groups: Record<string, string[]> = {};
	for (const it of items) {
		const sym = cleanSymbol(it.symbol);
		if (!sym) continue;
		const ex = normalizeKlineExchange(it.exchange);
		if (!groups[ex]) groups[ex] = [];
		if (!groups[ex].includes(sym)) groups[ex].push(sym);
	}
	return groups;
};

export const createLiveMarksManager = (onTick: MarksCallback) => {
	let handles: Record<string, MarksHandle> = {};

	const setSymbols = (items: LiveSymbol[]) => {
		const groups = groupByExchange(items);
		// close stale exchanges
		for (const ex of Object.keys(handles)) {
			if (!groups[ex]) {
				handles[ex].close();
				delete handles[ex];
			}
		}
		for (const [ex, syms] of Object.entries(groups)) {
			const factory = REGISTRY[ex] ?? REGISTRY.binance;
			if (!handles[ex]) handles[ex] = factory(onTick);
			handles[ex].setSymbols(syms);
		}
	};

	const close = () => {
		for (const h of Object.values(handles)) h.close();
		handles = {};
	};

	return { setSymbols, close };
};
