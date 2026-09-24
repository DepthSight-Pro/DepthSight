// pwa/services/liveMarks/bybit.ts
// Bybit v5 public linear tickers (no auth, one socket).
import {
	type CreateMarksAdapter,
	type MarksCallback,
	cleanSymbol,
} from "./types";

const URL = "wss://stream.bybit.com/v5/public/linear";

interface BybitTickerData {
	symbol?: unknown;
	markPrice?: unknown;
	lastPrice?: unknown;
}

export const createBybitAdapter: CreateMarksAdapter = (
	onTick: MarksCallback,
) => {
	let ws: WebSocket | null = null;
	let symbols: string[] = [];
	let closed = false;
	let retryTimer: ReturnType<typeof setTimeout> | null = null;

	const connect = () => {
		if (closed || symbols.length === 0) return;
		ws = new WebSocket(URL);
		ws.onopen = () => {
			if (!ws || ws.readyState !== WebSocket.OPEN) return;
			ws.send(
				JSON.stringify({
					op: "subscribe",
					args: symbols.map((s) => `tickers.${s}`),
				}),
			);
		};
		ws.onmessage = (ev) => {
			try {
				const msg = JSON.parse(ev.data as string) as {
					topic?: unknown;
					data?: BybitTickerData;
				};
				const d = msg?.data;
				if (!d) return;
				if (
					msg?.topic !== undefined &&
					!String(msg.topic).startsWith("tickers.")
				)
					return;
				const sym = cleanSymbol(String(d.symbol ?? ""));
				const price = Number(d.markPrice ?? d.lastPrice);
				if (!sym || !Number.isFinite(price) || price <= 0) return;
				onTick({ symbol: sym, price, ts: Date.now(), exchange: "bybit" });
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
			else {
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
