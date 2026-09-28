// frontend/src/services/liveMarks/bybit.ts
// Bybit v5 public tickers (no auth, one socket):
// - futures: wss://stream.bybit.com/v5/public/linear (markPrice ?? lastPrice)
// - spot:    wss://stream.bybit.com/v5/public/spot   (lastPrice, no mark)
import {
	type CreateMarksAdapter,
	type LiveMarket,
	type MarksCallback,
	cleanSymbol,
} from "./types";

const FUTURES_URL = "wss://stream.bybit.com/v5/public/linear";
const SPOT_URL = "wss://stream.bybit.com/v5/public/spot";

const createBybitWsAdapter = (
	onTick: MarksCallback,
	market: LiveMarket,
): ReturnType<CreateMarksAdapter> => {
	let ws: WebSocket | null = null;
	let symbols: string[] = [];
	let closed = false;
	let retryTimer: ReturnType<typeof setTimeout> | null = null;

	const sendSubs = () => {
		if (!ws || ws.readyState !== WebSocket.OPEN) return;
		ws.send(
			JSON.stringify({
				op: "subscribe",
				args: symbols.map((s) => `tickers.${s}`),
			}),
		);
	};

	const connect = () => {
		if (closed || symbols.length === 0) return;
		ws = new WebSocket(market === "spot" ? SPOT_URL : FUTURES_URL);
		ws.onopen = sendSubs;
		ws.onmessage = (ev) => {
			try {
				const msg = JSON.parse(ev.data as string);
				const d = msg?.data;
				if (!d || msg?.topic !== undefined && !String(msg.topic).startsWith("tickers."))
					return;
				// v5 tickers: { topic:"tickers.BTCUSDT", data:{ symbol, markPrice, lastPrice } }
				const sym = cleanSymbol(String(d.symbol ?? ""));
				if (!sym || !symbols.includes(sym)) return;
				const price =
					market === "spot"
						? Number(d.lastPrice ?? d.markPrice)
						: Number(d.markPrice ?? d.lastPrice);
				if (!Number.isFinite(price) || price <= 0) return;
				onTick({ symbol: sym, price, ts: Date.now(), exchange: "bybit", market });
			} catch {
				/* ignore */
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

	return {
		setSymbols: (next: string[]) => {
			const cleaned = [...new Set(next.map(cleanSymbol))].filter(Boolean);
			const same = cleaned.join(",") === symbols.join(",");
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
			else if (!same) {
				// simplest robust path: reconnect with new arg list
				try {
					ws?.close();
				} catch {
					/* noop */
				}
			}
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

export const createBybitFuturesAdapter: CreateMarksAdapter = (onTick) =>
	createBybitWsAdapter(onTick, "futures");

export const createBybitSpotAdapter: CreateMarksAdapter = (onTick) =>
	createBybitWsAdapter(onTick, "spot");

/** Legacy default: futures socket (kept for backward compat). */
export const createBybitAdapter: CreateMarksAdapter = createBybitFuturesAdapter;
