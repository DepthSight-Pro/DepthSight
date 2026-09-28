// frontend/src/services/liveMarks/funding.ts
// Client-side funding-rate feed over public exchange websockets
// (no auth, no backend). Dedicated lightweight sockets, opened only while
// a consumer (e.g. the hedge funding widget) is subscribed.
// Existing mark-price adapters are intentionally left untouched.

import { cleanSymbol } from "./types";

export interface FundingTick {
	symbol: string; // unified, e.g. "BTCUSDT"
	exchange: string; // normalized: binance|bybit|okx|bitget|weex
	ts: number; // ms, local receipt time
	/** Funding rate as a decimal (0.0001 = +0.0100%). Null when unknown. */
	rate: number | null;
	/** Next settlement timestamp (ms). Null when the venue doesn't send it. */
	nextFundingMs?: number | null;
	/** Settlement interval in hours. Defaults per venue (usually 8). */
	intervalHours?: number | null;
}

export type FundingCallback = (tick: FundingTick) => void;

export interface FundingHandle {
	close: () => void;
}

const RETRY_MS = 3000;

function num(value: unknown): number | null {
	const n =
		typeof value === "string" || typeof value === "number" ? Number(value) : NaN;
	return Number.isFinite(n) ? n : null;
}

/** First finite number found under any of the given keys (object or [obj]). */
function firstNum(data: unknown, keys: string[]): number | null {
	const obj = Array.isArray(data) ? data[0] : data;
	if (!obj || typeof obj !== "object") return null;
	for (const key of keys) {
		const v = num((obj as Record<string, unknown>)[key]);
		if (v !== null) return v;
	}
	return null;
}

function firstNumMs(data: unknown, keys: string[]): number | null {
	const v = firstNum(data, keys);
	if (v === null || v <= 0) return null;
	// Exchanges send ms; tolerate seconds just in case.
	return v < 1e12 ? v * 1000 : v;
}

interface SocketHooks {
	onOpen: (ws: WebSocket) => void;
	onMessage: (ws: WebSocket, msg: unknown) => void;
}

