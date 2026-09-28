// pwa/services/liveMarks/weex.ts
// WEEX V3 public ticker over WebSocket (no auth):
// - futures: wss://ws-contract.weex.com/v3/ws/public, price = mark (d.m ?? d.c)
// - spot:    wss://ws-spot.weex.com/v3/ws/public,    price = last (d.c ?? d.m)
// Subscribe: {"method":"SUBSCRIBE","params":["BTCUSDT@ticker"],"id":1}
// Server pings {"event":"ping",...} -> reply {"method":"PONG","id":1}.
// REST fallback via backend ccxt proxy (getProxyKlines limit=1) stays as a
// safety net and only fires while the socket is unhealthy (no ticks >10s).
import { api } from "../api";
import {
	type CreateMarksAdapter,
	type LiveMarket,
	type MarksCallback,
	cleanSymbol,
} from "./types";

const FUTURES_URL = "wss://ws-contract.weex.com/v3/ws/public";
const SPOT_URL = "wss://ws-spot.weex.com/v3/ws/public";

const RETRY_MS = 3000;
const POLL_MS = 5000;
const STALE_MS = 10_000;

interface TickerEntry {
	c?: unknown;
	m?: unknown;
}

const num = (value: unknown): number | null => {
	const n =
		typeof value === "string" || typeof value === "number" ? Number(value) : NaN;
	return Number.isFinite(n) && n > 0 ? n : null;
};

/** Futures ticker: {e:"ticker", s, d:[{m, c, ...}]}; spot: {e:"24hrTicker", ...}.
 * Spot payload has no mark price — fall back to last trade. */
const pickPrice = (entry: TickerEntry, market: LiveMarket): number | null =>
	market === "spot"
		? (num(entry.c) ?? num(entry.m))
		: (num(entry.m) ?? num(entry.c));

const createWeexWsAdapter = (
	onTick: MarksCallback,
	market: LiveMarket,
	url: string,
): ReturnType<CreateMarksAdapter> => {
	let symbols: string[] = [];
	let subscribed: string[] = [];
	let subscribedKey = "";
	let closed = false;
	let ws: WebSocket | null = null;
	let retryTimer: ReturnType<typeof setTimeout> | null = null;
	let pollTimer: ReturnType<typeof setInterval> | null = null;
	let lastTickTs = 0;

	const emit = (symbol: string, price: number) => {
		lastTickTs = Date.now();
		onTick({ symbol, price, ts: lastTickTs, exchange: "weex", market });
	};

	const send = (payload: unknown) => {
		try {
			if (ws && ws.readyState === WebSocket.OPEN) {
				ws.send(JSON.stringify(payload));
			}
		} catch {
			/* ignore send failure — reconnect loop will recover */
		}
	};

	const syncSubscriptions = () => {
		if (!ws || ws.readyState !== WebSocket.OPEN) return;
		const key = symbols.join(",");
		if (key === subscribedKey) return;
		const prev = new Set(subscribed);
		const next = new Set(symbols);
		const added = symbols.filter((s) => !prev.has(s));
		const removed = subscribed.filter((s) => !next.has(s));
		if (removed.length > 0) {
			send({
				method: "UNSUBSCRIBE",
				params: removed.map((s) => `${s}@ticker`),
				id: Date.now(),
			});
		}
		if (added.length > 0) {
			send({
				method: "SUBSCRIBE",
				params: added.map((s) => `${s}@ticker`),
				id: Date.now(),
			});
		}
		subscribed = [...symbols];
		subscribedKey = key;
	};

	const handleMessage = (raw: unknown) => {
		if (!raw || typeof raw !== "object") return;
		const msg = raw as Record<string, unknown>;
		// Server heartbeat — must reply or the connection gets terminated.
		if (msg.event === "ping") {
			send({ method: "PONG", id: 1 });
			return;
		}
		// Subscription ack {result, id} — nothing to do.
		if ("result" in msg && !("e" in msg)) return;
		const event = String(msg.e ?? "");
		if (event !== "ticker" && event !== "24hrTicker") return;
		const sym = cleanSymbol(String(msg.s ?? ""));
		if (!sym || !symbols.includes(sym)) return;
		const data = msg.d;
		const entries: TickerEntry[] = Array.isArray(data)
			? (data as TickerEntry[])
			: data && typeof data === "object"
				? [data as TickerEntry]
				: [];
		if (entries.length === 0) return;
		const price = pickPrice(entries[0], market);
		if (price !== null) emit(sym, price);
	};

	const connect = () => {
		if (closed || symbols.length === 0) return;
		try {
			ws = new WebSocket(url);
		} catch {
			scheduleRetry();
			return;
		}
		ws.onopen = () => {
			subscribed = [];
			subscribedKey = "";
			syncSubscriptions();
		};
		ws.onmessage = (ev) => {
			try {
				handleMessage(JSON.parse(ev.data as string));
			} catch {
				/* ignore malformed tick */
			}
		};
		ws.onerror = () => {
			try {
				ws?.close();
			} catch {
				/* noop */
			}
		};
		ws.onclose = () => {
			ws = null;
			if (!closed) scheduleRetry();
		};
	};

	const scheduleRetry = () => {
		if (closed || retryTimer) return;
		retryTimer = setTimeout(() => {
			retryTimer = null;
			connect();
		}, RETRY_MS);
	};

	// Emergency fallback: backend klines proxy (futures-biased) — only while
	// the socket is down or silent, so a blocked WS never freezes the UI.
	const pollOnce = async () => {
		if (closed || symbols.length === 0) return;
		if (ws && ws.readyState === WebSocket.OPEN && Date.now() - lastTickTs <= STALE_MS) {
			return;
		}
		await Promise.all(
			symbols.map(async (s) => {
				try {
					const rows = await api.getProxyKlines(s, "1m", "weex", 1);
					const last = Array.isArray(rows) ? rows[rows.length - 1] : null;
					const price = last ? Number(last[4]) : NaN;
					if (Number.isFinite(price) && price > 0) {
						emit(s, price);
					}
				} catch {
					/* ignore single-symbol failure */
				}
			}),
		);
	};

	const ensurePoller = () => {
		if (pollTimer || closed || symbols.length === 0) return;
		void pollOnce();
		pollTimer = setInterval(pollOnce, POLL_MS);
	};

	const stopPoller = () => {
		if (pollTimer) clearInterval(pollTimer);
		pollTimer = null;
	};

	return {
		setSymbols: (next: string[]) => {
			const cleaned = [...new Set(next.map(cleanSymbol))].filter(Boolean);
			const same = cleaned.join(",") === symbols.join(",");
			symbols = cleaned;
			if (symbols.length === 0) {
				stopPoller();
				subscribed = [];
				subscribedKey = "";
				try {
					ws?.close();
				} catch {
					/* noop */
				}
				return;
			}
			if (!ws || ws.readyState === WebSocket.CLOSED) connect();
			else if (!same) syncSubscriptions();
			ensurePoller();
		},
		close: () => {
			closed = true;
			stopPoller();
			if (retryTimer) clearTimeout(retryTimer);
			try {
				ws?.close();
			} catch {
				/* noop */
			}
			ws = null;
		},
	};
};

export const createWeexFuturesAdapter: CreateMarksAdapter = (onTick) =>
	createWeexWsAdapter(onTick, "futures", FUTURES_URL);

export const createWeexSpotAdapter: CreateMarksAdapter = (onTick) =>
	createWeexWsAdapter(onTick, "spot", SPOT_URL);

/** Legacy default: futures socket (kept for backward compat). */
export const createWeexAdapter: CreateMarksAdapter = createWeexFuturesAdapter;
