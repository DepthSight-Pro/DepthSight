// src/lib/binanceApi.ts

import type { BinanceKline } from "@/types/api";

const PROXY_KLINE_URL = `${import.meta.env.VITE_API_BASE_URL || "/api/v1"}/proxy/klines`;

/**
 * Normalizes an exchange string to a canonical lowercase exchange key.
 */
export function normalizeExchangeName(exchange?: string | null): string {
	const raw = (exchange || "").toLowerCase().trim();
	if (raw.includes("bybit")) return "bybit";
	if (raw.includes("weex")) return "weex";
	if (raw.includes("okx")) return "okx";
	if (raw.includes("bitget")) return "bitget";
	if (raw.includes("hyperliquid") || raw === "hl") return "hyperliquid";
	return "binance";
}

/** Direct browser fetch from Bybit V5 public REST API */
async function fetchBybitDirect(
	cleanSymbol: string,
	interval: string,
	startTime?: number,
	endTime?: number,
	limit: number = 500,
): Promise<BinanceKline[] | null> {
	const bybitIntervalMap: Record<string, string> = {
		"1m": "1",
		"3m": "3",
		"5m": "5",
		"15m": "15",
		"30m": "30",
		"1h": "60",
		"2h": "120",
		"4h": "240",
		"1d": "D",
	};
	const bInterval = bybitIntervalMap[interval] || "15";

	for (const category of ["linear", "spot"]) {
		try {
			const params = new URLSearchParams({
				category,
				symbol: cleanSymbol,
				interval: bInterval,
				limit: String(Math.min(limit, 1000)),
			});
			if (startTime) params.append("start", String(startTime));
			if (endTime) params.append("end", String(endTime));

			const controller = new AbortController();
			const timeoutId = setTimeout(() => controller.abort(), 4000);
			const resp = await fetch(
				`https://api.bybit.com/v5/market/kline?${params.toString()}`,
				{ signal: controller.signal },
			);
			clearTimeout(timeoutId);

			if (resp.ok) {
				const json = await resp.json();
				const list = json?.result?.list;
				if (Array.isArray(list) && list.length > 0) {
					// Bybit returns newest first, reverse/sort ascending
					const mapped = [...list]
						.map((item: string[]) => [
							Number(item[0]),
							item[1],
							item[2],
							item[3],
							item[4],
							item[5],
						])
						.sort((a, b) => Number(a[0]) - Number(b[0]));
					return mapped as unknown as BinanceKline[];
				}
			}
		} catch {
			// Try next category
		}
	}
	return null;
}

/** Direct browser fetch from OKX V5 public REST API */
async function fetchOkxDirect(
	cleanSymbol: string,
	interval: string,
	startTime?: number,
	endTime?: number,
	limit: number = 500,
): Promise<BinanceKline[] | null> {
	const okxBarMap: Record<string, string> = {
		"1m": "1m",
		"3m": "3m",
		"5m": "5m",
		"15m": "15m",
		"30m": "30m",
		"1h": "1H",
		"2h": "2H",
		"4h": "4H",
		"1d": "1D",
	};
	const bar = okxBarMap[interval] || "15m";

	const quote = cleanSymbol.endsWith("USDC") ? "USDC" : "USDT";
	const base = cleanSymbol.endsWith(quote)
		? cleanSymbol.slice(0, -quote.length)
		: cleanSymbol;

	const instCandidates = [`${base}-${quote}-SWAP`, `${base}-${quote}`];

	for (const instId of instCandidates) {
		for (const path of ["/api/v5/market/candles", "/api/v5/market/history-candles"]) {
			try {
				const params = new URLSearchParams({
					instId,
					bar,
					limit: String(Math.min(limit, 300)),
				});
				// In OKX V5: "after" queries older than ts, "before" queries newer than ts
				if (endTime) params.append("after", String(endTime));
				if (startTime) params.append("before", String(startTime));

				const controller = new AbortController();
				const timeoutId = setTimeout(() => controller.abort(), 4000);
				const resp = await fetch(
					`https://www.okx.com${path}?${params.toString()}`,
					{ signal: controller.signal },
				);
				clearTimeout(timeoutId);

				if (resp.ok) {
					const json = await resp.json();
					const data = json?.data;
					if (Array.isArray(data) && data.length > 0) {
						// OKX returns newest first, sort ascending
						const mapped = [...data]
							.map((item: string[]) => [
								Number(item[0]),
								item[1],
								item[2],
								item[3],
								item[4],
								item[5],
							])
							.sort((a, b) => Number(a[0]) - Number(b[0]));
						return mapped as unknown as BinanceKline[];
					}
				}
			} catch {
				// Try next candidate
			}
		}
	}
	return null;
}