function openSocket(url: string, hooks: SocketHooks): FundingHandle {
	let ws: WebSocket | null = null;
	let closed = false;
	let retry: ReturnType<typeof setTimeout> | null = null;

	const schedule = () => {
		if (closed || retry) return;
		retry = setTimeout(() => {
			retry = null;
			connect();
		}, RETRY_MS);
	};

	const connect = () => {
		if (closed) return;
		try {
			ws = new WebSocket(url);
		} catch {
			schedule();
			return;
		}
		ws.onopen = () => {
			try {
				hooks.onOpen(ws as WebSocket);
			} catch {
				/* ignore */
			}
		};
		ws.onmessage = (ev) => {
			try {
				hooks.onMessage(ws as WebSocket, JSON.parse(ev.data as string));
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
			if (!closed) schedule();
		};
	};

	connect();

	return {
		close: () => {
			closed = true;
			if (retry) clearTimeout(retry);
			try {
				ws?.close();
			} catch {
				/* noop */
			}
		},
	};
}

const emit =
	(
		cb: FundingCallback,
		exchange: string,
		symbol: string,
		partial: Omit<FundingTick, "symbol" | "exchange" | "ts">,
	) =>
	() =>
		cb({ symbol, exchange, ts: Date.now(), ...partial });

function subscribeBinance(symbol: string, cb: FundingCallback): FundingHandle {
	const sym = cleanSymbol(symbol).toLowerCase();
	const stream = `${sym}@markPrice@1s`;
	return openSocket(`wss://fstream.binance.com/stream?streams=${stream}`, {
		onOpen: () => {},
		onMessage: (_ws, msg) => {
			// markPrice stream: { data: { s, r: fundingRate, T: nextFundingMs } }
			const d = (msg as Record<string, unknown>)?.data;
			if (!d || typeof d !== "object") return;
			const streamSym = cleanSymbol(String((d as Record<string, unknown>).s ?? ""));
			if (streamSym && streamSym !== cleanSymbol(symbol)) return;
			emit(
				cb,
				"binance",
				cleanSymbol(symbol),
				{
					rate: num((d as Record<string, unknown>).r),
					nextFundingMs: firstNumMs(d, ["T"]),
					intervalHours: 8,
				},
			)();
		},
	});
}

function subscribeBybit(symbol: string, cb: FundingCallback): FundingHandle {
	const sym = cleanSymbol(symbol);
	return openSocket("wss://stream.bybit.com/v5/public/linear", {
		onOpen: (ws) =>
			ws.send(JSON.stringify({ op: "subscribe", args: [`tickers.${sym}`] })),
		onMessage: (_ws, msg) => {
			// v5 tickers: { topic: "tickers.BTCUSDT", data: { symbol, fundingRate } }
			const m = msg as Record<string, unknown>;
			const topic = String(m?.topic ?? "");
			if (topic && !topic.startsWith("tickers.")) return;
			const d = m?.data;
			if (!d || typeof d !== "object") return;
			const streamSym = cleanSymbol(
				String((d as Record<string, unknown>).symbol ?? ""),
			);
			if (streamSym && streamSym !== sym) return;
			emit(
				cb,
				"bybit",
				sym,
				{
					rate: num((d as Record<string, unknown>).fundingRate),
					nextFundingMs: null,
					intervalHours: 8,
				},
			)();
		},
	});
}

function subscribeBitget(symbol: string, cb: FundingCallback): FundingHandle {
	const sym = cleanSymbol(symbol);
	return openSocket("wss://ws.bitget.com/v2/ws/public", {
		onOpen: (ws) =>
			ws.send(
				JSON.stringify({
					op: "subscribe",
					args: [{ instType: "USDT-FUTURES", channel: "ticker", instId: sym }],
				}),
			),
		onMessage: (_ws, msg) => {
			// v2 ticker: { arg: { instId }, data: [{ fundingRate, ... }] }
			const arr = (msg as Record<string, unknown>)?.data;
			if (!Array.isArray(arr) || arr.length === 0) return;
			emit(
				cb,
				"bitget",
				sym,
				{
					rate: firstNum(arr, ["fundingRate"]),
					nextFundingMs: firstNumMs(arr, [
						"nextFundingTime",
						"fundingTime",
						"nextUpdate",
					]),
					intervalHours: 8,
				},
			)();
		},
	});
}

function subscribeOkx(symbol: string, cb: FundingCallback): FundingHandle {
	const base = cleanSymbol(symbol);
	const instId = base.includes("-")
		? base
		: base.endsWith("USDT")
			? `${base.slice(0, -4)}-USDT-SWAP`
			: base;
	return openSocket("wss://ws.okx.com:8443/ws/v5/public", {
		onOpen: (ws) =>
			ws.send(
				JSON.stringify({
					op: "subscribe",
					args: [{ channel: "tickers", instId }],
				}),
			),
		onMessage: (_ws, msg) => {
			// v5 tickers: { arg: { instId }, data: [{ fundingRate, fundingTime, ... }] }
			const arr = (msg as Record<string, unknown>)?.data;
			if (!Array.isArray(arr) || arr.length === 0) return;
			emit(
				cb,
				"okx",
				base,
				{
					rate: firstNum(arr, ["fundingRate"]),
					nextFundingMs: firstNumMs(arr, ["fundingTime", "nextFundingTime"]),
					intervalHours: 8,
				},
			)();
		},
	});
}

function subscribeWeex(symbol: string, cb: FundingCallback): FundingHandle {
	// WEEX WS ticker carries no funding fields — poll the backend funding
	// proxy instead (same pattern as the WEEX price adapter). Funding moves
	// rarely, 60s cadence is plenty.
	const sym = cleanSymbol(symbol);
	let timer: ReturnType<typeof setInterval> | null = null;
	let closed = false;

	const pollOnce = async () => {
		if (closed) return;
		try {
			const { apiClient } = await import("@/lib/apiClient");
			const data = await apiClient<{
				funding_rate?: number | null;
				next_funding_time_ms?: number | null;
				interval_hours?: number | null;
			}>(
				`/proxy/funding?${new URLSearchParams({
					exchange: "weex",
					symbol: sym,
				}).toString()}`,
			);
			const rate =
				typeof data?.funding_rate === "number" ? data.funding_rate : null;
			emit(
				cb,
				"weex",
				sym,
				{
					rate,
					nextFundingMs:
						typeof data?.next_funding_time_ms === "number"
							? data.next_funding_time_ms
							: null,
					intervalHours:
						typeof data?.interval_hours === "number" &&
						data.interval_hours > 0
							? data.interval_hours
							: 8,
				},
			)();
		} catch {
			/* backend unreachable — hook keeps showing "…" */
		}
	};

	void pollOnce();
	timer = setInterval(pollOnce, 60_000);

	return {
		close: () => {
			closed = true;
			if (timer) clearInterval(timer);
		},
	};
}

const FACTORIES: Record<
	string,
	(sym: string, cb: FundingCallback) => FundingHandle
> = {
	binance: subscribeBinance,
	bybit: subscribeBybit,
	bitget: subscribeBitget,
	okx: subscribeOkx,
	weex: subscribeWeex,
};

/** Subscribe to funding ticks for one exchange+symbol. No-op handle for unknown venues. */
export function subscribeFunding(
	exchange: string,
	symbol: string,
	cb: FundingCallback,
): FundingHandle {
	const factory = FACTORIES[exchange];
	if (!factory || !symbol) return { close: () => {} };
	return factory(symbol, cb);
}
