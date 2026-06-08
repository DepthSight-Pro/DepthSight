// src/lib/binanceApi.ts

import type { BinanceKline } from "@/types/api";

const PROXY_KLINE_URL = `${import.meta.env.VITE_API_BASE_URL || "/api/v1"}/proxy/binance/klines`; // Or use a proxy if running in browser to avoid CORS

/**
 * Fetches Kline/Candlestick data from Binance public API.
 * @param symbol The trading symbol (e.g., BTCUSDT)
 * @param interval The kline interval (e.g., '1h', '4h', '1d')
 * @param startTime Optional start time in milliseconds
 * @param endTime Optional end time in milliseconds
 * @param limit Optional limit, default 500, max 1000
 * @returns Promise<BinanceKline[]>
 */
export const fetchBinanceKlines = async (
	symbol: string,
	interval: string,
	startTime?: number,
	endTime?: number,
	limit: number = 500,
): Promise<BinanceKline[]> => {
	const params = new URLSearchParams({
		symbol: symbol.toUpperCase(),
		interval,
		limit: String(limit),
	});

	if (startTime) {
		params.append("startTime", String(startTime));
	}
	if (endTime) {
		params.append("endTime", String(endTime));
	}

	// --- Making a request to PROXY_KLINE_URL ---
	const response = await fetch(`${PROXY_KLINE_URL}?${params.toString()}`);

	if (!response.ok) {
		let errorMsg = `Failed to fetch klines from proxy: ${response.status} ${response.statusText}`;
		try {
			const errorData = await response.json();
			if (errorData?.detail) {
				// Our proxy will return an error in 'detail'
				errorMsg = errorData.detail;
			}
		} catch {
			// Could not parse error JSON, stick with default message
		}
		throw new Error(errorMsg);
	}

	const data = await response.json();
	// --- Our proxy already returns data without the 'data' wrapper
	return data as BinanceKline[];
};