/** Direct browser fetch from Bitget V2 public REST API */
async function fetchBitgetDirect(
	cleanSymbol: string,
	interval: string,
	startTime?: number,
	endTime?: number,
	limit: number = 500,
): Promise<BinanceKline[] | null> {
	const bitgetGranMap: Record<string, string> = {
		"1m": "1m",
		"3m": "3m",
		"5m": "5m",
		"15m": "15m",
		"30m": "30m",
		"1h": "1h",
		"2h": "2h",
		"4h": "4h",
		"1d": "1d",
	};
	const granularity = bitgetGranMap[interval] || "15m";

	const endpoints = [
		`https://api.bitget.com/api/v2/mix/market/candles?symbol=${cleanSymbol}&granularity=${granularity}&productType=USDT-FUTURES&limit=${Math.min(limit, 1000)}`,
		`https://api.bitget.com/api/v2/spot/market/candles?symbol=${cleanSymbol}&granularity=${granularity}&limit=${Math.min(limit, 1000)}`,
	];

	for (let url of endpoints) {
		try {
			if (startTime) url += `&startTime=${startTime}`;
			if (endTime) url += `&endTime=${endTime}`;

			const controller = new AbortController();
			const timeoutId = setTimeout(() => controller.abort(), 4000);
			const resp = await fetch(url, { signal: controller.signal });
			clearTimeout(timeoutId);

			if (resp.ok) {
				const json = await resp.json();
				const data = json?.data;
				if (Array.isArray(data) && data.length > 0) {
					const mapped = [...data]
						.map((item: string[]) => [
							Number(item[0]),
							item[1],
							item[2],
							item[3],
							item[4],
							item[5],
						])
						.sort((a, b) => Number(a[0]) - Number(b[0]));
					return mapped as unknown as BinanceKline[];
				}
			}
		} catch {
			// Try next endpoint
		}
	}
	return null;
}

/** Direct browser fetch from WEEX public REST API */
async function fetchWeexDirect(
	cleanSymbol: string,
	interval: string,
	startTime?: number,
	endTime?: number,
	limit: number = 500,
): Promise<BinanceKline[] | null> {
	const weexIntervalMap: Record<string, string> = {
		"1m": "1m",
		"3m": "3m",
		"5m": "5m",
		"15m": "15m",
		"30m": "30m",
		"1h": "1h",
		"2h": "2h",
		"4h": "4h",
		"1d": "1d",
	};
	const wInterval = weexIntervalMap[interval] || "15m";
	const cmtSymbol = `cmt_${cleanSymbol.toLowerCase()}`;
	const limitParam = Math.min(limit, 300);

	const candidates: string[] = [];
	if (startTime || endTime) {
		candidates.push(
			`https://api-contract.weex.com/capi/v3/market/historyKlines?symbol=${cmtSymbol}&interval=${wInterval}&limit=${limitParam}`,
			`https://api.weex.com/capi/v3/market/historyKlines?symbol=${cmtSymbol}&interval=${wInterval}&limit=${limitParam}`,
			`https://api-spot.weex.com/api/v3/market/historyKlines?symbol=${cleanSymbol.toUpperCase()}&interval=${wInterval}&limit=${limitParam}`,
		);
	}
	candidates.push(
		`https://api-contract.weex.com/capi/v3/market/klines?symbol=${cmtSymbol}&interval=${wInterval}&limit=${limitParam}`,
		`https://api.weex.com/capi/v3/market/klines?symbol=${cmtSymbol}&interval=${wInterval}&limit=${limitParam}`,
		`https://api-spot.weex.com/api/v3/market/klines?symbol=${cleanSymbol.toUpperCase()}&interval=${wInterval}&limit=${limitParam}`,
	);

	for (let url of candidates) {
		try {
			if (startTime) url += `&startTime=${startTime}`;
			if (endTime) url += `&endTime=${endTime}`;

			const controller = new AbortController();
			const timeoutId = setTimeout(() => controller.abort(), 4000);
			const resp = await fetch(url, { signal: controller.signal });
			clearTimeout(timeoutId);

			if (resp.ok) {
				const json = await resp.json();
				const list = Array.isArray(json) ? json : json?.data;
				if (Array.isArray(list) && list.length > 0) {
					const mapped = [...list]
						.map((item: (string | number)[]) => [
							Number(item[0]),
							String(item[1]),
							String(item[2]),
							String(item[3]),
							String(item[4]),
							String(item[5] ?? 0),
						])
						.sort((a, b) => Number(a[0]) - Number(b[0]));
					return mapped as unknown as BinanceKline[];
				}
			}
		} catch {
			// Try next candidate
		}
	}
	return null;
}

