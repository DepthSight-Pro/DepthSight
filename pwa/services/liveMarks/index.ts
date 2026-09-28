// pwa/services/liveMarks/index.ts
// Groups open symbols by exchange+market, keeps max 1 socket per group.
import {
	createBinanceFuturesAdapter,
	createBinanceSpotAdapter,
} from "./binance";
import {
	createBitgetFuturesAdapter,
	createBitgetSpotAdapter,
} from "./bitget";
import {
	createBybitFuturesAdapter,
	createBybitSpotAdapter,
} from "./bybit";
import { createOkxFuturesAdapter, createOkxSpotAdapter } from "./okx";
import { createWeexFuturesAdapter, createWeexSpotAdapter } from "./weex";
import {
	type CreateMarksAdapter,
	type LiveMarket,
	type MarksCallback,
	type MarksHandle,
	cleanSymbol,
	normalizeLiveMarket,
} from "./types";

const REGISTRY: Record<string, CreateMarksAdapter> = {
	binance: createBinanceFuturesAdapter,
	binance_spot: createBinanceSpotAdapter,
	bybit: createBybitFuturesAdapter,
	bybit_spot: createBybitSpotAdapter,
	okx: createOkxFuturesAdapter,
	okx_spot: createOkxSpotAdapter,
	bitget: createBitgetFuturesAdapter,
	bitget_spot: createBitgetSpotAdapter,
	weex: createWeexFuturesAdapter,
	weex_spot: createWeexSpotAdapter,
};

export interface LiveSymbol {
	symbol: string;
	exchange?: string | null;
	/** Raw market scope ("spot", "futures_usdtm", ...). Defaults to futures. */
	market?: string | null;
}

/** Normalize position/apiKey exchange names down to a supported source. */
export const normalizeLiveExchange = (exchange?: string | null): string => {
	const raw = (exchange || "binance").trim().toLowerCase();
	const base = raw
		.replace(/_testnet$/, "")
		.replace(/_(futures|usdtm|usdm|linear|swap|spot)$/, "");
	if (
		base === "bybit" ||
		base === "okx" ||
		base === "bitget" ||
		base === "weex"
	) {
		return base;
	}
	return "binance";
};

/** Group key: "<exchange>" for futures, "<exchange>_spot" for spot. */
export const groupKeyFor = (
	exchange?: string | null,
	market?: string | null,
): string => {
	const ex = normalizeLiveExchange(exchange);
	const mkt: LiveMarket = normalizeLiveMarket(market ?? exchange);
	return mkt === "spot" ? `${ex}_spot` : ex;
};

export const groupByExchange = (
	items: LiveSymbol[],
): Record<string, string[]> => {
	const groups: Record<string, string[]> = {};
	for (const it of items) {
		const sym = cleanSymbol(it.symbol);
		if (!sym) continue;
		const key = groupKeyFor(it.exchange, it.market);
		if (!groups[key]) groups[key] = [];
		if (!groups[key].includes(sym)) groups[key].push(sym);
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
			const base = ex.endsWith("_spot") ? ex.slice(0, -5) : ex;
			const factory = REGISTRY[ex] ?? REGISTRY[base] ?? REGISTRY.binance;
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
