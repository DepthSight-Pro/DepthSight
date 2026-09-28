// pwa/hooks/useLiveMarks.ts
// Live mark-prices straight from exchanges (zero backend load).
// Throttled to ~4Hz renders; paused when tab hidden.
import { useEffect, useMemo, useRef, useState } from "react";
import {
	createLiveMarksManager,
	type LiveSymbol,
} from "../services/liveMarks";
import { markKey } from "../lib/livePnl";

// Re-exported from the shared lib so screens don't need this hook for math.
export { calcLivePnl } from "../lib/livePnl";

export interface LiveMark {
	price: number;
	ts: number;
	exchange: string;
	market?: string;
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
				.map((i) => markKey(i.symbol, i.exchange, i.market))
				.sort()
				.join(","),
		[items],
	);

	// Visible marks only — drops ticks for symbols no longer subscribed
	// without a setState-in-effect reset (react-hooks/set-state-in-effect).
	const keySet = useMemo(() => new Set(key.split(",").filter(Boolean)), [key]);
	const visibleMarks = useMemo(() => {
		const out: Record<string, LiveMark> = {};
		for (const [k, m] of Object.entries(marks)) {
			if (keySet.has(k)) out[k] = m;
		}
		return out;
	}, [marks, keySet]);

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
			// Venue-scoped key (WEEX additionally market-scoped): ticks from
			// different venues/markets for the same symbol must not
			// overwrite each other.
			cacheRef.current[markKey(tick.symbol, tick.exchange, tick.market)] = {
				price: tick.price,
				ts: tick.ts,
				exchange: tick.exchange,
				market: tick.market,
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