/** Direct browser fetch from Binance public REST APIs & global mirrors */
async function fetchBinanceDirect(
	cleanSymbol: string,
	interval: string,
	startTime?: number,
	endTime?: number,
	limit: number = 500,
): Promise<BinanceKline[] | null> {
	const params = new URLSearchParams({
		symbol: cleanSymbol,
		interval,
		limit: String(Math.min(limit, 1000)),
	});
	if (startTime) params.append("startTime", String(startTime));
	if (endTime) params.append("endTime", String(endTime));

	const endpoints = [
		`https://fapi.binance.com/fapi/v1/klines?${params.toString()}`,
		`https://api.binance.com/api/v3/klines?${params.toString()}`,
		`https://api1.binance.com/api/v3/klines?${params.toString()}`,
		`https://data-api.binance.vision/api/v3/klines?${params.toString()}`,
	];

	for (const url of endpoints) {
		try {
			const controller = new AbortController();
			const timeoutId = setTimeout(() => controller.abort(), 3500);
			const resp = await fetch(url, { signal: controller.signal });
			clearTimeout(timeoutId);

			if (resp.ok) {
				const data = await resp.json();
				if (Array.isArray(data) && data.length > 0) {
					return data as BinanceKline[];
				}
			}
		} catch {
			// Try next mirror
		}
	}
	return null;
}

/** Direct browser fetch from Hyperliquid public API */
async function fetchHyperliquidDirect(
	cleanSymbol: string,
	interval: string,
	startTime?: number,
	endTime?: number,
): Promise<BinanceKline[] | null> {
	const hlIntervalMap: Record<string, string> = {
		"1m": "1m",
		"3m": "5m",
		"5m": "5m",
		"15m": "15m",
		"30m": "30m",
		"1h": "1h",
		"2h": "2h",
		"4h": "4h",
		"1d": "1d",
	};
	const hInterval = hlIntervalMap[interval] || "15m";
	let coin = cleanSymbol.replace(/USDT$|USDC$|USD$/, "");
	if (coin.startsWith("1000")) coin = `k${coin.slice(4)}`;

	try {
		const controller = new AbortController();
		const timeoutId = setTimeout(() => controller.abort(), 4000);
		const resp = await fetch("https://api.hyperliquid.xyz/info", {
			method: "POST",
			headers: { "Content-Type": "application/json" },
			body: JSON.stringify({
				type: "candleSnapshot",
				req: {
					coin,
					interval: hInterval,
					startTime: startTime || Date.now() - 24 * 3600 * 1000,
					endTime: endTime || Date.now(),
				},
			}),
			signal: controller.signal,
		});
		clearTimeout(timeoutId);

		if (resp.ok) {
			const list = await resp.json();
			if (Array.isArray(list) && list.length > 0) {
				const mapped = list
					.map((d: { t: number; o: string; h: string; l: string; c: string; v: string }) => [
						Number(d.t),
						d.o,
						d.h,
						d.l,
						d.c,
						d.v,
					])
					.sort((a, b) => Number(a[0]) - Number(b[0]));
				return mapped as unknown as BinanceKline[];
			}
		}
	} catch {
		// Ignore
	}
	return null;
}

