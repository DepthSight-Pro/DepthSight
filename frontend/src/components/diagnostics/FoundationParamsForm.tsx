// src/components/diagnostics/FoundationParamsForm.tsx

import { useEffect, useState } from "react";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
	Select,
	SelectContent,
	SelectItem,
	SelectTrigger,
	SelectValue,
} from "@/components/ui/select";

interface FoundationParamsState {
	significant_level: { kline_1h: number; kline_4h: number; kline_1d: number };
	local_level: { timeframe: string; lookback_period: number };
	round_level: Record<string, never>;
	classic_pattern: {
		pattern_name: string;
		side?: "any" | "bullish" | "bearish";
	};
	volume_confirmation: Record<string, never>;
	price_consolidation: {
		lookback_period: number;
		max_range_atr: number;
		timeframe?: string;
	};
	trend_direction: {
		sma_fast_period: number;
		sma_slow_period: number;
		rsi_period: number;
		rsi_lower_bound: number;
		rsi_upper_bound: number;
	};
	open_interest: {
		lookback: number;
		analyze: string;
		operator: string;
		value: number;
	};
	correlation: { lookback: number; operator: string; value: number };
	tape_acceleration: {
		time_window_sec: number;
		analysis_type: string;
		multiplier: number;
	};
	volatility_filter: {
		indicator: "ATR" | "BBW";
		operator: "gt" | "lt";
		value: number;
	};
	trend_filter: { indicator: "ADX"; threshold: number };
	natr_filter: { natr_threshold: number };
	rel_vol_filter: { rel_vol_threshold: number };
	bollinger_bands_condition: {
		source: "close" | "high" | "low";
		location: "above_upper" | "below_lower";
		shift: number;
	};
	ma_crossover: {
		fast_period: number;
		slow_period: number;
		ma_type: "SMA" | "EMA";
	};
	rsi_condition: { period: number; operator: "gt" | "lt"; value: number };
	macd_condition: {
		fast: number;
		slow: number;
		signal: number;
		condition: "cross_above" | "cross_below" | "above_zero" | "below_zero";
	};
	stochastic_condition: {
		k_period: number;
		d_period: number;
		slowing: number;
		zone: "overbought" | "oversold";
	};
	volatility_squeeze: {
		lookback_period: number;
		squeeze_ratio: number;
		timeframe?: string;
	};
	level_touch_analyzer: {
		level_source: number;
		touch_tolerance_pct: number;
		lookback_candles: number;
		min_touches: number;
		invalidate_on_pierce: boolean;
		timeframe?: string;
	};
	price_action_analyzer: {
		lookback_candles: number;
		order: number;
		structure_type: "higher_lows" | "lower_highs";
		min_points: number;
		timeframe?: string;
	};
}

export type FoundationKey = keyof FoundationParamsState;

interface FoundationParamsFormProps {
	foundationTypes: FoundationKey[];
	onParamsChange: (params: string) => void;
}

