// frontend/src/hooks/useFundingRates.ts
// Client-side funding ticks (public exchange websockets, zero backend load).
// Sockets live only while subscribed; closed on unmount / set change.
import { useEffect, useMemo, useState } from "react";
import {
	subscribeFunding,
	type FundingTick,
} from "@/services/liveMarks/funding";

export interface FundingRequest {
	exchange?: string | null;
	symbol: string;
}

export interface FundingState {
	rate: number | null;
	nextFundingMs: number | null;
	intervalHours: number | null;
	updatedTs: number;
}

export const fundingKey = (exchange: string, symbol: string) =>
	`${exchange.toLowerCase()}|${symbol.toUpperCase()}`;

export function useFundingRates(
	requests: FundingRequest[],
): Record<string, FundingState> {
	const [states, setStates] = useState<Record<string, FundingState>>({});

	const key = useMemo(
		() =>
			[...requests]
				.map((r) => `${r.symbol}|${r.exchange ?? ""}`)
				.sort()
				.join(","),
		// eslint-disable-next-line react-hooks/exhaustive-deps
		[JSON.stringify(requests)],
	);

	useEffect(() => {
		setStates({});
		const active = requests.filter((r) => r.exchange && r.symbol);
		if (active.length === 0) return;

		const onTick = (tick: FundingTick) => {
			const k = fundingKey(tick.exchange, tick.symbol);
			setStates((prev) => ({
				...prev,
				[k]: {
					rate: tick.rate,
					nextFundingMs: tick.nextFundingMs ?? null,
					intervalHours: tick.intervalHours ?? null,
					updatedTs: tick.ts,
				},
			}));
		};

		const handles = active.map((r) =>
			subscribeFunding(String(r.exchange), r.symbol, onTick),
		);
		return () => {
			for (const h of handles) {
				try {
					h.close();
				} catch {
					/* noop */
				}
			}
		};
		// eslint-disable-next-line react-hooks/exhaustive-deps
	}, [key]);

	return states;
}