/**
 * Fetches Kline/Candlestick data directly from public exchange APIs with zero backend load.
 * Tries the requested exchange first, then seamlessly falls back across Bybit, OKX, Bitget, and Binance.
 *
 * @param symbol The trading symbol (e.g., BTCUSDT, XRPUSDT)
 * @param interval The kline interval (e.g., '15m', '1h', '4h')
 * @param startTime Optional start time in milliseconds
 * @param endTime Optional end time in milliseconds
 * @param limit Optional limit, default 500, max 1000
 * @param exchange The exchange name (e.g., 'weex', 'bybit', 'okx', 'bitget', 'binance', 'hyperliquid')
 * @returns Promise<BinanceKline[]>
 */
export const fetchBinanceKlines = async (
	symbol: string,
	interval: string,
	startTime?: number,
	endTime?: number,
	limit: number = 500,
	exchange?: string | null,
): Promise<BinanceKline[]> => {
	const cleanSymbol = symbol.replace(/[^a-zA-Z0-9]/g, "").toUpperCase();
	const primaryEx = normalizeExchangeName(exchange);

	// Priority order: primary exchange first, followed by major liquidity sources
	const exchangeOrder: string[] = [primaryEx];
	const fallbacks = ["bybit", "bitget", "okx", "binance", "weex", "hyperliquid"];
	for (const fb of fallbacks) {
		if (!exchangeOrder.includes(fb)) {
			exchangeOrder.push(fb);
		}
	}

	let latestFallbackCandles: BinanceKline[] | null = null;

	for (const ex of exchangeOrder) {
		let res: BinanceKline[] | null = null;
		if (ex === "bybit") {
			res = await fetchBybitDirect(cleanSymbol, interval, startTime, endTime, limit);
		} else if (ex === "bitget") {
			res = await fetchBitgetDirect(cleanSymbol, interval, startTime, endTime, limit);
		} else if (ex === "okx") {
			res = await fetchOkxDirect(cleanSymbol, interval, startTime, endTime, limit);
		} else if (ex === "weex") {
			res = await fetchWeexDirect(cleanSymbol, interval, startTime, endTime, limit);
		} else if (ex === "hyperliquid") {
			res = await fetchHyperliquidDirect(cleanSymbol, interval, startTime, endTime);
		} else if (ex === "binance") {
			res = await fetchBinanceDirect(cleanSymbol, interval, startTime, endTime, limit);
		}

		if (res && res.length > 0) {
			if (!latestFallbackCandles) {
				latestFallbackCandles = res;
			}
			// When a specific trade time range is requested (startTime/endTime),
			// verify that the returned candles actually overlap the trade window.
			// If an exchange returns candles that start after endTime or end before startTime,
			// it returned out-of-range data (e.g. current-day candles instead of historical trade).
			if (startTime || endTime) {
				const firstTime = Number(res[0][0]);
				const lastTime = Number(res[res.length - 1][0]);
				if (endTime && firstTime > endTime) {
					continue; // All returned candles are in the future relative to the trade
				}
				if (startTime && lastTime < startTime) {
					continue; // All returned candles are in the past relative to the trade
				}
			}
			return res;
		}
	}

	if (latestFallbackCandles) {
		return latestFallbackCandles;
	}

	// If all direct client fetches failed and user has an auth token, try backend proxy
	const token = localStorage.getItem("token");
	if (token) {
		try {
			const params = new URLSearchParams({
				symbol: cleanSymbol,
				interval,
				exchange: primaryEx,
				limit: String(limit),
			});
			if (startTime) params.append("startTime", String(startTime));
			if (endTime) params.append("endTime", String(endTime));

			const response = await fetch(`${PROXY_KLINE_URL}?${params.toString()}`, {
				headers: {
					Authorization: `Bearer ${token}`,
				},
			});

			if (response.ok) {
				const data = await response.json();
				if (Array.isArray(data) && data.length > 0) {
					return data as BinanceKline[];
				}
			}
		} catch {
			// Proxy fallback failed
		}
	}

	throw new Error(`Unable to load live candles for ${cleanSymbol} from exchange feeds.`);
};
