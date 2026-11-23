// src/lib/klineApi.ts

import type { BinanceKline } from "@/types/api";
import { fetchBinanceKlines } from "./binanceApi";

/**
 * Fetches Kline/Candlestick data from exchange directly (with client fallback and backend backup).
 * @param symbol The trading symbol (e.g., BTCUSDT)
 * @param interval The kline interval (e.g., '1m', '1h', '1d')
 * @param exchange The exchange name (e.g., 'binance', 'bybit', 'weex', 'okx', 'bitget')
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
	return fetchBinanceKlines(symbol, interval, startTime, endTime, limit, exchange);
};
