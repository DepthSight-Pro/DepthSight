// pwa/services/liveMarks/binance.ts
// Binance Futures public markPrice stream (no auth, one socket for all symbols).
import {
	type CreateMarksAdapter,
	type MarksCallback,
	cleanSymbol,
} from "./types";
import { toBinanceStream } from "./symbolMap";

export const createBinanceAdapter: CreateMarksAdapter = (
	onTick: MarksCallback,
) => {
	let ws: WebSocket | null = null;
	let symbols: string[] = [];
	let closed = false;
	let retryTimer: ReturnType<typeof setTimeout> | null = null;

	const connect = () => {
		if (closed || symbols.length === 0) return;
		const streams = symbols.map(toBinanceStream).join("/");
		ws = new WebSocket(`wss://fstream.binance.com/stream?streams=${streams}`);
		ws.onmessage = (ev) => {
			try {
				const msg = JSON.parse(ev.data as string);
				const d = msg?.data as Record<string, unknown> | undefined;
				if (!d) return;
				const sym = cleanSymbol(String(d.s ?? ""));
				const price = Number(d.p ?? d.c);
				if (!sym || !Number.isFinite(price) || price <= 0) return;
				onTick({ symbol: sym, price, ts: Date.now(), exchange: "binance" });
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
