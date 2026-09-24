// frontend/src/services/exchangeKlineService.ts
//
// Single exchange-aware klines path backed by GET /proxy/klines (unified ccxt proxy).
// Replaces the manual binance-vs-bybit branching scattered across components.

import { apiClient } from "@/lib/apiClient";
import type { Kline, KlineInterval } from "./binanceService";

export type KlineExchangeSource = "binance" | "bybit" | "okx" | "bitget" | "weex";

/**
 * Normalizes position/apiKey exchange names ("bybit", "okx_futures", "WEEX_USDTM"...)
 * down to one of the proxy-supported sources. Unknown -> "binance".
 */
export function normalizeKlineExchange(
	exchange?: string | null,
): KlineExchangeSource {
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
}

/** Raw row from GET /proxy/klines: [ts_ms, o, h, l, c, v] (numbers). */
type UnifiedKlineRow = [
	number,
	number,
	number,
	number,
	number,
	number,
	...unknown[],
];

export interface ExchangeKlinesParams {
	symbol: string;
	interval: KlineInterval;
	exchange?: string | null;
	startTime?: number;
	endTime?: number;
	limit?: number;
}

export async function fetchExchangeKlines(
	params: ExchangeKlinesParams,
): Promise<Kline[]> {
	const {
		symbol,
		interval,
		exchange,
		startTime,
		endTime,
		limit = 500,
	} = params;
	const cleanSymbol = symbol.replace(/[^a-zA-Z0-9]/g, "").toUpperCase();
	const source = normalizeKlineExchange(exchange);

	const query = new URLSearchParams({
		symbol: cleanSymbol,
		interval,
		exchange: source,
		limit: String(limit),
	});
	if (startTime) query.append("startTime", String(Math.floor(startTime)));
	if (endTime) query.append("endTime", String(Math.floor(endTime)));

	const data = await apiClient<UnifiedKlineRow[]>(
		`/proxy/klines?${query.toString()}`,
	);
	if (!Array.isArray(data)) return [];

	return data
		.map((d) => ({
			time: Number(d[0]),
			open: Number(d[1]),
			high: Number(d[2]),
			low: Number(d[3]),
			close: Number(d[4]),
			volume: Number(d[5] ?? 0),
		}))
		.filter((k) => Number.isFinite(k.time) && Number.isFinite(k.close));
}

export interface ExchangeKlinesResult {
	klines: Kline[];
	/** Exchange the data actually came from (may differ after fallback). */
	source: KlineExchangeSource;
}

/**
 * Same as fetchExchangeKlines, but falls back to Binance when the native
 * exchange returns nothing (delisted mapping, regional block, etc.).
 */
export async function fetchExchangeKlinesWithFallback(
	params: ExchangeKlinesParams,
): Promise<ExchangeKlinesResult> {
	const primary = normalizeKlineExchange(params.exchange);
	try {
		const klines = await fetchExchangeKlines({ ...params, exchange: primary });
		if (klines.length > 0) return { klines, source: primary };
	} catch (error) {
		console.warn(`Failed to load ${primary} klines:`, error);
	}
	if (primary !== "binance") {
		try {
			const klines = await fetchExchangeKlines({
				...params,
				exchange: "binance",
			});
			return { klines, source: "binance" };
		} catch (error) {
			console.warn("Failed to load Binance fallback klines:", error);
		}
	}
	return { klines: [], source: primary };
}
