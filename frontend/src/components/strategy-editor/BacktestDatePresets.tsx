// src/components/strategy-editor/BacktestDatePresets.tsx

import {
	endOfMonth,
	endOfYear,
	format,
	isSameDay,
	parseISO,
	startOfMonth,
	startOfYear,
	subMonths,
	subYears,
} from "date-fns";
import { CalendarDays, Database, History, Loader2 } from "lucide-react";
import React, { useMemo } from "react";
import type { DateRange } from "react-day-picker";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import {
	Tooltip,
	TooltipContent,
	TooltipProvider,
	TooltipTrigger,
} from "@/components/ui/tooltip";
import { useHistoricalRanges } from "@/lib/api";
import { cn } from "@/lib/utils";

interface BacktestDatePresetsProps {
	symbol: string;
	dateRange: DateRange | undefined;
	onSelectDateRange: (range: DateRange | undefined) => void;
	className?: string;
}

interface PresetDefinition {
	id: string;
	labelKey: string;
	colSpanClass?: string;
	getRange: () => { from: Date; to: Date };
}

export const BacktestDatePresets: React.FC<BacktestDatePresetsProps> = ({
	symbol,
	dateRange,
	onSelectDateRange,
	className,
}) => {
	const { t } = useTranslation("strategy-editor");
	const cleanSymbol = (symbol || "").trim().toUpperCase().replace("/", "").replace(":", "");

	const { data: storageList, isLoading } = useHistoricalRanges(cleanSymbol);

	const storageItem = useMemo(() => {
		if (!storageList || storageList.length === 0) return null;
		return (
			storageList.find(
				(item) =>
					item.symbol.replace("/", "").replace(":", "").toUpperCase() === cleanSymbol,
			) || storageList[0]
		);
	}, [storageList, cleanSymbol]);

	const klineInfo = storageItem?.klines_1m;
	const storageStartDate = klineInfo?.start_date;
	const storageEndDate = klineInfo?.end_date;

	const presets = useMemo<PresetDefinition[]>(() => {
		const now = new Date();
		let parsedStorageEnd = storageEndDate ? parseISO(storageEndDate) : null;
		if (parsedStorageEnd && isNaN(parsedStorageEnd.getTime())) {
			parsedStorageEnd = null;
		}

		let parsedStorageStart = storageStartDate ? parseISO(storageStartDate) : null;
		if (parsedStorageStart && isNaN(parsedStorageStart.getTime())) {
			parsedStorageStart = null;
		}

		// Anchor the "latest" available date to storage end if present and not in future, or now
		const anchorEnd = parsedStorageEnd
			? parsedStorageEnd > now
				? now
				: parsedStorageEnd
			: now;

		return [
			{
				id: "all",
				labelKey: "configPanel.presets.all",
				colSpanClass: "col-span-2",
				getRange: () => {
					const from = parsedStorageStart || startOfYear(subYears(now, 1));
					const to = parsedStorageEnd || anchorEnd;
					return { from, to };
				},
			},
			{
				id: "thisYear",
				labelKey: "configPanel.presets.thisYear",
				colSpanClass: "col-span-1",
				getRange: () => {
					let from = startOfYear(anchorEnd);
					if (parsedStorageStart && parsedStorageStart > from) {
						from = parsedStorageStart;
					}
					return { from, to: anchorEnd };
				},
			},
			{
				id: "lastYear",
				labelKey: "configPanel.presets.lastYear",
				colSpanClass: "col-span-1",
				getRange: () => {
					const prevYear = subYears(anchorEnd, 1);
					let from = startOfYear(prevYear);
					let to = endOfYear(prevYear);

					if (parsedStorageStart && parsedStorageStart > from) {
						from = parsedStorageStart;
					}
					if (parsedStorageEnd && parsedStorageEnd < to) {
						to = parsedStorageEnd;
					}
					return { from, to };
				},
			},
			{
				id: "sixMonths",
				labelKey: "configPanel.presets.sixMonths",
				colSpanClass: "col-span-1",
				getRange: () => {
					let from = subMonths(anchorEnd, 6);
					if (parsedStorageStart && parsedStorageStart > from) {
						from = parsedStorageStart;
					}
					return { from, to: anchorEnd };
				},
			},
			{
				id: "threeMonths",
				labelKey: "configPanel.presets.threeMonths",
				colSpanClass: "col-span-1",
				getRange: () => {
					let from = subMonths(anchorEnd, 3);
					if (parsedStorageStart && parsedStorageStart > from) {
						from = parsedStorageStart;
					}
					return { from, to: anchorEnd };
				},
			},
			{
				id: "oneMonth",
				labelKey: "configPanel.presets.oneMonth",
				colSpanClass: "col-span-1",
				getRange: () => {
					let from = subMonths(anchorEnd, 1);
					if (parsedStorageStart && parsedStorageStart > from) {
						from = parsedStorageStart;
					}
					return { from, to: anchorEnd };
				},
			},
			{
				id: "lastMonth",
				labelKey: "configPanel.presets.lastMonth",
				colSpanClass: "col-span-1",
				getRange: () => {
					const prevMonth = subMonths(anchorEnd, 1);
					let from = startOfMonth(prevMonth);
					let to = endOfMonth(prevMonth);

					if (parsedStorageStart && parsedStorageStart > from) {
						from = parsedStorageStart;
					}
					if (parsedStorageEnd && parsedStorageEnd < to) {
						to = parsedStorageEnd;
					}
					return { from, to };
				},
			},
		];
	}, [storageStartDate, storageEndDate]);

	return (
		<TooltipProvider delayDuration={200}>
			<div className={cn("space-y-2", className)}>
				{/* Header: Available data indicator & quick presets title */}
				<div className="flex items-center justify-between gap-1 text-xs">
					<div className="flex items-center gap-1.5 font-medium text-muted-foreground">
						<CalendarDays className="w-3.5 h-3.5 text-primary shrink-0" />
						<span className="text-[11px] uppercase tracking-wider font-semibold">
							{t("configPanel.quickPresetsLabel")}
						</span>
					</div>

					{isLoading ? (
						<div className="flex items-center gap-1 text-[10px] text-muted-foreground">
							<Loader2 className="w-3 h-3 animate-spin" />
						</div>
					) : storageStartDate && storageEndDate ? (
						<Tooltip>
							<TooltipTrigger asChild>
								<div className="flex items-center gap-1.5 text-[10px] bg-secondary/80 hover:bg-secondary text-secondary-foreground px-2 py-0.5 rounded-full border border-border/60 transition-colors cursor-help">
									<Database className="w-2.5 h-2.5 text-primary shrink-0" />
									<span className="font-mono font-medium">
										{storageStartDate} — {storageEndDate}
									</span>
								</div>
							</TooltipTrigger>
							<TooltipContent side="top" className="text-xs max-w-xs p-2.5 space-y-1">
								<p className="font-semibold text-primary">
									{t("configPanel.availableHistoryLabel")}: {cleanSymbol}
								</p>
								<p className="font-mono text-[11px] text-muted-foreground">
									{storageStartDate} 00:00 → {storageEndDate} 23:59
								</p>
								{storageItem?.timeframes && storageItem.timeframes.length > 0 && (
									<p className="text-[10px] text-muted-foreground">
										TF: {storageItem.timeframes.join(", ")}
									</p>
								)}
								{(storageItem?.has_depth || storageItem?.has_oi) && (
									<div className="pt-1 flex items-center gap-2 text-[10px] text-emerald-400">
										{storageItem.has_depth && <span>✓ bookDepth</span>}
										{storageItem.has_oi && <span>✓ OI</span>}
									</div>
								)}
							</TooltipContent>
						</Tooltip>
					) : (
						<div className="flex items-center gap-1 text-[10px] text-muted-foreground/70">
							<History className="w-2.5 h-2.5" />
							<span>{t("configPanel.noHistoryLoaded")}</span>
						</div>
					)}
				</div>

				{/* 4-Column Compact Presets Grid */}
				<div className="grid grid-cols-4 gap-1.5">
					{presets.map((preset) => {
						const range = preset.getRange();
						const isActive =
							dateRange?.from &&
							dateRange?.to &&
							isSameDay(dateRange.from, range.from) &&
							isSameDay(dateRange.to, range.to);

						const formattedFrom = format(range.from, "yyyy-MM-dd");
						const formattedTo = format(range.to, "yyyy-MM-dd");

						return (
							<Tooltip key={preset.id}>
								<TooltipTrigger asChild>
									<Button
										type="button"
										variant={isActive ? "default" : "outline"}
										size="sm"
										className={cn(
											"h-7 px-1.5 text-[11px] font-medium leading-none transition-all truncate",
											preset.colSpanClass,
											isActive
												? "bg-primary text-primary-foreground shadow-xs font-semibold ring-1 ring-primary/60"
												: "hover:bg-accent/60 hover:text-accent-foreground text-muted-foreground border-border/70",
										)}
										onClick={() => {
											onSelectDateRange({
												from: range.from,
												to: range.to,
											});
										}}
									>
										{t(preset.labelKey)}
									</Button>
								</TooltipTrigger>
								<TooltipContent side="bottom" className="text-xs">
									<p className="font-medium text-foreground">
										{t(preset.labelKey)}
									</p>
									<p className="font-mono text-[10px] text-muted-foreground">
										{formattedFrom} — {formattedTo}
									</p>
								</TooltipContent>
							</Tooltip>
						);
					})}
				</div>
			</div>
		</TooltipProvider>
	);
};
