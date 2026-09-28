// pwa/services/liveMarks/binance.ts
// Binance public streams (no auth, one socket for all symbols):
// - futures: wss://fstream.binance.com markPrice@1s (mark `p`, fallback `c`)
// - spot:    wss://stream.binance.com:9443 miniTicker (last `c`, 1s)
import {
	type CreateMarksAdapter,
	type LiveMarket,
	type MarksCallback,
	cleanSymbol,
} from "./types";
import { toBinanceFuturesStream, toBinanceSpotStream } from "./symbolMap";

const FUTURES_BASE = "wss://fstream.binance.com/stream?streams=";
const SPOT_BASE = "wss://stream.binance.com:9443/stream?streams=";

const createBinanceWsAdapter = (
	onTick: MarksCallback,
	market: LiveMarket,
): ReturnType<CreateMarksAdapter> => {
	const toStream = market === "spot" ? toBinanceSpotStream : toBinanceFuturesStream;
	let ws: WebSocket | null = null;
	let symbols: string[] = [];
	let closed = false;
	let retryTimer: ReturnType<typeof setTimeout> | null = null;

	const connect = () => {
		if (closed || symbols.length === 0) return;
		const streams = symbols.map(toStream).join("/");
		const base = market === "spot" ? SPOT_BASE : FUTURES_BASE;
		ws = new WebSocket(`${base}${streams}`);
		ws.onmessage = (ev) => {
			try {
				const msg = JSON.parse(ev.data as string);
				const d = msg?.data;
				if (!d) return;
				// markPrice stream: { s: "BTCUSDT", p: "67234.5", T: ... }
				// miniTicker stream: { s: "BTCUSDT", c: "67230.1", ... }
				const sym = cleanSymbol(String(d.s ?? ""));
				if (!sym || !symbols.includes(sym)) return;
				const price =
					market === "spot" ? Number(d.c) : Number(d.p ?? d.c);
				if (!Number.isFinite(price) || price <= 0) return;
				onTick({ symbol: sym, price, ts: Date.now(), exchange: "binance", market });
			} catch {
				/* ignore malformed tick */
			}
		};
		ws.onclose = () => {
			if (closed) return;
			retryTimer = setTimeout(connect, 3000);
		};
		ws.onerror = () => {
			try {
				ws?.close();
			} catch {
				/* noop */
			}
		};
	};

	const reconnect = () => {
		try {
			ws?.close();
		} catch {
			/* noop */
		}
		ws = null;
		if (retryTimer) clearTimeout(retryTimer);
		retryTimer = setTimeout(connect, 300);
	};

	return {
		setSymbols: (next: string[]) => {
			const cleaned = [...new Set(next.map(cleanSymbol))].filter(Boolean);
			if (cleaned.join(",") === symbols.join(",")) return;
			symbols = cleaned;
			if (symbols.length === 0) {
				try {
					ws?.close();
				} catch {
					/* noop */
				}
				return;
			}
			if (!ws || ws.readyState === WebSocket.CLOSED) connect();
			else reconnect();
		},
		close: () => {
			closed = true;
			if (retryTimer) clearTimeout(retryTimer);
			try {
				ws?.close();
			} catch {
				/* noop */
			}
		},
	};
};

export const createBinanceFuturesAdapter: CreateMarksAdapter = (onTick) =>
	createBinanceWsAdapter(onTick, "futures");

export const createBinanceSpotAdapter: CreateMarksAdapter = (onTick) =>
	createBinanceWsAdapter(onTick, "spot");

/** Legacy default: futures socket (kept for backward compat). */
export const createBinanceAdapter: CreateMarksAdapter = createBinanceFuturesAdapter;
