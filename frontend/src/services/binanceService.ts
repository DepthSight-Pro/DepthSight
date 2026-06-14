// frontend/src/services/binanceService.ts

import { apiClient } from "@/lib/apiClient";

export interface Kline {
	time: number;
	open: number;
	high: number;
	low: number;
	close: number;
	volume: number;
}

export type KlineInterval = "1m" | "5m" | "15m" | "1h" | "4h" | "1d";

export const KLINE_INTERVALS: { value: KlineInterval; label: string }[] = [
	{ value: "1m", label: "1m" },
	{ value: "5m", label: "5m" },
	{ value: "15m", label: "15m" },
	{ value: "1h", label: "1h" },
	{ value: "4h", label: "4h" },
	{ value: "1d", label: "1d" },
];

/**
 * Fetches klines (candlestick data) from Binance.
 * Tries Futures API first, then fallbacks to Spot API if no data found.
 * @param symbol - Trading pair symbol (e.g., 'BTCUSDT')
 * @param startTime - Start time in milliseconds (Unix timestamp)
 * @param endTime - End time in milliseconds (Unix timestamp)
 * @param intervalOverride - Optional manual interval override
 */
export async function fetchKlines(
	symbol: string,
	startTime: number,
	endTime: number,
	intervalOverride?: KlineInterval,
): Promise<Kline[]> {
	const durationMs = endTime - startTime;
	let interval: KlineInterval;

	if (intervalOverride) {
		interval = intervalOverride;
	} else {
		const durationMinutes = durationMs / 60000;

		interval = "1m";
		if (durationMinutes > 1440) interval = "15m";
		if (durationMinutes > 10080) interval = "1h";
		if (durationMinutes > 43200) interval = "4h";
	}

	const cleanSymbol = symbol.replace(/[^a-zA-Z0-9]/g, "").toUpperCase();

	const padding = Math.max(durationMs, 7200000);
	const paddedStart = Math.floor(startTime - padding);
	const paddedEnd = Math.min(Date.now(), Math.floor(endTime + padding));

	try {
		const params = new URLSearchParams({
			symbol: cleanSymbol,
			interval: interval,
			startTime: paddedStart.toString(),
			endTime: paddedEnd.toString(),
			limit: "1500",
			_t: Date.now().toString(),
		});
		const data = await apiClient<[number, string, string, string, string, string, ...unknown[]][]>(
			`/proxy/binance/klines?${params.toString()}`
		);

		if (!Array.isArray(data) || data.length === 0) return [];

		return data.map(
			(
				d: [number, string, string, string, string, string, ...unknown[]],
			) => ({
				time: d[0] as number,
				open: parseFloat(d[1]),
				high: parseFloat(d[2]),
				low: parseFloat(d[3]),
				close: parseFloat(d[4]),
				volume: parseFloat(d[5]),
			}),
		);
	} catch (error) {
		console.warn(`Error fetching from Binance proxy:`, error);
	}

	return [];
}

export async function fetchSymbolInfo(symbol: string): Promise<any> {
	try {
		const response = await apiClient<any>(
			`/proxy/binance/exchange-info?symbol=${symbol.toUpperCase()}`,
		);
		return response;
	} catch (error) {
		console.warn(`Error fetching symbol info for ${symbol}:`, error);
		return null;
	}
}

