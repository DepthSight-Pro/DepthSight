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
		<div className="flex flex-wrap items-end gap-3 p-4 bg-card border border-border rounded-xl">
			{/* Strategy Select */}
			<div className="flex-1 min-w-[150px] max-w-[200px]">
				<Label
					htmlFor="strategy-select"
					className="text-xs text-muted-foreground mb-1 block"
				>
					{t("filterStrategyLabel")}
				</Label>
				<Select
					value={strategyId || "all"}
					onValueChange={(value) =>
						setStrategyId(value === "all" ? undefined : value)
					}
				>
					<SelectTrigger id="strategy-select" className="h-9">
						<SelectValue placeholder={t("filterStrategyAll")} />
					</SelectTrigger>
					<SelectContent>
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
					className="text-xs text-muted-foreground mb-1 block"
				>
					{t("filterSymbolLabel")}
				</Label>
				<Input
					id="symbol-input"
					placeholder="BTCUSDT"
					value={symbol}
					onChange={(e) => setSymbol(e.target.value)}
					className="h-9"
				/>
			</div>

			{/* Date Range */}
			<div className="flex-1 min-w-[200px] max-w-[280px]">
				<Label
					htmlFor="date-range-picker"
					className="text-xs text-muted-foreground mb-1 block"
				>
					{t("filterDateRangeLabel")}
				</Label>
				<Popover>
					<PopoverTrigger asChild>
						<Button
							id="date-range-picker"
							variant={"outline"}
							className="w-full justify-start text-left font-normal h-9 text-sm"
						>
							<CalendarIcon className="mr-2 h-3.5 w-3.5" />
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
								<span>{t("filterDateRangePlaceholder")}</span>
							)}
						</Button>
					</PopoverTrigger>
					<PopoverContent className="w-auto p-0" align="start">
						<Calendar
							initialFocus
							mode="range"
							defaultMonth={dateRange?.from}
							selected={dateRange}
							onSelect={setDateRange}
							numberOfMonths={2}
						/>
					</PopoverContent>
				</Popover>
			</div>

			{/* Buttons - moved back next to inputs */}
			<div className="flex gap-2">
				<Button
					variant="ghost"
					size="sm"
					onClick={handleClear}
					className="h-9 px-3"
				>
					<FilterXIcon className="h-4 w-4" />
				</Button>
				<Button size="sm" onClick={handleApply} className="h-9 px-4">
					<SearchIcon className="h-4 w-4 mr-1.5" />
					{t("applyButton")}
				</Button>
			</div>

			{/* Interactive Filters Status - moved to right */}
			{isInteractiveFiltered && onResetInteractive && (
				<div className="flex items-center gap-2 ml-auto">
					<Badge
						variant="outline"
						className="bg-amber-500/10 text-amber-500 border-amber-500/30 animate-pulse h-9 px-3"
					>
						{t("filterActive", "Filter Active")}
					</Badge>
					<Button
						variant="outline"
						size="sm"
						onClick={onResetInteractive}
						className="h-9 px-3 border-destructive/30 text-destructive hover:bg-destructive/10"
					>
						<FilterXIcon className="w-4 h-4 mr-2" />
						{t("resetFilters", "Reset Filters")}
					</Button>
				</div>
			)}
		</div>
	);
};
