// frontend/src/services/liveMarks/okx.ts
// OKX public tickers (no auth). BTCUSDT -> BTC-USDT-SWAP.
import {
	type CreateMarksAdapter,
	type MarksCallback,
	cleanSymbol,
} from "./types";
import { toOkxInstId } from "./symbolMap";

const URL = "wss://ws.okx.com:8443/ws/v5/public";

export const createOkxAdapter: CreateMarksAdapter = (onTick: MarksCallback) => {
	let ws: WebSocket | null = null;
	let symbols: string[] = [];
	let closed = false;
	let retryTimer: ReturnType<typeof setTimeout> | null = null;
	const instToUnified = new Map<string, string>();

	const sendSubs = () => {
		if (!ws || ws.readyState !== WebSocket.OPEN) return;
		instToUnified.clear();
		for (const s of symbols) instToUnified.set(toOkxInstId(s), s);
		ws.send(
			JSON.stringify({
				op: "subscribe",
				args: symbols.map((s) => ({ channel: "tickers", instId: toOkxInstId(s) })),
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
				const price = Number(d?.markPx ?? d?.last);
				if (!unified || !Number.isFinite(price) || price <= 0) return;
				onTick({ symbol: unified, price, ts: Date.now(), exchange: "okx" });
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
