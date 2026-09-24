// pwa/services/liveMarks/bitget.ts
// Bitget v2 public ticker (no auth). USDT-FUTURES uses "BTCUSDT".
import {
	type CreateMarksAdapter,
	type MarksCallback,
	cleanSymbol,
} from "./types";

const URL = "wss://ws.bitget.com/v2/ws/public";

interface BitgetTicker {
	instId?: unknown;
	markPrice?: unknown;
	lastPr?: unknown;
}

export const createBitgetAdapter: CreateMarksAdapter = (
	onTick: MarksCallback,
) => {
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
					instType: "USDT-FUTURES",
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
				const msg = JSON.parse(ev.data as string) as {
					arg?: { instId?: unknown };
					data?: BitgetTicker[];
				};
				const arr = msg?.data;
				if (!Array.isArray(arr) || arr.length === 0) return;
				const d = arr[0];
				const sym = cleanSymbol(String(msg?.arg?.instId ?? d?.instId ?? ""));
				const price = Number(d?.markPrice ?? d?.lastPr);
				if (!sym || !Number.isFinite(price) || price <= 0) return;
				onTick({ symbol: sym, price, ts: Date.now(), exchange: "bitget" });
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
