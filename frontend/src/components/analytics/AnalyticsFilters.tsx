// src/components/analytics/AnalyticsFilters.tsx

import { format, subDays } from "date-fns";
import { CalendarIcon, FilterXIcon, SearchIcon } from "lucide-react";
import type React from "react";
import { useState } from "react";
import type { DateRange } from "react-day-picker";
import { useTranslation } from "react-i18next";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Calendar } from "@/components/ui/calendar";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
	Popover,
	PopoverContent,
	PopoverTrigger,
} from "@/components/ui/popover";
import {
	Select,
	SelectContent,
	SelectItem,
	SelectTrigger,
	SelectValue,
} from "@/components/ui/select";
import type { TradeHistoryParams } from "@/lib/api";
import type { StrategyConfig } from "@/types/api";

interface AnalyticsFiltersProps {
	onApply: (filters: TradeHistoryParams) => void;
	onClear: () => void;
	strategies?: StrategyConfig[];
	isInteractiveFiltered?: boolean;
	onResetInteractive?: () => void;
}

export const AnalyticsFilters: React.FC<AnalyticsFiltersProps> = ({
	onApply,
	onClear,
	strategies = [],
	isInteractiveFiltered,
	onResetInteractive,
}) => {
	const { t } = useTranslation("analytics");
	const [strategyId, setStrategyId] = useState<string | undefined>(undefined);
	const [symbol, setSymbol] = useState<string>("");
	const [dateRange, setDateRange] = useState<DateRange | undefined>({
		from: subDays(new Date(), 30), // 30 days by default
		to: new Date(),
	});

	const handleApply = () => {
		const filters: TradeHistoryParams = {
			strategyConfigId:
				strategyId === "all" || !strategyId ? undefined : strategyId,
			symbol: symbol.trim() === "" ? undefined : symbol.trim().toUpperCase(),
			startDate: dateRange?.from
				? format(dateRange.from, "yyyy-MM-dd")
				: undefined,
			endDate: dateRange?.to
				? format(dateRange.to, "yyyy-MM-dd")
				: dateRange?.from
					? format(dateRange.from, "yyyy-MM-dd")
					: undefined,
			limit: 500,
		};
		onApply(filters);
	};

	const handleClear = () => {
		setStrategyId(undefined);
		setSymbol("");
		setDateRange({ from: subDays(new Date(), 30), to: new Date() });
		onClear();
	};

	return (
		<div className="flex flex-wrap items-end gap-3 p-4 bg-card/90 dark:bg-[#07080b]/90 border border-border dark:border-white/10 rounded-2xl backdrop-blur-2xl shadow-xl">
			{/* Strategy Select */}
			<div className="flex-1 min-w-[150px] max-w-[200px]">
				<Label
					htmlFor="strategy-select"
					className="text-[11px] font-mono font-medium text-muted-foreground dark:text-white/50 mb-1.5 block uppercase tracking-wider"
				>
					{t("filterStrategyLabel")}
				</Label>
				<Select
					value={strategyId || "all"}
					onValueChange={(value) =>
						setStrategyId(value === "all" ? undefined : value)
					}
				>
					<SelectTrigger id="strategy-select" className="h-9 bg-card dark:bg-white/[0.03] border-border dark:border-white/10 text-xs text-foreground dark:text-white hover:bg-muted/50 dark:hover:bg-white/[0.06] hover:border-border dark:hover:border-white/20 transition-all rounded-xl">
						<SelectValue placeholder={t("filterStrategyAll")} />
					</SelectTrigger>
					<SelectContent className="bg-popover border-border dark:border-white/10 text-popover-foreground shadow-2xl">
						<SelectItem value="all">{t("filterStrategyAll")}</SelectItem>
						{strategies.map((s) => (
							<SelectItem key={s.id} value={s.id}>
								{s.name} ({s.config_data?.strategy_name || "Strategy"},{" "}
								{s.id.substring(0, 6)}...)
							</SelectItem>
						))}
					</SelectContent>
				</Select>
			</div>

			{/* Symbol Input */}
			<div className="flex-1 min-w-[120px] max-w-[150px]">
				<Label
					htmlFor="symbol-input"
					className="text-[11px] font-mono font-medium text-muted-foreground dark:text-white/50 mb-1.5 block uppercase tracking-wider"
				>
					{t("filterSymbolLabel")}
				</Label>
				<Input
					id="symbol-input"
					placeholder="BTCUSDT"
					value={symbol}
					onChange={(e) => setSymbol(e.target.value)}
					className="h-9 bg-card dark:bg-white/[0.03] border-border dark:border-white/10 text-xs text-foreground dark:text-white placeholder:text-muted-foreground/50 hover:bg-muted/50 dark:hover:bg-white/[0.06] hover:border-border dark:hover:border-white/20 transition-all rounded-xl uppercase font-mono"
				/>
			</div>

			{/* Date Range */}
			<div className="flex-1 min-w-[200px] max-w-[280px]">
				<Label
					htmlFor="date-range-picker"
					className="text-[11px] font-mono font-medium text-muted-foreground dark:text-white/50 mb-1.5 block uppercase tracking-wider"
				>
					{t("filterDateRangeLabel")}
				</Label>
				<Popover>
					<PopoverTrigger asChild>
						<Button
							id="date-range-picker"
							variant={"outline"}
							className="w-full justify-start text-left font-mono font-normal h-9 text-xs bg-card dark:bg-white/[0.03] border-border dark:border-white/10 text-foreground dark:text-white hover:bg-muted/50 dark:hover:bg-white/[0.06] hover:border-border dark:hover:border-white/20 transition-all rounded-xl"
						>
							<CalendarIcon className="mr-2 h-3.5 w-3.5 text-cyan" />
							{dateRange?.from ? (
								dateRange.to ? (
									<>
										{format(dateRange.from, "dd.MM.yy")} -{" "}
										{format(dateRange.to, "dd.MM.yy")}
									</>
								) : (
									format(dateRange.from, "dd.MM.yy")
								)
							) : (
								<span className="text-muted-foreground dark:text-white/40">{t("filterDateRangePlaceholder")}</span>
							)}
						</Button>
					</PopoverTrigger>
					<PopoverContent className="w-auto p-0 bg-popover border-border dark:border-white/10 text-popover-foreground shadow-2xl rounded-2xl overflow-hidden" align="start">
						<Calendar
							initialFocus
							mode="range"
							defaultMonth={dateRange?.from}
							selected={dateRange}
							onSelect={setDateRange}
							numberOfMonths={2}
							className="text-popover-foreground"
						/>
					</PopoverContent>
				</Popover>
			</div>

			{/* Buttons */}
			<div className="flex gap-2">
				<Button
					variant="ghost"
					size="sm"
					onClick={handleClear}
					className="h-9 px-3 rounded-xl text-muted-foreground dark:text-white/50 hover:text-foreground dark:hover:text-white hover:bg-muted/50 dark:hover:bg-white/5 transition-all"
					title="Clear filters"
				>
					<FilterXIcon className="h-4 w-4" />
				</Button>
				<Button
					size="sm"
					onClick={handleApply}
					className="h-9 px-4 rounded-xl bg-cyan hover:bg-cyan/90 text-black font-semibold text-xs shadow-[0_0_16px_-3px_rgba(0,212,255,0.6)] transition-all flex items-center gap-1.5"
				>
					<SearchIcon className="h-3.5 w-3.5" />
					{t("applyButton")}
				</Button>
			</div>

			{/* Interactive Filters Status */}
			{isInteractiveFiltered && onResetInteractive && (
				<div className="flex items-center gap-2 ml-auto">
					<Badge
						variant="outline"
						className="bg-amber-500/10 text-amber-400 border-amber-500/30 animate-pulse h-9 px-3 font-mono text-xs rounded-xl"
					>
						{t("filterActive", "Filter Active")}
					</Badge>
					<Button
						variant="outline"
						size="sm"
						onClick={onResetInteractive}
						className="h-9 px-3 rounded-xl border-rose-500/30 text-rose-400 hover:bg-rose-500/10 hover:text-rose-300 font-mono text-xs transition-all flex items-center gap-1.5"
					>
						<FilterXIcon className="w-3.5 h-3.5" />
						{t("resetFilters", "Reset Filters")}
					</Button>
				</div>
			)}
		</div>
	);
};
