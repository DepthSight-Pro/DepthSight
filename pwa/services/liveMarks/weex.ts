// pwa/services/liveMarks/weex.ts
// WEEX: public WS is not stably documented — same interface, REST fallback
// via backend ccxt proxy (GET /proxy/klines?limit=1). Swappable later.
import { api } from "../api";
import {
	type CreateMarksAdapter,
	type MarksCallback,
	cleanSymbol,
} from "./types";

export const createWeexAdapter: CreateMarksAdapter = (onTick: MarksCallback) => {
	let symbols: string[] = [];
	let closed = false;
	let timer: ReturnType<typeof setInterval> | null = null;

	const pollOnce = async () => {
		if (closed || symbols.length === 0) return;
		await Promise.all(
			symbols.map(async (s) => {
				try {
					const rows = await api.getProxyKlines(s, "1m", "weex", 1);
					const last = Array.isArray(rows) ? rows[rows.length - 1] : null;
					const price = last ? Number(last[4]) : NaN;
					if (Number.isFinite(price) && price > 0) {
						onTick({ symbol: s, price, ts: Date.now(), exchange: "weex" });
					}
				} catch {
					/* ignore single-symbol failure */
				}
			}),
		);
	};

	const restart = () => {
		if (timer) clearInterval(timer);
		timer = null;
		if (closed || symbols.length === 0) return;
		void pollOnce();
		timer = setInterval(pollOnce, 5000);
	};

	return {
		setSymbols: (next: string[]) => {
			symbols = [...new Set(next.map(cleanSymbol))].filter(Boolean);
			restart();
		},
		close: () => {
			closed = true;
			if (timer) clearInterval(timer);
		},
	};
};
