// frontend/src/services/bybitService.ts

import { apiClient } from "@/lib/api";
import type { Kline, KlineInterval } from "./binanceService";

export async function fetchBybitKlines(
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

	const bybitInterval = {
		"1m": "1",
		"5m": "5",
		"15m": "15",
		"1h": "60",
		"4h": "240",
		"1d": "D",
	}[interval] || "1";

	const categories = ["linear", "spot"];

	for (const category of categories) {
		try {
			const params = new URLSearchParams({
				symbol: cleanSymbol,
				interval: bybitInterval,
				category: category,
				start: paddedStart.toString(),
				end: paddedEnd.toString(),
				limit: "1000",
			});

			const json = await apiClient<{ retCode: number; result?: { list?: string[][] } }>(
				`/proxy/bybit/klines?${params.toString()}`
			);

			if (json.retCode !== 0 || !json.result || !Array.isArray(json.result.list) || json.result.list.length === 0) {
				continue;
			}

			// Bybit returns list ordered by descending time. Reverse it to ascending time.
			const reversedList = [...json.result.list].reverse();

			return reversedList.map((d: string[]) => ({
				time: parseInt(d[0], 10),
				open: parseFloat(d[1]),
				high: parseFloat(d[2]),
				low: parseFloat(d[3]),
				close: parseFloat(d[4]),
				volume: parseFloat(d[5]),
			}));
		} catch (error) {
			console.warn(`Error fetching from Bybit proxy ${category}:`, error);
		}
	}

	console.error(`Could not fetch data for ${cleanSymbol} from any Bybit proxy endpoint.`);
	return [];
}

