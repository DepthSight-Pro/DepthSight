// src/lib/klineApi.ts

import type { BinanceKline } from "@/types/api";

const PROXY_KLINE_URL = `${import.meta.env.VITE_API_BASE_URL || "/api/v1"}/proxy/klines`;

/**
 * Fetches Kline/Candlestick data from various exchanges via backend proxy.
 * @param symbol The trading symbol (e.g., BTCUSDT)
 * @param interval The kline interval (e.g., '1m', '1h', '1d')
 * @param exchange The exchange name (e.g., 'binance', 'bybit')
 * @param startTime Optional start time in milliseconds
 * @param endTime Optional end time in milliseconds
 * @param limit Optional limit, default 500
 * @returns Promise<BinanceKline[]> (Normalized format: [[ts, o, h, l, c, v], ...])
 */
export const fetchKlines = async (
	symbol: string,
	interval: string,
	exchange: string = "binance",
	startTime?: number,
	endTime?: number,
	limit: number = 500,
): Promise<BinanceKline[]> => {
	const params = new URLSearchParams({
		symbol: symbol.toUpperCase(),
		interval,
		exchange: exchange.toLowerCase(),
		limit: String(limit),
	});

	if (startTime) {
		params.append("startTime", String(startTime));
	}
	if (endTime) {
		params.append("endTime", String(endTime));
	}

	const response = await fetch(`${PROXY_KLINE_URL}?${params.toString()}`);

	if (!response.ok) {
		let errorMsg = `Failed to fetch klines from proxy: ${response.status} ${response.statusText}`;
		try {
			const errorData = await response.json();
			if (errorData?.detail) {
				errorMsg = errorData.detail;
			}
		} catch {
			// fallback
		}
		throw new Error(errorMsg);
	}

	const data = await response.json();
	return data as BinanceKline[];
};
