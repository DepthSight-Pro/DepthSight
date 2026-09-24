// src/components/positions/PositionSparkline.tsx
//
// Real-klines sparkline for a position: closes from the position's native
// exchange via GET /proxy/klines (Binance fallback inside). Falls back to a
// flat line at `fallbackPrice` while loading or on error — never fake drift.

import { useMemo } from "react";
import { Sparkline } from "@/components/ui/quant-ui";
import { useExchangeKlines } from "@/lib/api";

interface PositionSparklineProps {
	symbol: string;
	exchange?: string | null;
	fallbackPrice: number;
	width?: number;
	height?: number;
	baseline?: boolean;
}

export function PositionSparkline({
	symbol,
	exchange,
	fallbackPrice,
	width = 80,
	height = 22,
	baseline = false,
}: PositionSparklineProps) {
	const { data: klines } = useExchangeKlines(
		{ symbol, interval: "15m", exchange, limit: 40 },
		{ enabled: !!symbol },
	);

	const data = useMemo(() => {
		if (klines && klines.length >= 2) {
			return klines.map((k) => k.close);
		}
		const flat = Number.isFinite(fallbackPrice) ? fallbackPrice : 0;
		return [flat, flat];
	}, [klines, fallbackPrice]);

	return (
		<Sparkline data={data} width={width} height={height} baseline={baseline} />
	);
}
