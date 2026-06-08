// src/components/strategies/BacktestModal.tsx

import { format } from "date-fns";
import { CalendarIcon, Loader2, Play } from "lucide-react";
import type React from "react";
import { useState } from "react";
import type { DateRange } from "react-day-picker";
import { useTranslation } from "react-i18next";
import { SymbolCombobox } from "@/components/strategy-editor/SymbolCombobox";
import { Button } from "@/components/ui/button";
import { Calendar } from "@/components/ui/calendar";
import {
	Dialog,
	DialogContent,
	DialogDescription,
	DialogFooter,
	DialogHeader,
	DialogTitle,
} from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import {
	Popover,
	PopoverContent,
	PopoverTrigger,
} from "@/components/ui/popover";
import type { CombinedStrategy } from "@/types/api";

interface BacktestModalProps {
	isOpen: boolean;
	onClose: () => void;
	onConfirm: (data: BacktestFormData) => void;
	strategyName?: string;
	isLoading?: boolean;
	strategy?: CombinedStrategy | null;
}

export interface BacktestFormData {
	symbol: string;
	startDate: string;
	endDate: string;
}

export const BacktestModal: React.FC<BacktestModalProps> = ({
	isOpen,
	onClose,
	onConfirm,
	strategyName = "Strategy",
	isLoading = false,
	strategy,
}) => {
	const { t } = useTranslation(["strategies", "common"]);

	// Get initial symbol from strategy
	const initialSymbol =
		strategy?.config_data?.symbol ||
		(strategy?.symbols && strategy.symbols.length > 0
			? strategy.symbols[0]
			: "") ||
		"BTCUSDT";

	const [symbol, setSymbol] = useState(initialSymbol);
	const [dateRange, setDateRange] = useState<DateRange | undefined>({
		from: new Date(new Date().setMonth(new Date().getMonth() - 1)),
		to: new Date(),
	});

	const [prevStrategyId, setPrevStrategyId] = useState<number | string | null>(
		null,
	);
	const strategyId = strategy?.id || null;

	if (isOpen && strategyId !== prevStrategyId) {
		setPrevStrategyId(strategyId);
		const sym =
			strategy?.config_data?.symbol ||
			(strategy?.symbols && strategy.symbols.length > 0
				? strategy.symbols[0]
				: "") ||
			"BTCUSDT";
		setSymbol(sym);
	}

	const handleSubmit = (e: React.FormEvent) => {
		e.preventDefault();

		if (!symbol || !dateRange?.from || !dateRange?.to) {
			return;
		}

		onConfirm({
			symbol,
			startDate: format(dateRange.from, "yyyy-MM-dd'T'HH:mm:ss'Z'"),
			endDate: format(dateRange.to, "yyyy-MM-dd'T'HH:mm:ss'Z'"),
		});
	};

	return (
		<Dialog open={isOpen} onOpenChange={onClose}>
			<DialogContent className="sm:max-w-[450px]">
				<DialogHeader>
					<DialogTitle>
						{t("backtestModal.title", {
							name: strategyName,
							defaultValue: `Backtest: ${strategyName}`,
						})}
					</DialogTitle>
					<DialogDescription>
						{t(
							"backtestModal.description",
							"Configure backtest parameters for this strategy",
						)}
					</DialogDescription>
				</DialogHeader>

				<form onSubmit={handleSubmit} className="space-y-6 py-4">
					{/* Symbol Selection */}
					<div className="space-y-2">
						<Label htmlFor="backtest-symbol">
							{t("backtestModal.symbolLabel", "Symbol")}
						</Label>
						<SymbolCombobox
							value={symbol}
							onChange={(value) => setSymbol(value.toUpperCase())}
							disabled={isLoading}
						/>
					</div>

					{/* Date Range */}
					<div className="space-y-2">
						<Label>{t("backtestModal.periodLabel", "Period")}</Label>
						<Popover>
							<PopoverTrigger asChild>
								<Button
									variant="outline"
									className="w-full justify-start font-normal"
									disabled={isLoading}
								>
									<CalendarIcon className="mr-2 h-4 w-4" />
									{dateRange?.from ? (
										dateRange.to ? (
											`${format(dateRange.from, "PP")} - ${format(dateRange.to, "PP")}`
										) : (
											format(dateRange.from, "PP")
										)
									) : (
										<span>
											{t(
												"backtestModal.selectPeriodPlaceholder",
												"Select period",
											)}
										</span>
									)}
								</Button>
							</PopoverTrigger>
							<PopoverContent className="w-auto p-0">
								<Calendar
									mode="range"
									selected={dateRange}
									onSelect={setDateRange}
									numberOfMonths={2}
								/>
							</PopoverContent>
						</Popover>
					</div>

					<DialogFooter>
						<Button
							type="button"
							variant="outline"
							onClick={onClose}
							disabled={isLoading}
						>
							{t("common:cancel")}
						</Button>
						<Button
							type="submit"
							disabled={
								isLoading || !symbol || !dateRange?.from || !dateRange?.to
							}
						>
							{isLoading ? (
								<Loader2 className="mr-2 h-4 w-4 animate-spin" />
							) : (
								<Play className="mr-2 h-4 w-4" />
							)}
							{t("backtestModal.runButton", "Run Backtest")}
						</Button>
					</DialogFooter>
				</form>
			</DialogContent>
		</Dialog>
	);
};
