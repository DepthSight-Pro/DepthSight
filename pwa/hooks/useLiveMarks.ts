// pwa/hooks/useLiveMarks.ts
// Live mark-prices straight from exchanges (zero backend load).
// Throttled to ~4Hz renders; paused when tab hidden.
import { useEffect, useMemo, useRef, useState } from "react";
import {
	createLiveMarksManager,
	type LiveSymbol,
} from "../services/liveMarks";

// Re-exported from the shared lib so screens don't need this hook for math.
export { calcLivePnl } from "../lib/livePnl";

export interface LiveMark {
	price: number;
	ts: number;
	exchange: string;
}

const THROTTLE_MS = 250;

export function useLiveMarks(items: LiveSymbol[]): {
	marks: Record<string, LiveMark>;
	liveCount: number;
} {
	const [marks, setMarks] = useState<Record<string, LiveMark>>({});
	const cacheRef = useRef<Record<string, LiveMark>>({});
	const lastEmitRef = useRef(0);
	const flushTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

	const key = useMemo(
		() =>
			[...items]
				.map((i) => `${i.symbol}|${i.exchange ?? ""}`)
				.sort()
				.join(","),
		[items],
	);

	// Visible marks only — drops ticks for symbols no longer subscribed
	// without a setState-in-effect reset (react-hooks/set-state-in-effect).
	const symbolSet = useMemo(
		() => new Set(key.split(",").map((s) => s.split("|")[0])),
		[key],
	);
	const visibleMarks = useMemo(() => {
		const out: Record<string, LiveMark> = {};
		for (const [sym, m] of Object.entries(marks)) {
			if (symbolSet.has(sym)) out[sym] = m;
		}
		return out;
	}, [marks, symbolSet]);

	useEffect(() => {
		if (items.length === 0) return;

		let disposed = false;
		const scheduleFlush = () => {
			if (disposed) return;
			const now = Date.now();
			const wait = THROTTLE_MS - (now - lastEmitRef.current);
			if (wait <= 0) {
				lastEmitRef.current = now;
				setMarks({ ...cacheRef.current });
			} else if (!flushTimerRef.current) {
				flushTimerRef.current = setTimeout(() => {
					flushTimerRef.current = null;
					if (disposed) return;
					lastEmitRef.current = Date.now();
					setMarks({ ...cacheRef.current });
				}, wait);
			}
		};

		const manager = createLiveMarksManager((tick) => {
			if (disposed || document.visibilityState === "hidden") return;
			cacheRef.current[tick.symbol] = {
				price: tick.price,
				ts: tick.ts,
				exchange: tick.exchange,
			};
			scheduleFlush();
		});
		manager.setSymbols(items);

		const onVis = () => {
			if (document.visibilityState === "visible") {
				lastEmitRef.current = 0;
				setMarks({ ...cacheRef.current });
			}
		};
		document.addEventListener("visibilitychange", onVis);

		return () => {
			disposed = true;
			document.removeEventListener("visibilitychange", onVis);
			if (flushTimerRef.current) clearTimeout(flushTimerRef.current);
			flushTimerRef.current = null;
			manager.close();
		};
		// eslint-disable-next-line react-hooks/exhaustive-deps
	}, [key]);

	return { marks: visibleMarks, liveCount: Object.keys(visibleMarks).length };
}
