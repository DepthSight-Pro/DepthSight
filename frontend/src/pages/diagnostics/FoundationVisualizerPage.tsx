// src/pages/diagnostics/FoundationVisualizerPage.tsx

import { TestTube2 } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import type {
	KlineData,
	LevelData,
	MarkerData,
	SubchartPoint,
	ZoneData,
} from "@/components/diagnostics/FoundationChart";
import { FoundationChart } from "@/components/diagnostics/FoundationChart";
import {
	type FoundationKey,
	FoundationParamsForm,
} from "@/components/diagnostics/FoundationParamsForm";
import { PageLayout } from "@/components/layout/PageLayout";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
	Select,
	SelectContent,
	SelectItem,
	SelectTrigger,
	SelectValue,
} from "@/components/ui/select";
import { useToast } from "@/components/ui/use-toast";
import { apiClient } from "@/lib/apiClient";

const formatDateForInput = (date: Date): string => {
	const year = date.getFullYear();
	const month = (date.getMonth() + 1).toString().padStart(2, "0");
	const day = date.getDate().toString().padStart(2, "0");
	const hours = date.getHours().toString().padStart(2, "0");
	const minutes = date.getMinutes().toString().padStart(2, "0");
	return `${year}-${month}-${day}T${hours}:${minutes}`;
};

