// frontend/src/services/liveMarks/okx.ts
// OKX public tickers (no auth, one socket per market):
// - futures: BTCUSDT -> BTC-USDT-SWAP (markPx ?? last)
// - spot:    BTCUSDT -> BTC-USDT      (last ?? markPx)
import {
	type CreateMarksAdapter,
	type LiveMarket,
	type MarksCallback,
	cleanSymbol,
} from "./types";
import { toOkxInstId, toOkxSpotInstId } from "./symbolMap";

const URL = "wss://ws.okx.com:8443/ws/v5/public";

const createOkxWsAdapter = (
	onTick: MarksCallback,
	market: LiveMarket,
): ReturnType<CreateMarksAdapter> => {
	const toInstId = market === "spot" ? toOkxSpotInstId : toOkxInstId;
	let ws: WebSocket | null = null;
	let symbols: string[] = [];
	let closed = false;
	let retryTimer: ReturnType<typeof setTimeout> | null = null;
	const instToUnified = new Map<string, string>();

	const sendSubs = () => {
		if (!ws || ws.readyState !== WebSocket.OPEN) return;
		instToUnified.clear();
		for (const s of symbols) instToUnified.set(toInstId(s), s);
		ws.send(
			JSON.stringify({
				op: "subscribe",
				args: symbols.map((s) => ({ channel: "tickers", instId: toInstId(s) })),
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
				const instId = String(msg?.arg?.instId ?? d?.instId ?? "");
				const unified =
					instToUnified.get(instId) ?? cleanSymbol(instId.replace(/-/g, ""));
				if (!unified || !symbols.includes(unified)) return;
				const price =
					market === "spot"
						? Number(d?.last ?? d?.markPx)
						: Number(d?.markPx ?? d?.last);
				if (!Number.isFinite(price) || price <= 0) return;
				onTick({ symbol: unified, price, ts: Date.now(), exchange: "okx", market });
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

export const createOkxFuturesAdapter: CreateMarksAdapter = (onTick) =>
	createOkxWsAdapter(onTick, "futures");

export const createOkxSpotAdapter: CreateMarksAdapter = (onTick) =>
	createOkxWsAdapter(onTick, "spot");

/** Legacy default: futures socket (kept for backward compat). */
export const createOkxAdapter: CreateMarksAdapter = createOkxFuturesAdapter;
