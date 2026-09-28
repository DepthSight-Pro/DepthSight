// pwa/services/liveMarks/bitget.ts
// Bitget v2 public ticker (no auth, one socket per market):
// - futures: instType USDT-FUTURES, "BTCUSDT" (markPrice ?? lastPr)
// - spot:    instType SPOT,         "BTCUSDT" (lastPr, no markPrice)
import {
	type CreateMarksAdapter,
	type LiveMarket,
	type MarksCallback,
	cleanSymbol,
} from "./types";

const URL = "wss://ws.bitget.com/v2/ws/public";

const createBitgetWsAdapter = (
	onTick: MarksCallback,
	market: LiveMarket,
): ReturnType<CreateMarksAdapter> => {
	const instType = market === "spot" ? "SPOT" : "USDT-FUTURES";
	let ws: WebSocket | null = null;
	let symbols: string[] = [];
	let closed = false;
	let retryTimer: ReturnType<typeof setTimeout> | null = null;

	const sendSubs = () => {
		if (!ws || ws.readyState !== WebSocket.OPEN) return;
		ws.send(
			JSON.stringify({
				op: "subscribe",
				args: symbols.map((s) => ({
					instType,
					channel: "ticker",
					instId: cleanSymbol(s),
				})),
			}),
		);
	};

	const connect = () => {
		if (closed || symbols.length === 0) return;
		ws = new WebSocket(URL);
		ws.onopen = sendSubs;
		ws.onmessage = (ev) => {
			try {
				const msg = JSON.parse(ev.data as string);
				const arr = msg?.data;
				if (!Array.isArray(arr) || arr.length === 0) return;
				const d = arr[0];
				const sym = cleanSymbol(String(msg?.arg?.instId ?? d?.instId ?? ""));
				if (!sym || !symbols.includes(sym)) return;
				const price =
					market === "spot"
						? Number(d?.lastPr ?? d?.markPrice)
						: Number(d?.markPrice ?? d?.lastPr);
				if (!Number.isFinite(price) || price <= 0) return;
				onTick({ symbol: sym, price, ts: Date.now(), exchange: "bitget", market });
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
			else if (ws.readyState === WebSocket.OPEN) sendSubs();
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

export const createBitgetFuturesAdapter: CreateMarksAdapter = (onTick) =>
	createBitgetWsAdapter(onTick, "futures");

export const createBitgetSpotAdapter: CreateMarksAdapter = (onTick) =>
	createBitgetWsAdapter(onTick, "spot");

/** Legacy default: futures socket (kept for backward compat). */
export const createBitgetAdapter: CreateMarksAdapter = createBitgetFuturesAdapter;
