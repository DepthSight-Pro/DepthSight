// frontend/src/hooks/useLiveMarks.ts
// Live mark-prices straight from exchanges (zero backend load).
// Throttled to ~4Hz renders; paused when tab hidden.
import { useEffect, useMemo, useRef, useState } from "react";
import {
	createLiveMarksManager,
	type LiveSymbol,
} from "@/services/liveMarks";

// Re-exported from the shared lib so pages don't need this hook for math.
export { calcLivePnl } from "@/lib/livePnl";
import { markKey } from "@/lib/livePnl";

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

	useEffect(() => {
		cacheRef.current = {};
		setMarks({});
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
			// Venue-scoped key: ticks from different exchanges for the same
			// symbol must not overwrite each other.
			cacheRef.current[markKey(tick.symbol, tick.exchange)] = {
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

	return { marks, liveCount: Object.keys(marks).length };
}