export const FoundationParamsForm = ({
	foundationTypes,
	onParamsChange,
}: FoundationParamsFormProps) => {
	const [params, setParams] = useState<FoundationParamsState>({
		significant_level: { kline_1h: 24, kline_4h: 168, kline_1d: 30 },
		local_level: { timeframe: "1h", lookback_period: 24 },
		round_level: {},
		classic_pattern: { pattern_name: "pin_bar", side: "any" },
		volume_confirmation: {},
		price_consolidation: {
			lookback_period: 10,
			max_range_atr: 0.8,
			timeframe: "auto",
		},
		trend_direction: {
			sma_fast_period: 10,
			sma_slow_period: 50,
			rsi_period: 14,
			rsi_lower_bound: 30,
			rsi_upper_bound: 70,
		},
		open_interest: {
			lookback: 5,
			analyze: "change_pct",
			operator: "gt",
			value: 1.0,
		},
		correlation: { lookback: 50, operator: "lt", value: 0.7 },
		tape_acceleration: {
			time_window_sec: 5,
			analysis_type: "count",
			multiplier: 2.0,
		},
		volatility_filter: { indicator: "ATR", operator: "gt", value: 1.0 },
		trend_filter: { indicator: "ADX", threshold: 25.0 },
		natr_filter: { natr_threshold: 1.0 },
		rel_vol_filter: { rel_vol_threshold: 1.5 },
		bollinger_bands_condition: {
			source: "close",
			location: "above_upper",
			shift: 0,
		},
		// New indicators defaults
		ma_crossover: { fast_period: 9, slow_period: 21, ma_type: "EMA" },
		rsi_condition: { period: 14, operator: "lt", value: 30 },
		macd_condition: { fast: 12, slow: 26, signal: 9, condition: "cross_above" },
		stochastic_condition: {
			k_period: 14,
			d_period: 3,
			slowing: 3,
			zone: "oversold",
		},
		volatility_squeeze: {
			lookback_period: 20,
			squeeze_ratio: 0.6,
			timeframe: "auto",
		},
		level_touch_analyzer: {
			level_source: 0,
			touch_tolerance_pct: 0.1,
			lookback_candles: 100,
			min_touches: 1,
			invalidate_on_pierce: true,
			timeframe: "auto",
		},
		price_action_analyzer: {
			lookback_candles: 50,
			order: 3,
			structure_type: "higher_lows",
			min_points: 2,
			timeframe: "auto",
		},
	});

	useEffect(() => {
		const activeParams: Record<string, unknown> = {};
		foundationTypes.forEach((type) => {
			activeParams[type] = params[type];
		});
		onParamsChange(JSON.stringify(activeParams));
	}, [foundationTypes, params, onParamsChange]);

	const handleParamChange = <T extends FoundationKey>(
		type: T,
		param: keyof FoundationParamsState[T],
		value: unknown,
	) => {
		setParams((prev) => ({
			...prev,
			[type]: {
				...prev[type],
				[param]: value,
			},
		}));
	};

	const renderForm = (type: FoundationKey) => {
		switch (type) {
			case "significant_level":
				return (
					<div className="space-y-2 mt-2 p-2 border rounded-md">
						<h4 className="font-semibold">Significant Level</h4>
						<div>
							<Label>Lookback 1h</Label>
							<Input
								type="number"
								value={params.significant_level.kline_1h}
								onChange={(e) =>
									handleParamChange(
										"significant_level",
										"kline_1h",
										Number(e.target.value),
									)
								}
							/>
						</div>
						<div>
							<Label>Lookback 4h</Label>
							<Input
								type="number"
								value={params.significant_level.kline_4h}
								onChange={(e) =>
									handleParamChange(
										"significant_level",
										"kline_4h",
										Number(e.target.value),
									)
								}
							/>
						</div>
						<div>
							<Label>Lookback 1d</Label>
							<Input
								type="number"
								value={params.significant_level.kline_1d}
								onChange={(e) =>
									handleParamChange(
										"significant_level",
										"kline_1d",
										Number(e.target.value),
									)
								}
							/>
						</div>
					</div>
				);
			case "local_level":
				return (
					<div className="space-y-2 mt-2 p-2 border rounded-md">
						<h4 className="font-semibold">Local Level</h4>
						<div>
							<Label>Timeframe</Label>
							<Select
								value={params.local_level.timeframe}
								onValueChange={(value) =>
									handleParamChange("local_level", "timeframe", value)
								}
							>
								<SelectTrigger>
									<SelectValue />
								</SelectTrigger>
								<SelectContent>
									<SelectItem value="1m">1m</SelectItem>
									<SelectItem value="5m">5m</SelectItem>
									<SelectItem value="15m">15m</SelectItem>
									<SelectItem value="1h">1h</SelectItem>
									<SelectItem value="4h">4h</SelectItem>
									<SelectItem value="1d">1d</SelectItem>
								</SelectContent>
							</Select>
						</div>
						<div>
							<Label>Lookback Period</Label>
							<Input
								type="number"
								value={params.local_level.lookback_period}
								onChange={(e) =>
									handleParamChange(
										"local_level",
										"lookback_period",
										Number(e.target.value),
									)
								}
							/>
						</div>
					</div>
				);
			case "round_level":
				return (
					<div className="space-y-2 mt-2 p-2 border rounded-md">
						<h4 className="font-semibold">Round Level</h4>
						<p className="text-sm text-muted-foreground">
							No parameters needed for basic run.
						</p>
					</div>
				);
			case "classic_pattern":
				return (
					<div className="space-y-2 mt-2 p-2 border rounded-md">
						<h4 className="font-semibold">Classic Pattern</h4>
						<div>
							<Label>Pattern Name</Label>
							<Select
								value={params.classic_pattern.pattern_name}
								onValueChange={(value) =>
									handleParamChange("classic_pattern", "pattern_name", value)
								}
							>
								<SelectTrigger>
									<SelectValue />
								</SelectTrigger>
								<SelectContent>
									<SelectItem value="bullish_engulfing">
										Bullish Engulfing
									</SelectItem>
									<SelectItem value="bearish_engulfing">
										Bearish Engulfing
									</SelectItem>
									<SelectItem value="pin_bar">Pin Bar</SelectItem>
									<SelectItem value="doji">Doji</SelectItem>
									<SelectItem value="inside_bar">Inside Bar</SelectItem>
								</SelectContent>
							</Select>
						</div>
						{params.classic_pattern.pattern_name === "pin_bar" && (
							<div>
								<Label>Side</Label>
								<Select
									value={params.classic_pattern.side || "any"}
									onValueChange={(value) =>
										handleParamChange("classic_pattern", "side", value)
									}
								>
									<SelectTrigger>
										<SelectValue />
									</SelectTrigger>
									<SelectContent>
										<SelectItem value="any">Any</SelectItem>
										<SelectItem value="bullish">Bullish</SelectItem>
										<SelectItem value="bearish">Bearish</SelectItem>
									</SelectContent>
								</Select>
							</div>
						)}
					</div>
				);
			case "volume_confirmation":
				return (
					<div className="space-y-2 mt-2 p-2 border rounded-md">
						<h4 className="font-semibold">Volume Confirmation</h4>
						<p className="text-sm text-muted-foreground">
							No parameters needed.
						</p>
					</div>
				);
			case "price_consolidation":
				return (
					<div className="space-y-2 mt-2 p-2 border rounded-md">
						<h4 className="font-semibold">Price Consolidation</h4>
						<div>
							<Label>Timeframe</Label>
							<Select
								value={params.price_consolidation.timeframe || "auto"}
								onValueChange={(value) =>
									handleParamChange("price_consolidation", "timeframe", value)
								}
							>
								<SelectTrigger>
									<SelectValue />
								</SelectTrigger>
								<SelectContent>
									<SelectItem value="auto">Auto (Chart TF)</SelectItem>
									<SelectItem value="1m">1m</SelectItem>
									<SelectItem value="5m">5m</SelectItem>
									<SelectItem value="15m">15m</SelectItem>
									<SelectItem value="1h">1h</SelectItem>
									<SelectItem value="4h">4h</SelectItem>
									<SelectItem value="1d">1d</SelectItem>
								</SelectContent>
							</Select>
						</div>
						<div>
							<Label>Lookback Period</Label>
							<Input
								type="number"
								value={params.price_consolidation.lookback_period}
								onChange={(e) =>
									handleParamChange(
										"price_consolidation",
										"lookback_period",
										Number(e.target.value),
									)
								}
							/>
						</div>
						<div>
							<Label>Max Range (ATR)</Label>
							<Input
								type="number"
								value={params.price_consolidation.max_range_atr}
								onChange={(e) =>
									handleParamChange(
										"price_consolidation",
										"max_range_atr",
										Number(e.target.value),
									)
								}
							/>
						</div>
					</div>
				);
			case "trend_direction":
				return (
					<div className="space-y-2 mt-2 p-2 border rounded-md">
						<h4 className="font-semibold">Trend Direction</h4>
						<div>
							<Label>SMA Fast Period</Label>
							<Input
								type="number"
								value={params.trend_direction.sma_fast_period}
								onChange={(e) =>
									handleParamChange(
										"trend_direction",
										"sma_fast_period",
										Number(e.target.value),
									)
								}
							/>
						</div>
						<div>
							<Label>SMA Slow Period</Label>
							<Input
								type="number"
								value={params.trend_direction.sma_slow_period}
								onChange={(e) =>
									handleParamChange(
										"trend_direction",
										"sma_slow_period",
										Number(e.target.value),
									)
								}
							/>
						</div>
						<div>
							<Label>RSI Period</Label>
							<Input
								type="number"
								value={params.trend_direction.rsi_period}
								onChange={(e) =>
									handleParamChange(
										"trend_direction",
										"rsi_period",
										Number(e.target.value),
									)
								}
							/>
						</div>
						<div>
							<Label>RSI Lower Bound</Label>
							<Input
								type="number"
								value={params.trend_direction.rsi_lower_bound}
								onChange={(e) =>
									handleParamChange(
										"trend_direction",
										"rsi_lower_bound",
										Number(e.target.value),
									)
								}
							/>
						</div>
						<div>
							<Label>RSI Upper Bound</Label>
							<Input
								type="number"
								value={params.trend_direction.rsi_upper_bound}
								onChange={(e) =>
									handleParamChange(
										"trend_direction",
										"rsi_upper_bound",
										Number(e.target.value),
									)
								}
							/>
						</div>
					</div>
				);
			case "open_interest":
				return (
					<div className="space-y-2 mt-2 p-2 border rounded-md">
						<h4 className="font-semibold">Open Interest</h4>
						<div>
							<Label>Lookback</Label>
							<Input
								type="number"
								value={params.open_interest.lookback}
								onChange={(e) =>
									handleParamChange(
										"open_interest",
										"lookback",
										Number(e.target.value),
									)
								}
							/>
						</div>
						<div>
							<Label>Analyze</Label>
							<Select
								value={params.open_interest.analyze}
								onValueChange={(value) =>
									handleParamChange("open_interest", "analyze", value)
								}
							>
								<SelectTrigger>
									<SelectValue />
								</SelectTrigger>
								<SelectContent>
									<SelectItem value="change_pct">Change %</SelectItem>
									<SelectItem value="absolute_value">Absolute Value</SelectItem>
								</SelectContent>
							</Select>
						</div>
						<div>
							<Label>Operator</Label>
							<Select
								value={params.open_interest.operator}
								onValueChange={(value) =>
									handleParamChange("open_interest", "operator", value)
								}
							>
								<SelectTrigger>
									<SelectValue />
								</SelectTrigger>
								<SelectContent>
									<SelectItem value="gt">Greater Than</SelectItem>
									<SelectItem value="lt">Less Than</SelectItem>
								</SelectContent>
							</Select>
						</div>
						<div>
							<Label>Value</Label>
							<Input
								type="number"
								value={params.open_interest.value}
								onChange={(e) =>
									handleParamChange(
										"open_interest",
										"value",
										Number(e.target.value),
									)
								}
							/>
						</div>
					</div>
				);
			case "correlation":
				return (
					<div className="space-y-2 mt-2 p-2 border rounded-md">
						<h4 className="font-semibold">Correlation</h4>
						<div>
							<Label>Lookback</Label>
							<Input
								type="number"
								value={params.correlation.lookback}
								onChange={(e) =>
									handleParamChange(
										"correlation",
										"lookback",
										Number(e.target.value),
									)
								}
							/>
						</div>
						<div>
							<Label>Operator</Label>
							<Select
								value={params.correlation.operator}
								onValueChange={(value) =>
									handleParamChange("correlation", "operator", value)
								}
							>
								<SelectTrigger>
									<SelectValue />
								</SelectTrigger>
								<SelectContent>
									<SelectItem value="gt">Greater Than</SelectItem>
									<SelectItem value="lt">Less Than</SelectItem>
								</SelectContent>
							</Select>
						</div>
						<div>
							<Label>Value</Label>
							<Input
								type="number"
								value={params.correlation.value}
								onChange={(e) =>
									handleParamChange(
										"correlation",
										"value",
										Number(e.target.value),
									)
								}
							/>
						</div>
					</div>
				);
			case "tape_acceleration":
				return (
					<div className="space-y-2 mt-2 p-2 border rounded-md">
						<h4 className="font-semibold">Tape Acceleration</h4>
						<div>
							<Label>Time Window (sec)</Label>
							<Input
								type="number"
								value={params.tape_acceleration.time_window_sec}
								onChange={(e) =>
									handleParamChange(
										"tape_acceleration",
										"time_window_sec",
										Number(e.target.value),
									)
								}
							/>
						</div>
						<div>
							<Label>Analysis Type</Label>
							<Select
								value={params.tape_acceleration.analysis_type}
								onValueChange={(value) =>
									handleParamChange("tape_acceleration", "analysis_type", value)
								}
							>
								<SelectTrigger>
									<SelectValue />
								</SelectTrigger>
								<SelectContent>
									<SelectItem value="count">Count</SelectItem>
									<SelectItem value="volume_usd">Volume (USD)</SelectItem>
									<SelectItem value="delta">Delta</SelectItem>
								</SelectContent>
							</Select>
						</div>
						<div>
							<Label>Multiplier</Label>
							<Input
								type="number"
								value={params.tape_acceleration.multiplier}
								onChange={(e) =>
									handleParamChange(
										"tape_acceleration",
										"multiplier",
										Number(e.target.value),
									)
								}
							/>
						</div>
					</div>
				);
			case "volatility_filter":
				return (
					<div className="space-y-2 mt-2 p-2 border rounded-md">
						<h4 className="font-semibold">Volatility Filter</h4>
						<div>
							<Label>Indicator</Label>
							<Select
								value={params.volatility_filter.indicator}
								onValueChange={(v) =>
									handleParamChange(
										"volatility_filter",
										"indicator",
										v as FoundationParamsState["volatility_filter"]["indicator"],
									)
								}
							>
								<SelectTrigger>
									<SelectValue />
								</SelectTrigger>
								<SelectContent>
									<SelectItem value="ATR">ATR (14)</SelectItem>
									<SelectItem value="BBW">Bollinger Width (20)</SelectItem>
								</SelectContent>
							</Select>
						</div>
						<div>
							<Label>Operator</Label>
							<Select
								value={params.volatility_filter.operator}
								onValueChange={(v) =>
									handleParamChange(
										"volatility_filter",
										"operator",
										v as FoundationParamsState["volatility_filter"]["operator"],
									)
								}
							>
								<SelectTrigger>
									<SelectValue />
								</SelectTrigger>
								<SelectContent>
									<SelectItem value="gt">Greater Than</SelectItem>
									<SelectItem value="lt">Less Than</SelectItem>
								</SelectContent>
							</Select>
						</div>
						<div>
							<Label>Value</Label>
							<Input
								type="number"
								value={params.volatility_filter.value}
								onChange={(e) =>
									handleParamChange(
										"volatility_filter",
										"value",
										Number(e.target.value),
									)
								}
							/>
						</div>
					</div>
				);
			case "trend_filter":
				return (
					<div className="space-y-2 mt-2 p-2 border rounded-md">
						<h4 className="font-semibold">Trend Filter</h4>
						<div>
							<Label>Indicator</Label>
							<Select
								value={params.trend_filter.indicator}
								onValueChange={(v) =>
									handleParamChange(
										"trend_filter",
										"indicator",
										v as FoundationParamsState["trend_filter"]["indicator"],
									)
								}
							>
								<SelectTrigger>
									<SelectValue />
								</SelectTrigger>
								<SelectContent>
									<SelectItem value="ADX">ADX (14)</SelectItem>
								</SelectContent>
							</Select>
						</div>
						<div>
							<Label>Threshold</Label>
							<Input
								type="number"
								value={params.trend_filter.threshold}
								onChange={(e) =>
									handleParamChange(
										"trend_filter",
										"threshold",
										Number(e.target.value),
									)
								}
							/>
						</div>
					</div>
				);
			case "natr_filter":
				return (
					<div className="space-y-2 mt-2 p-2 border rounded-md">
						<h4 className="font-semibold">NATR Filter</h4>
						<div>
							<Label>Threshold (%)</Label>
							<Input
								type="number"
								value={params.natr_filter.natr_threshold}
								onChange={(e) =>
									handleParamChange(
										"natr_filter",
										"natr_threshold",
										Number(e.target.value),
									)
								}
							/>
						</div>
					</div>
				);
			case "rel_vol_filter":
				return (
					<div className="space-y-2 mt-2 p-2 border rounded-md">
						<h4 className="font-semibold">Relative Volume</h4>
						<div>
							<Label>Threshold (x Average)</Label>
							<Input
								type="number"
								value={params.rel_vol_filter.rel_vol_threshold}
								onChange={(e) =>
									handleParamChange(
										"rel_vol_filter",
										"rel_vol_threshold",
										Number(e.target.value),
									)
								}
							/>
						</div>
					</div>
				);
			case "bollinger_bands_condition":
				return (
					<div className="space-y-2 mt-2 p-2 border rounded-md">
						<h4 className="font-semibold">Bollinger Bands</h4>
						<div>
							<Label>Source</Label>
							<Select
								value={params.bollinger_bands_condition.source}
								onValueChange={(v) =>
									handleParamChange(
										"bollinger_bands_condition",
										"source",
										v as FoundationParamsState["bollinger_bands_condition"]["source"],
									)
								}
							>
								<SelectTrigger>
									<SelectValue />
								</SelectTrigger>
								<SelectContent>
									<SelectItem value="close">Close</SelectItem>
									<SelectItem value="high">High</SelectItem>
									<SelectItem value="low">Low</SelectItem>
								</SelectContent>
							</Select>
						</div>
						<div>
							<Label>Location</Label>
							<Select
								value={params.bollinger_bands_condition.location}
								onValueChange={(v) =>
									handleParamChange(
										"bollinger_bands_condition",
										"location",
										v as FoundationParamsState["bollinger_bands_condition"]["location"],
									)
								}
							>
								<SelectTrigger>
									<SelectValue />
								</SelectTrigger>
								<SelectContent>
									<SelectItem value="above_upper">Above Upper Band</SelectItem>
									<SelectItem value="below_lower">Below Lower Band</SelectItem>
								</SelectContent>
							</Select>
						</div>
					</div>
				);

			case "ma_crossover":
				return (
					<div className="space-y-2 mt-2 p-2 border rounded-md">
						<h4 className="font-semibold">MA Crossover</h4>
						<div>
							<Label>MA Type</Label>
							<Select
								value={params.ma_crossover.ma_type}
								onValueChange={(v) =>
									handleParamChange(
										"ma_crossover",
										"ma_type",
										v as FoundationParamsState["ma_crossover"]["ma_type"],
									)
								}
							>
								<SelectTrigger>
									<SelectValue />
								</SelectTrigger>
								<SelectContent>
									<SelectItem value="SMA">SMA</SelectItem>
									<SelectItem value="EMA">EMA</SelectItem>
								</SelectContent>
							</Select>
						</div>
						<div>
							<Label>Fast Period</Label>
							<Input
								type="number"
								value={params.ma_crossover.fast_period}
								onChange={(e) =>
									handleParamChange(
										"ma_crossover",
										"fast_period",
										Number(e.target.value),
									)
								}
							/>
						</div>
						<div>
							<Label>Slow Period</Label>
							<Input
								type="number"
								value={params.ma_crossover.slow_period}
								onChange={(e) =>
									handleParamChange(
										"ma_crossover",
										"slow_period",
										Number(e.target.value),
									)
								}
							/>
						</div>
					</div>
				);

			case "rsi_condition":
				return (
					<div className="space-y-2 mt-2 p-2 border rounded-md">
						<h4 className="font-semibold">RSI Condition</h4>
						<div>
							<Label>Period</Label>
							<Input
								type="number"
								value={params.rsi_condition.period}
								onChange={(e) =>
									handleParamChange(
										"rsi_condition",
										"period",
										Number(e.target.value),
									)
								}
							/>
						</div>
						<div>
							<Label>Operator</Label>
							<Select
								value={params.rsi_condition.operator}
								onValueChange={(v) =>
									handleParamChange(
										"rsi_condition",
										"operator",
										v as FoundationParamsState["rsi_condition"]["operator"],
									)
								}
							>
								<SelectTrigger>
									<SelectValue />
								</SelectTrigger>
								<SelectContent>
									<SelectItem value="gt">Greater Than</SelectItem>
									<SelectItem value="lt">Less Than</SelectItem>
								</SelectContent>
							</Select>
						</div>
						<div>
							<Label>Value</Label>
							<Input
								type="number"
								value={params.rsi_condition.value}
								onChange={(e) =>
									handleParamChange(
										"rsi_condition",
										"value",
										Number(e.target.value),
									)
								}
							/>
						</div>
					</div>
				);

			case "macd_condition":
				return (
					<div className="space-y-2 mt-2 p-2 border rounded-md">
						<h4 className="font-semibold">MACD</h4>
						<div>
							<Label>Fast</Label>
							<Input
								type="number"
								value={params.macd_condition.fast}
								onChange={(e) =>
									handleParamChange(
										"macd_condition",
										"fast",
										Number(e.target.value),
									)
								}
							/>
						</div>
						<div>
							<Label>Slow</Label>
							<Input
								type="number"
								value={params.macd_condition.slow}
								onChange={(e) =>
									handleParamChange(
										"macd_condition",
										"slow",
										Number(e.target.value),
									)
								}
							/>
						</div>
						<div>
							<Label>Signal</Label>
							<Input
								type="number"
								value={params.macd_condition.signal}
								onChange={(e) =>
									handleParamChange(
										"macd_condition",
										"signal",
										Number(e.target.value),
									)
								}
							/>
						</div>
						<div>
							<Label>Condition</Label>
							<Select
								value={params.macd_condition.condition}
								onValueChange={(v) =>
									handleParamChange(
										"macd_condition",
										"condition",
										v as FoundationParamsState["macd_condition"]["condition"],
									)
								}
							>
								<SelectTrigger>
									<SelectValue />
								</SelectTrigger>
								<SelectContent>
									<SelectItem value="cross_above">
										Cross Above Signal
									</SelectItem>
									<SelectItem value="cross_below">
										Cross Below Signal
									</SelectItem>
									<SelectItem value="above_zero">Above Zero Line</SelectItem>
									<SelectItem value="below_zero">Below Zero Line</SelectItem>
								</SelectContent>
							</Select>
						</div>
					</div>
				);

			case "stochastic_condition":
				return (
					<div className="space-y-2 mt-2 p-2 border rounded-md">
						<h4 className="font-semibold">Stochastic</h4>
						<div>
							<Label>%K Period</Label>
							<Input
								type="number"
								value={params.stochastic_condition.k_period}
								onChange={(e) =>
									handleParamChange(
										"stochastic_condition",
										"k_period",
										Number(e.target.value),
									)
								}
							/>
						</div>
						<div>
							<Label>%D Period</Label>
							<Input
								type="number"
								value={params.stochastic_condition.d_period}
								onChange={(e) =>
									handleParamChange(
										"stochastic_condition",
										"d_period",
										Number(e.target.value),
									)
								}
							/>
						</div>
						<div>
							<Label>Slowing</Label>
							<Input
								type="number"
								value={params.stochastic_condition.slowing}
								onChange={(e) =>
									handleParamChange(
										"stochastic_condition",
										"slowing",
										Number(e.target.value),
									)
								}
							/>
						</div>
						<div>
							<Label>Zone</Label>
							<Select
								value={params.stochastic_condition.zone}
								onValueChange={(v) =>
									handleParamChange(
										"stochastic_condition",
										"zone",
										v as FoundationParamsState["stochastic_condition"]["zone"],
									)
								}
							>
								<SelectTrigger>
									<SelectValue />
								</SelectTrigger>
								<SelectContent>
									<SelectItem value="oversold">Oversold (&lt;20)</SelectItem>
									<SelectItem value="overbought">
										Overbought (&gt;80)
									</SelectItem>
								</SelectContent>
							</Select>
						</div>
					</div>
				);

			case "volatility_squeeze":
				return (
					<div className="space-y-2 mt-2 p-2 border rounded-md">
						<h4 className="font-semibold">Volatility Squeeze</h4>
						<div>
							<Label>Timeframe</Label>
							<Select
								value={params.volatility_squeeze.timeframe || "auto"}
								onValueChange={(value) =>
									handleParamChange("volatility_squeeze", "timeframe", value)
								}
							>
								<SelectTrigger>
									<SelectValue />
								</SelectTrigger>
								<SelectContent>
									<SelectItem value="auto">Auto (Chart TF)</SelectItem>
									<SelectItem value="1m">1m</SelectItem>
									<SelectItem value="5m">5m</SelectItem>
									<SelectItem value="15m">15m</SelectItem>
									<SelectItem value="1h">1h</SelectItem>
								</SelectContent>
							</Select>
						</div>
						<div>
							<Label>Lookback Period</Label>
							<Input
								type="number"
								value={params.volatility_squeeze.lookback_period}
								onChange={(e) =>
									handleParamChange(
										"volatility_squeeze",
										"lookback_period",
										Number(e.target.value),
									)
								}
							/>
						</div>
						<div>
							<Label>Squeeze Ratio</Label>
							<Input
								type="number"
								step="0.1"
								value={params.volatility_squeeze.squeeze_ratio}
								onChange={(e) =>
									handleParamChange(
										"volatility_squeeze",
										"squeeze_ratio",
										Number(e.target.value),
									)
								}
							/>
						</div>
					</div>
				);

			case "level_touch_analyzer":
				return (
					<div className="space-y-2 mt-2 p-2 border rounded-md">
						<h4 className="font-semibold">Level Touch</h4>
						<div>
							<Label>Level Source (Price)</Label>
							<Input
								type="number"
								step="0.01"
								value={params.level_touch_analyzer.level_source}
								onChange={(e) =>
									handleParamChange(
										"level_touch_analyzer",
										"level_source",
										Number(e.target.value),
									)
								}
							/>
						</div>
						<div className="grid grid-cols-2 gap-2">
							<div>
								<Label>Tolerance (%)</Label>
								<Input
									type="number"
									step="0.01"
									value={params.level_touch_analyzer.touch_tolerance_pct}
									onChange={(e) =>
										handleParamChange(
											"level_touch_analyzer",
											"touch_tolerance_pct",
											Number(e.target.value),
										)
									}
								/>
							</div>
							<div>
								<Label>Lookback</Label>
								<Input
									type="number"
									value={params.level_touch_analyzer.lookback_candles}
									onChange={(e) =>
										handleParamChange(
											"level_touch_analyzer",
											"lookback_candles",
											Number(e.target.value),
										)
									}
								/>
							</div>
						</div>
						<div className="grid grid-cols-2 gap-2">
							<div>
								<Label>Min Touches</Label>
								<Input
									type="number"
									value={params.level_touch_analyzer.min_touches}
									onChange={(e) =>
										handleParamChange(
											"level_touch_analyzer",
											"min_touches",
											Number(e.target.value),
										)
									}
								/>
							</div>
							<div className="flex items-center space-x-2 pt-6">
								<input
									type="checkbox"
									id="invalidate_on_pierce"
									checked={params.level_touch_analyzer.invalidate_on_pierce}
									onChange={(e) =>
										handleParamChange(
											"level_touch_analyzer",
											"invalidate_on_pierce",
											e.target.checked,
										)
									}
								/>
								<Label htmlFor="invalidate_on_pierce">No Pierce</Label>
							</div>
						</div>
					</div>
				);

			case "price_action_analyzer":
				return (
					<div className="space-y-2 mt-2 p-2 border rounded-md">
						<h4 className="font-semibold">Price Action</h4>
						<div>
							<Label>Structure Type</Label>
							<Select
								value={params.price_action_analyzer.structure_type}
								onValueChange={(v) =>
									handleParamChange(
										"price_action_analyzer",
										"structure_type",
										v as FoundationParamsState["price_action_analyzer"]["structure_type"],
									)
								}
							>
								<SelectTrigger>
									<SelectValue />
								</SelectTrigger>
								<SelectContent>
									<SelectItem value="higher_lows">
										Higher Lows (Bullish)
									</SelectItem>
									<SelectItem value="lower_highs">
										Lower Highs (Bearish)
									</SelectItem>
								</SelectContent>
							</Select>
						</div>
						<div className="grid grid-cols-3 gap-2">
							<div>
								<Label>Lookback</Label>
								<Input
									type="number"
									value={params.price_action_analyzer.lookback_candles}
									onChange={(e) =>
										handleParamChange(
											"price_action_analyzer",
											"lookback_candles",
											Number(e.target.value),
										)
									}
								/>
							</div>
							<div>
								<Label>Points</Label>
								<Input
									type="number"
									value={params.price_action_analyzer.min_points}
									onChange={(e) =>
										handleParamChange(
											"price_action_analyzer",
											"min_points",
											Number(e.target.value),
										)
									}
								/>
							</div>
							<div>
								<Label>Order</Label>
								<Input
									type="number"
									value={params.price_action_analyzer.order}
									onChange={(e) =>
										handleParamChange(
											"price_action_analyzer",
											"order",
											Number(e.target.value),
										)
									}
								/>
							</div>
						</div>
					</div>
				);

			default:
				return null;
		}
	};

	return (
		<div className="space-y-4">
			{foundationTypes.map((type) => (
				<div key={type}>{renderForm(type)}</div>
			))}
		</div>
	);
};