export function FoundationVisualizerPage() {
	const { t } = useTranslation("diagnostics");
	const { toast } = useToast();

	const foundationOptions: {
		id: FoundationKey;
		label: string;
		color: string;
	}[] = [
		{
			id: "significant_level",
			label: t("foundations.significant_level"),
			color: "#2962ff",
		},
		{
			id: "local_level",
			label: t("foundations.local_level"),
			color: "#e91e63",
		},
		{
			id: "round_level",
			label: t("foundations.round_level"),
			color: "#ff9800",
		},
		{
			id: "classic_pattern",
			label: t("foundations.classic_pattern"),
			color: "#e91e63",
		},
		{
			id: "volume_confirmation",
			label: t("foundations.volume_confirmation"),
			color: "#ff9800",
		},
		{
			id: "price_consolidation",
			label: t("foundations.price_consolidation"),
			color: "rgba(128, 128, 128, 0.5)",
		},
		{
			id: "trend_direction",
			label: t("foundations.trend_direction"),
			color: "rgba(0, 255, 0, 0.5)",
		},
		{
			id: "open_interest",
			label: t("foundations.open_interest"),
			color: "#AB47BC",
		},
		{
			id: "correlation",
			label: t("foundations.correlation"),
			color: "#FFD700",
		},
		{
			id: "tape_acceleration",
			label: t("foundations.tape_acceleration"),
			color: "#2196F3",
		},
		{
			id: "volatility_filter",
			label: "Volatility (ATR/BBW)",
			color: "#FF5722",
		},
		{ id: "trend_filter", label: "Trend Strength (ADX)", color: "#4CAF50" },
		{ id: "natr_filter", label: "NATR Filter", color: "#9C27B0" },
		{ id: "rel_vol_filter", label: "Relative Volume", color: "#607D8B" },
		{
			id: "bollinger_bands_condition",
			label: "Bollinger Bands",
			color: "#3F51B5",
		},
		// New indicators
		{
			id: "ma_crossover",
			label: t("foundations.ma_crossover", "MA Crossover"),
			color: "#00BCD4",
		},
		{
			id: "rsi_condition",
			label: t("foundations.rsi_condition", "RSI Condition"),
			color: "#E91E63",
		},
		{
			id: "macd_condition",
			label: t("foundations.macd_condition", "MACD"),
			color: "#8BC34A",
		},
		{
			id: "stochastic_condition",
			label: t("foundations.stochastic_condition", "Stochastic"),
			color: "#FF5252",
		},
		{
			id: "volatility_squeeze",
			label: t("foundations.volatility_squeeze", "Volatility Squeeze"),
			color: "#FFD700",
		},
		{
			id: "level_touch_analyzer",
			label: t("foundations.level_touch_analyzer", "Level Touch"),
			color: "#2196F3",
		},
		{
			id: "price_action_analyzer",
			label: t("foundations.price_action_analyzer", "Price Action"),
			color: "#4CAF50",
		},
	];

	const [endDate, setEndDate] = useState(() => formatDateForInput(new Date()));
	const [symbol, setSymbol] = useState("BTCUSDT");
	const [timeframe, setTimeframe] = useState("1m");
	const [selectedFoundations, setSelectedFoundations] = useState<
		FoundationKey[]
	>(["significant_level", "local_level", "trend_direction"]);
	const [params, setParams] = useState("{}");
	interface FoundationVisualizerData {
		klines: KlineData[];
		visualizations: {
			levels: LevelData[];
			markers: MarkerData[];
			zones: ZoneData[];
			subcharts: Record<string, SubchartPoint[]>;
		};
	}

	const [data, setData] = useState<FoundationVisualizerData | null>(null);
	const [isLoading, setIsLoading] = useState(false);

	const handleVisualize = async () => {
		setIsLoading(true);
		setData(null);

		const queryParams = new URLSearchParams({
			symbol: symbol.toUpperCase().trim(),
			end_date: new Date(endDate).toISOString(),
			timeframe,
			foundations: selectedFoundations.join(","),
			params,
		});

		try {
			const result = await apiClient<FoundationVisualizerData>(
				`/diagnostics/preview-foundation?${queryParams}`,
			);
			if (result.klines && result.klines.length > 0) {
				setData(result);
			} else {
				toast({
					variant: "destructive",
					title: t("chartCard.noDataTitle"),
					description: t("chartCard.noDataForSymbol"),
				});
				setData(null);
			}
		} catch (err) {
			const error = err as Error;
			console.error("Failed to fetch foundation data:", error);
			toast({
				variant: "destructive",
				title: t("chartCard.errorTitle"),
				description: error.message || t("chartCard.error"),
			});
			setData(null);
		} finally {
			setIsLoading(false);
		}
	};

	return (
		<PageLayout title={t("pageTitle")} icon={TestTube2}>
			<div className="flex h-full gap-4 overflow-hidden">
				{/* Left panel - parameters */}
				<div className="w-full max-w-xs flex-shrink-0 overflow-hidden">
					<Card className="h-full flex flex-col max-h-[calc(100vh-120px)]">
						<CardHeader className="flex-shrink-0">
							<CardTitle>{t("parametersCard.title")}</CardTitle>
						</CardHeader>
						<CardContent className="flex-grow min-h-0 overflow-hidden">
							<ScrollArea className="h-full pr-4">
								<div className="space-y-4">
									<div>
										<Label htmlFor="symbol">{t("form.symbol")}</Label>
										<Input
											id="symbol"
											value={symbol}
											onChange={(e) => setSymbol(e.target.value)}
										/>
									</div>
									<div>
										<Label htmlFor="end-date">{t("form.endDate")}</Label>
										<Input
											id="end-date"
											type="datetime-local"
											value={endDate}
											onChange={(e) => setEndDate(e.target.value)}
										/>
										<p className="text-xs text-muted-foreground mt-1">
											{t("form.endDateDesc")}
										</p>
									</div>
									<div>
										<Label htmlFor="timeframe">{t("form.timeframe")}</Label>
										<Select value={timeframe} onValueChange={setTimeframe}>
											<SelectTrigger>
												<SelectValue />
											</SelectTrigger>
											<SelectContent>
												<SelectItem value="1m">1m</SelectItem>
												<SelectItem value="5m">5m</SelectItem>
												<SelectItem value="1h">1h</SelectItem>
												<SelectItem value="4h">4h</SelectItem>
												<SelectItem value="1d">1d</SelectItem>
											</SelectContent>
										</Select>
									</div>
									<div>
										<Label>{t("form.foundationTypes")}</Label>
										<div className="space-y-2 mt-2 p-2 border rounded-md max-h-[250px] overflow-y-auto">
											{foundationOptions.map((option) => (
												<div
													key={option.id}
													className="flex items-center space-x-2"
												>
													<Checkbox
														id={option.id}
														checked={selectedFoundations.includes(option.id)}
														onCheckedChange={(checked) =>
															setSelectedFoundations((prev) =>
																checked
																	? [...prev, option.id]
																	: prev.filter((id) => id !== option.id),
															)
														}
													/>
													<div
														style={{
															width: "12px",
															height: "12px",
															borderRadius: "50%",
															backgroundColor: option.color,
															marginRight: "8px",
														}}
													></div>
													<Label
														htmlFor={option.id}
														className="font-normal cursor-pointer text-sm"
													>
														{option.label}
													</Label>
												</div>
											))}
										</div>
									</div>
									<FoundationParamsForm
										foundationTypes={selectedFoundations}
										onParamsChange={setParams}
									/>
								</div>
							</ScrollArea>
						</CardContent>
						<div className="p-6 pt-0 flex-shrink-0">
							<Button
								onClick={handleVisualize}
								disabled={isLoading || !symbol || !endDate}
								className="w-full"
							>
								{isLoading
									? t("form.loadingButton")
									: t("form.visualizeButton")}
							</Button>
						</div>
					</Card>
				</div>

				{/* Right panel with chart - fixed height */}
				<div className="flex-grow min-w-0 overflow-hidden">
					<Card className="h-full flex flex-col max-h-[calc(100vh-120px)]">
						<CardHeader className="flex-shrink-0">
							<CardTitle>{t("chartCard.title")}</CardTitle>
						</CardHeader>
						<CardContent className="flex-grow min-h-0 overflow-hidden">
							{isLoading ? (
								<div className="h-full flex items-center justify-center text-muted-foreground">
									<p>{t("chartCard.loading")}</p>
								</div>
							) : data ? (
								<div className="h-full w-full">
									<FoundationChart
										klines={data.klines}
										visualizations={data.visualizations}
									/>
								</div>
							) : (
								<div className="h-full flex items-center justify-center text-muted-foreground">
									<p>{t("chartCard.noData")}</p>
								</div>
							)}
						</CardContent>
					</Card>
				</div>
			</div>
		</PageLayout>
	);
}
