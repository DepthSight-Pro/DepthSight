// frontend/src/services/liveMarks/hyperliquid.ts
// Hyperliquid public websocket (allMids channel, no auth):
// Single lightweight subscription yields mid prices across all coins.
import {
	type CreateMarksAdapter,
	type LiveMarket,
	type MarksCallback,
	cleanSymbol,
} from "./types";

const URL = "wss://api.hyperliquid.xyz/ws";
const PING_INTERVAL_MS = 30_000;

const toBaseCoin = (sym: string): string => {
	const cleaned = cleanSymbol(sym);
	return cleaned.replace(/(USDT|USDC|PERP)$/, "") || cleaned;
};

const createHyperliquidWsAdapter = (
	onTick: MarksCallback,
	market: LiveMarket,
): ReturnType<CreateMarksAdapter> => {
	let ws: WebSocket | null = null;
	let symbols: string[] = [];
	let closed = false;
	let retryTimer: ReturnType<typeof setTimeout> | null = null;
	let pingTimer: ReturnType<typeof setInterval> | null = null;

	const clearTimers = () => {
		if (retryTimer) {
			clearTimeout(retryTimer);
			retryTimer = null;
		}
		if (pingTimer) {
			clearInterval(pingTimer);
			pingTimer = null;
		}
	};

	const sendSub = () => {
		if (!ws || ws.readyState !== WebSocket.OPEN) return;
		try {
			ws.send(
				JSON.stringify({
					method: "subscribe",
					subscription: { type: "allMids" },
				}),
			);
		} catch {
			/* ignore */
		}
	};

	const connect = () => {
		if (closed || symbols.length === 0) return;
		clearTimers();

		try {
			ws = new WebSocket(URL);
		} catch {
			retryTimer = setTimeout(connect, 3000);
			return;
		}

		ws.onopen = () => {
			sendSub();
			pingTimer = setInterval(() => {
				if (ws && ws.readyState === WebSocket.OPEN) {
					try {
						ws.send(JSON.stringify({ method: "ping" }));
					} catch {
						/* noop */
					}
				}
			}, PING_INTERVAL_MS);
		};

		ws.onmessage = (ev) => {
			try {
				const msg = JSON.parse(ev.data as string);
				if (msg?.channel !== "allMids" || !msg?.data?.mids) return;

				const mids: Record<string, string> = msg.data.mids;
				const now = Date.now();

				for (const sym of symbols) {
					const base = toBaseCoin(sym);
					const rawPrice = mids[base] ?? mids[sym];
					if (!rawPrice) continue;

					const price = Number(rawPrice);
					if (Number.isFinite(price) && price > 0) {
						onTick({
							symbol: sym,
							price,
							ts: now,
							exchange: "hyperliquid",
							market,
						});
					}
				}
			} catch {
				/* ignore malformed frame */
			}
		};

		ws.onclose = () => {
			clearTimers();
			if (!closed && symbols.length > 0) {
				retryTimer = setTimeout(connect, 3000);
			}
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
				clearTimers();
				try {
					ws?.close();
				} catch {
					/* noop */
				}
				ws = null;
				return;
			}
			if (!ws || ws.readyState === WebSocket.CLOSED) {
				connect();
			} else if (ws.readyState === WebSocket.OPEN) {
				sendSub();
			}
		},
		close: () => {
			closed = true;
			clearTimers();
			try {
				ws?.close();
			} catch {
				/* noop */
			}
			ws = null;
		},
	};
};

export const createHyperliquidFuturesAdapter: CreateMarksAdapter = (onTick) =>
	createHyperliquidWsAdapter(onTick, "futures");

export const createHyperliquidSpotAdapter: CreateMarksAdapter = (onTick) =>
	createHyperliquidWsAdapter(onTick, "spot");

