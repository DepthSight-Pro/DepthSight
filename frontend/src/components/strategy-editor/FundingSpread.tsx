// src/components/strategy-editor/FundingSpread.tsx
// Hedge funding-spread widget: live per-leg funding rates straight from
// public exchange websockets (zero backend load) + net spread + countdown.
// LONG legA pays rateA, SHORT legB earns rateB => net = rateB - rateA.

import { memo, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { ExchangeBadge } from "@/components/layout/AccountSelector";
import { useFundingRates, fundingKey } from "@/hooks/useFundingRates";
import { exchangeLabels } from "@/lib/exchanges";
import { cn } from "@/lib/utils";
import {
	DEFAULT_INTERVAL_HOURS,
	estimateFundingUsd8h,
	formatCountdown,
	formatFundingPct,
	formatSignedUsd,
	netFunding8h,
	nextGridSlotMs,
} from "@/services/liveMarks/fundingMath";

interface FundingSpreadProps {
	legAExchange: string | null;
	legBExchange: string | null;
	symbol: string;
	notionalUsd: number | null;
}

const rateTone = (rate: number | null) =>
	rate === null
		? "text-muted-foreground dark:text-white/30"
		: rate > 0
			? "text-emerald-600 dark:text-emerald-400"
			: rate < 0
				? "text-rose-500 dark:text-rose-400"
				: "text-foreground dark:text-white";

export const FundingSpread = memo(
	({ legAExchange, legBExchange, symbol, notionalUsd }: FundingSpreadProps) => {
		const { t } = useTranslation(["strategy-editor", "common"]);

		const requests = useMemo(
			() =>
				[
					{ exchange: legAExchange, symbol },
					{ exchange: legBExchange, symbol },
				].filter((r) => r.exchange && r.symbol),
			[legAExchange, legBExchange, symbol],
		);
		const states = useFundingRates(requests);

		// 1s countdown ticker (local only, no network).
		const [now, setNow] = useState(() => Date.now());
		useEffect(() => {
			const timer = setInterval(() => setNow(Date.now()), 1000);
			return () => clearInterval(timer);
		}, []);

		if (!legAExchange || !legBExchange || !symbol) return null;

		const stateA = states[fundingKey(legAExchange, symbol)];
		const stateB = states[fundingKey(legBExchange, symbol)];
		const rateA = stateA?.rate ?? null;
		const rateB = stateB?.rate ?? null;

		const intA = stateA?.intervalHours ?? DEFAULT_INTERVAL_HOURS;
		const intB = stateB?.intervalHours ?? DEFAULT_INTERVAL_HOURS;
		const net =
			rateA !== null && rateB !== null
				? netFunding8h(rateA, rateB, intA, intB)
				: null;

		// Countdown: prefer venue-provided settlement times, else the sooner
		// UTC-grid slot derived from each leg's interval.
		const targetMs = (() => {
			const known = [stateA?.nextFundingMs, stateB?.nextFundingMs].filter(
				(v): v is number => typeof v === "number" && v > now,
			);
			if (known.length > 0) return Math.min(...known);
			if (rateA !== null || rateB !== null) {
				return Math.min(
					nextGridSlotMs(intA, now),
					nextGridSlotMs(intB, now),
				);
			}
			return null;
		})();

		const labelFor = (exchange: string) =>
			exchangeLabels[exchange as keyof typeof exchangeLabels] ?? exchange;

		const renderLegRow = (
			exchange: string,
			rate: number | null,
			interval: number,
			side: string,
		) => (
			<div className="flex items-center gap-2">
				<ExchangeBadge exchange={exchange} size="xs" />
				<span className="text-[11px] text-foreground dark:text-white truncate">
					{labelFor(exchange)}
				</span>
				<span className="text-[10px] text-muted-foreground dark:text-white/40">
					{side}
				</span>
				<span className={cn("ml-auto font-mono text-[11px]", rateTone(rate))}>
					{rate === null ? "…" : `${formatFundingPct(rate)} / ${interval}h`}
				</span>
			</div>
		);

		return (
			<div className="rounded-lg border border-border dark:border-white/[0.06] bg-muted/20 dark:bg-white/[0.02] px-2.5 py-2 space-y-1.5">
				<div className="text-[11px] uppercase tracking-wider font-semibold text-muted-foreground dark:text-white/60">
					{t("configPanel.fundingTitle", "Funding spread")}
				</div>
				{renderLegRow(legAExchange, rateA, intA, "long")}
				{renderLegRow(legBExchange, rateB, intB, "short")}
				<div className="flex items-center gap-2 border-t border-border dark:border-white/[0.06] pt-1.5">
					<span className="text-[11px] font-medium text-foreground dark:text-white">
						{t("configPanel.fundingNet", "Net")}
					</span>
					<span className="text-[10px] text-muted-foreground dark:text-white/40">
						/ 8h
					</span>
					<span className={cn("ml-auto font-mono text-[11px] font-semibold", rateTone(net))}>
						{net === null ? (
							"…"
						) : (
							<>
								{formatFundingPct(net)}
								{notionalUsd !== null && Number.isFinite(notionalUsd) && (
									<span className="ml-1.5 font-normal opacity-80">
										({formatSignedUsd(estimateFundingUsd8h(net, notionalUsd))})
									</span>
								)}
							</>
						)}
					</span>
				</div>
				{targetMs !== null && (
					<div className="flex items-center gap-2">
						<span className="text-[10px] text-muted-foreground dark:text-white/40">
							{t("configPanel.fundingNextIn", "Next funding in")}
						</span>
						<span className="ml-auto font-mono text-[11px] text-foreground dark:text-white">
							{formatCountdown(targetMs - now)}
						</span>
					</div>
				)}
			</div>
		);
	},
);
