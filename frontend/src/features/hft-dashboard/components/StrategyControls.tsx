// src/features/hft-dashboard/components/StrategyControls.tsx

import {
	Activity,
	Layers,
	Lock,
	Settings2,
	ShieldAlert,
	Unlock,
} from "lucide-react";
import type React from "react";
import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import {
	Select,
	SelectContent,
	SelectItem,
	SelectTrigger,
	SelectValue,
} from "@/components/ui/select";
import { Slider } from "@/components/ui/slider";
import { Switch } from "@/components/ui/switch";
import { useAuth } from "../../../context/AuthContext";
import { useHftStore } from "../hooks/useHftStore";
import type { HftConfig, PartialTakeProfitConfig } from "../types/hft.types";

const apiBase = import.meta.env.VITE_PUBLIC_API_URL || "";

export const StrategyControls: React.FC = () => {
	const { config, setConfig } = useHftStore();
	const { token: authToken } = useAuth();
	const [localConfig, setLocalConfig] = useState<HftConfig>({
		entry_threshold: 0.5,
		max_position_size_usd: 100,
		sl_type: "ATR",
		sl_val: 0.02,
		min_sl_percent: 0.0005,
		stop_loss_cooldown_seconds: 0,
		tp_type: "RR",
		tp_val: 20.0,
		be_enabled: false,
		be_type: "RR",
		be_threshold: 1.0,
		be_offset_pct: 0.1,
		trailing_stop_enabled: false,
		risk_per_trade_pct: 1.0,
		max_leverage: 20.0,
		max_hold_minutes: 15,
		use_screener: true,
		use_oracle: true,
		use_maker_mode: true,
		max_analyzed_symbols: 10,
		max_concurrent_trades: 3,
		use_risk_size: true,
		min_volume_24h: 50000000,
		entry_slippage_limit: 0.0005,
		liquidity_safety_factor: 10,
		max_spread_pct: 0.001,
		auto_exit_on_low_confidence: false,
		exit_confidence_threshold: 0.4,
		sl_trigger_type: "LAST",
		partial_tp: {
			use_limit_orders: true,
			ptp1_enabled: true,
			ptp1_rr: 4.0,
			ptp1_percent: 20.0,
			ptp2_enabled: true,
			ptp2_rr: 8.0,
			ptp2_percent: 20.0,
			ptp3_enabled: true,
			ptp3_rr: 12.0,
			ptp3_percent: 20.0,
			ptp4_enabled: true,
			ptp4_rr: 16.0,
			ptp4_percent: 20.0,
		},
	});
	const [configLocked, setConfigLocked] = useState(true);

	const fetchConfig = useCallback(async () => {
		const token = authToken;
		if (!token) return;
		try {
			const res = await fetch(`${apiBase}/api/v1/hft/config`, {
				headers: { Authorization: `Bearer ${token}` },
			});
			if (res.ok) {
				const data = await res.json();
				setConfig(data);
				setLocalConfig(data);
			}
		} catch (e) {
			console.error(e);
		}
	}, [authToken, setConfig]);

	const [prevConfig, setPrevConfig] = useState<HftConfig | null>(null);
	if (config !== prevConfig) {
		setPrevConfig(config);
		if (config) {
			setLocalConfig(config);
		}
	}

	useEffect(() => {
		if (!config) {
			const timer = setTimeout(() => {
				fetchConfig();
			}, 0);
			return () => clearTimeout(timer);
		}
	}, [config, fetchConfig]);

	const handleSave = async () => {
		const token = authToken;
		if (!token) return;

		try {
			const res = await fetch(`${apiBase}/api/v1/hft/config`, {
				method: "POST",
				headers: {
					Authorization: `Bearer ${token}`,
					"Content-Type": "application/json",
				},
				body: JSON.stringify(localConfig),
			});
			if (res.ok) {
				setConfig(localConfig);
				toast.success("Configuration synced successfully");
			} else {
				toast.error("Failed to sync configuration");
			}
		} catch {
			toast.error("Network error during sync");
		}
	};

	const handleChange = <K extends keyof HftConfig>(
		key: K,
		value: HftConfig[K],
	) => {
		setLocalConfig((prev: HftConfig) => ({ ...prev, [key]: value }));
	};

	const handlePtpChange = <K extends keyof PartialTakeProfitConfig>(
		key: K,
		value: PartialTakeProfitConfig[K],
	) => {
		setLocalConfig((prev: HftConfig) => ({
			...prev,
			partial_tp: { ...prev.partial_tp, [key]: value },
		}));
	};

	return (
		<div className="h-full flex flex-col bg-card">
			<CardHeader className="py-2 px-3 border-b border-border/40 flex flex-row items-center justify-between sticky top-0 bg-card z-10 shrink-0">
				<CardTitle className="text-xs uppercase font-bold tracking-widest text-muted-foreground flex items-center gap-2">
					<Settings2 size={14} className="text-cyan-500" />
					Mission Config
				</CardTitle>
				<Button
					variant={configLocked ? "outline" : "secondary"}
					size="icon"
					className="h-6 w-6 transition-all"
					onClick={() => setConfigLocked(!configLocked)}
				>
					{configLocked ? (
						<Lock size={12} />
					) : (
						<Unlock size={12} className="text-amber-500" />
					)}
				</Button>
			</CardHeader>

			<div className="flex-1 overflow-y-auto p-2 space-y-4">
				{/* Logic Handlers */}
				<div className="space-y-2">
					<div className="flex items-center gap-2 text-muted-foreground">
						<Layers size={14} />
						<span className="text-xs font-bold uppercase tracking-wider">
							Logic Handlers
						</span>
					</div>

					<div
						className={`space-y-4 ${configLocked ? "opacity-50 pointer-events-none" : ""}`}
					>
						{/* Entry Threshold */}
						<div className="space-y-3">
							<div className="flex justify-between items-center">
								<label className="text-xs font-medium">
									Confidence Threshold
								</label>
								<Input
									type="number"
									step="0.001"
									min="0"
									max="1"
									value={localConfig.entry_threshold}
									onChange={(e) =>
										handleChange("entry_threshold", parseFloat(e.target.value))
									}
									className="h-6 w-20 font-mono text-[10px] text-right"
								/>
							</div>
							<Slider
								value={[localConfig.entry_threshold]}
								min={0}
								max={1}
								step={0.01}
								onValueChange={(vals) =>
									handleChange("entry_threshold", vals[0])
								}
								className="w-full"
							/>
						</div>

						{/* Entry Size Mode & Value */}
						<div className="space-y-3">
							<div className="flex justify-between items-center">
								<label className="text-xs font-medium uppercase text-muted-foreground/80">
									Entry Size Mode
								</label>
								<Select
									value={localConfig.use_risk_size ? "PERCENT" : "USDT"}
									onValueChange={(v) =>
										handleChange("use_risk_size", v === "PERCENT")
									}
								>
									<SelectTrigger className="h-6 w-24 text-[10px]">
										<SelectValue />
									</SelectTrigger>
									<SelectContent>
										<SelectItem value="USDT" className="text-xs">
											FIXED USDT
										</SelectItem>
										<SelectItem value="PERCENT" className="text-xs">
											RISK %
										</SelectItem>
									</SelectContent>
								</Select>
							</div>

							{localConfig.use_risk_size ? (
								<div className="space-y-2">
									<label className="text-xs font-medium text-amber-500">
										Risk per Trade (%)
									</label>
									<Input
										type="number"
										value={localConfig.risk_per_trade_pct}
										onChange={(e) =>
											handleChange(
												"risk_per_trade_pct",
												parseFloat(e.target.value),
											)
										}
										className="h-8 font-mono text-xs border-amber-500/30"
									/>
								</div>
							) : (
								<div className="space-y-2">
									<label className="text-xs font-medium text-primary">
										Entry Size (USDT)
									</label>
									<Input
										type="number"
										value={localConfig.max_position_size_usd}
										onChange={(e) =>
											handleChange(
												"max_position_size_usd",
												parseFloat(e.target.value),
											)
										}
										className="h-8 font-mono text-xs"
									/>
								</div>
							)}
						</div>

						{/* Leverage */}
						<div className="space-y-2">
							<label className="text-xs font-medium uppercase text-muted-foreground/80">
								Max Leverage (x)
							</label>
							<Input
								type="number"
								value={localConfig.max_leverage}
								onChange={(e) =>
									handleChange("max_leverage", parseFloat(e.target.value))
								}
								className="h-8 font-mono text-xs"
							/>
						</div>

						{/* Limits */}
						<div className="grid grid-cols-2 gap-4 border-t border-border/40 pt-4">
							<div className="space-y-2">
								<label className="text-xs font-medium uppercase text-muted-foreground/80">
									Max Analyzed
								</label>
								<Input
									type="number"
									value={localConfig.max_analyzed_symbols}
									onChange={(e) =>
										handleChange(
											"max_analyzed_symbols",
											parseInt(e.target.value, 10),
										)
									}
									className="h-8 font-mono text-xs"
								/>
							</div>
							<div className="space-y-2">
								<label className="text-xs font-medium uppercase text-muted-foreground/80">
									Max Trades
								</label>
								<Input
									type="number"
									value={localConfig.max_concurrent_trades}
									onChange={(e) =>
										handleChange(
											"max_concurrent_trades",
											parseInt(e.target.value, 10),
										)
									}
									className="h-8 font-mono text-xs"
								/>
							</div>
							<div className="col-span-2 space-y-2 border-t border-border/40 pt-2">
								<label className="text-xs font-medium uppercase text-muted-foreground/80">
									Min 24h Volume (USD)
								</label>
								<Input
									type="number"
									value={localConfig.min_volume_24h || 50000000}
									onChange={(e) =>
										handleChange("min_volume_24h", parseFloat(e.target.value))
									}
									className="h-8 font-mono text-xs text-blue-500 border-blue-500/30"
								/>
							</div>
						</div>

						{/* Toggles */}
						<div className="grid grid-cols-2 gap-4 pt-2">
							<div className="flex items-center justify-between p-2 rounded-md border border-border/40 bg-muted/10">
								<label className="text-[10px] font-medium uppercase">
									Screener
								</label>
								<Switch
									checked={localConfig.use_screener}
									onCheckedChange={(checked) =>
										handleChange("use_screener", checked)
									}
								/>
							</div>
							<div className="flex items-center justify-between p-2 rounded-md border border-border/40 bg-muted/10">
								<label className="text-[10px] font-medium uppercase">
									Oracle
								</label>
								<Switch
									checked={localConfig.use_oracle}
									onCheckedChange={(checked) =>
										handleChange("use_oracle", checked)
									}
								/>
							</div>
						</div>

						{/* Maker Mode, Trade on Close, Auto Blacklist */}
						<div className="grid grid-cols-3 gap-4">
							<div className="flex items-center justify-between p-2 rounded-md border border-cyan-500/30 bg-cyan-500/5">
								<div className="flex flex-col">
									<label className="text-[10px] font-medium uppercase text-cyan-400">
										Maker Mode
									</label>
									<span className="text-[8px] text-muted-foreground">
										LIMIT entry
									</span>
								</div>
								<Switch
									checked={localConfig.use_maker_mode ?? false}
									onCheckedChange={(checked) =>
										handleChange("use_maker_mode", checked)
									}
								/>
							</div>
							<div className="flex items-center justify-between p-2 rounded-md border border-purple-500/30 bg-purple-500/5">
								<div className="flex flex-col">
									<label className="text-[10px] font-medium uppercase text-purple-400">
										Candle Close
									</label>
									<span className="text-[8px] text-muted-foreground">
										Safer Entry
									</span>
								</div>
								<Switch
									checked={localConfig.trade_on_close_only ?? true}
									onCheckedChange={(checked) =>
										handleChange("trade_on_close_only", checked)
									}
								/>
							</div>
							<div className="flex items-center justify-between p-2 rounded-md border border-rose-500/30 bg-rose-500/5">
								<div className="flex flex-col">
									<label className="text-[10px] font-medium uppercase text-rose-400">
										No Auto BL
									</label>
									<span className="text-[8px] text-muted-foreground">
										Manual Only
									</span>
								</div>
								<Switch
									checked={localConfig.ignore_auto_blacklist_rules ?? false}
									onCheckedChange={(checked) =>
										handleChange("ignore_auto_blacklist_rules", checked)
									}
								/>
							</div>
						</div>

						{/* Mock Screener / Manual Mode */}
						<div className="space-y-2 border-t border-border/40 pt-4 pb-2">
							<div className="flex items-center justify-between">
								<div className="flex items-center gap-2">
									<Activity size={14} className="text-pink-500" />
									<label className="text-xs font-bold uppercase tracking-wider text-muted-foreground">
										Manual Injection
									</label>
								</div>
								<Switch
									checked={localConfig.mock_screener_enabled ?? false}
									onCheckedChange={(v) =>
										handleChange("mock_screener_enabled", v)
									}
								/>
							</div>

							{localConfig.mock_screener_enabled && (
								<div className="space-y-2 p-2 bg-pink-500/5 rounded border border-pink-500/20">
									<label className="text-[10px] text-pink-400 font-bold uppercase">
										Symbols (Comma Separated)
									</label>
									<textarea
										className="flex min-h-[60px] w-full rounded-md border border-input bg-background/50 px-3 py-2 text-[10px] font-mono shadow-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring text-pink-300 placeholder:text-pink-500/30"
										value={localConfig.mock_screener_symbols?.join(", ") || ""}
										onChange={(e) => {
											const val = e.target.value;
											const syms = val
												.split(",")
												.map((s) => s.trim().replace(/['"]/g, "").toUpperCase())
												.filter(Boolean);
											handleChange("mock_screener_symbols", syms);
										}}
										placeholder="BTCUSDT, ETHUSDT..."
									/>
									<div className="text-[9px] text-muted-foreground">
										Overrides screener. Bot will immediately trade these coins
										if Strategy allows.
									</div>
								</div>
							)}
						</div>

						{/* Liquidity & Spread */}
						<div className="space-y-3 pt-2 border-t border-border/40">
							<label className="text-[10px] font-bold uppercase text-muted-foreground tracking-widest flex items-center gap-2">
								Liquidity & Spread
							</label>

							<div className="grid grid-cols-2 gap-3">
								<div className="space-y-1">
									<label className="text-[9px] uppercase text-muted-foreground">
										Max Slippage (%)
									</label>
									<Input
										type="number"
										step="0.01"
										value={(
											(localConfig.entry_slippage_limit || 0.0005) * 100
										).toFixed(2)}
										onChange={(e) =>
											handleChange(
												"entry_slippage_limit",
												parseFloat(e.target.value) / 100,
											)
										}
										className="h-7 font-mono text-[10px]"
									/>
								</div>
								<div className="space-y-1">
									<label className="text-[9px] uppercase text-muted-foreground">
										Max Spread (%)
									</label>
									<Input
										type="number"
										step="0.01"
										value={(
											(localConfig.max_spread_pct || 0.001) * 100
										).toFixed(2)}
										onChange={(e) =>
											handleChange(
												"max_spread_pct",
												parseFloat(e.target.value) / 100,
											)
										}
										className="h-7 font-mono text-[10px]"
									/>
								</div>
								<div className="space-y-1 col-span-2">
									<div className="flex justify-between">
										<label className="text-[9px] uppercase text-muted-foreground">
											Liquidity Safety Factor (x)
										</label>
										<span className="text-[9px] font-mono text-cyan-500">
											{localConfig.liquidity_safety_factor || 10}x
										</span>
									</div>
									<Slider
										value={[localConfig.liquidity_safety_factor || 10]}
										min={1}
										max={50}
										step={1}
										onValueChange={(vals) =>
											handleChange("liquidity_safety_factor", vals[0])
										}
										className="py-1"
									/>
								</div>
							</div>
						</div>

						{/* Confidence Exit */}
						<div className="space-y-3 pt-2 border-t border-border/40">
							<div className="flex items-center justify-between">
								<label className="text-[10px] font-bold uppercase text-muted-foreground tracking-widest flex items-center gap-2">
									Adaptive Exit
								</label>
								<Switch
									checked={localConfig.auto_exit_on_low_confidence ?? false}
									onCheckedChange={(checked) =>
										handleChange("auto_exit_on_low_confidence", checked)
									}
									className="scale-75"
								/>
							</div>

							{localConfig.auto_exit_on_low_confidence && (
								<div className="space-y-2 p-2 rounded border border-rose-500/20 bg-rose-500/5">
									<div className="flex justify-between items-center">
										<label className="text-[9px] uppercase text-muted-foreground">
											Exit Confidence Threshold
										</label>
										<span className="text-[9px] font-mono text-rose-400">
											{localConfig.exit_confidence_threshold || 0.4}
										</span>
									</div>
									<Slider
										value={[localConfig.exit_confidence_threshold || 0.4]}
										min={0}
										max={1}
										step={0.01}
										onValueChange={(vals) =>
											handleChange("exit_confidence_threshold", vals[0])
										}
										className="py-1"
									/>
									<p className="text-[8px] text-muted-foreground/70 italic">
										Position will close if model confidence drops below this
										level for 5s
									</p>
								</div>
							)}
						</div>
					</div>
				</div>

				{/* Risk Handlers */}
				<div className="space-y-4">
					<div className="flex items-center gap-2 text-rose-500">
						<ShieldAlert size={14} />
						<span className="text-xs font-bold uppercase tracking-wider">
							Risk Handlers
						</span>
					</div>

					<div
						className={`space-y-4 p-4 rounded-lg border border-border/40 bg-muted/20 ${configLocked ? "opacity-50 pointer-events-none" : ""}`}
					>
						{/* Stop Loss */}
						<div className="space-y-2">
							<div className="flex justify-between items-center">
								<label className="text-[10px] font-medium uppercase text-muted-foreground">
									Stop Loss
								</label>
								<Select
									value={localConfig.sl_type}
									onValueChange={(v: string) =>
										handleChange(
											"sl_type",
											v as "PERCENT" | "ATR" | "VOLATILITY",
										)
									}
								>
									<SelectTrigger className="h-6 w-24 text-[10px]">
										<SelectValue />
									</SelectTrigger>
									<SelectContent>
										<SelectItem value="PERCENT" className="text-xs">
											PERCENT
										</SelectItem>
										<SelectItem value="ATR" className="text-xs">
											ATR
										</SelectItem>
										<SelectItem value="VOLATILITY" className="text-xs">
											VOLATILITY
										</SelectItem>
									</SelectContent>
								</Select>
							</div>
							<Input
								type="number"
								step="0.01"
								value={localConfig.sl_val}
								onChange={(e) =>
									handleChange("sl_val", parseFloat(e.target.value))
								}
								className="h-8 font-mono text-xs text-rose-500 border-rose-500/30"
							/>

							{/* Min SL Percent */}
							<div className="flex justify-between items-center pt-2">
								<label className="text-[9px] uppercase text-muted-foreground/80">
									Min SL %
								</label>
								<Input
									type="number"
									step="0.01"
									min="0.01"
									value={((localConfig.min_sl_percent || 0.0005) * 100).toFixed(
										2,
									)}
									onChange={(e) =>
										handleChange(
											"min_sl_percent",
											parseFloat(e.target.value) / 100,
										)
									}
									className="h-6 w-20 font-mono text-[10px] text-right text-rose-500/80 border-rose-500/20"
								/>
							</div>

							{/* SL Trigger Type */}
							<div className="flex justify-between items-center pt-2">
								<label className="text-[9px] uppercase text-muted-foreground/80">
									Trigger
								</label>
								<div className="flex bg-muted/20 rounded p-0.5 border border-border/30">
									{["MARK", "LAST"].map((type) => (
										<button
											key={type}
											onClick={() => handleChange("sl_trigger_type", type)}
											className={`px-2 py-0.5 rounded text-[8px] font-bold transition-all ${
												(localConfig.sl_trigger_type || "LAST") === type
													? "bg-rose-500/20 text-rose-500 border border-rose-500/30 shadow-sm"
													: "text-muted-foreground hover:text-foreground"
											}`}
										>
											{type}
										</button>
									))}
								</div>
							</div>

							{/* SL Cooldown */}
							<div className="flex justify-between items-center pt-2">
								<label className="text-[9px] uppercase text-muted-foreground/80">
									Cooldown (sec)
								</label>
								<Input
									type="number"
									min="0"
									value={localConfig.stop_loss_cooldown_seconds || 0}
									onChange={(e) =>
										handleChange(
											"stop_loss_cooldown_seconds",
											parseInt(e.target.value, 10),
										)
									}
									className="h-6 w-16 font-mono text-[10px] text-right"
								/>
							</div>
						</div>

						{/* Take Profit */}
						<div className="space-y-2 border-t border-border/40 pt-2">
							<div className="flex justify-between items-center">
								<label className="text-[10px] font-medium uppercase text-muted-foreground">
									Take Profit
								</label>
								<Select
									value={localConfig.tp_type}
									onValueChange={(v: string) =>
										handleChange(
											"tp_type",
											v as "PERCENT" | "ATR" | "RR" | "VOLATILITY",
										)
									}
								>
									<SelectTrigger className="h-6 w-24 text-[10px]">
										<SelectValue />
									</SelectTrigger>
									<SelectContent>
										<SelectItem value="PERCENT" className="text-xs">
											PERCENT
										</SelectItem>
										<SelectItem value="ATR" className="text-xs">
											ATR
										</SelectItem>
										<SelectItem value="RR" className="text-xs">
											RR (R:R)
										</SelectItem>
										<SelectItem value="VOLATILITY" className="text-xs">
											VOLATILITY
										</SelectItem>
									</SelectContent>
								</Select>
							</div>
							<Input
								type="number"
								step="0.01"
								value={localConfig.tp_val}
								onChange={(e) =>
									handleChange("tp_val", parseFloat(e.target.value))
								}
								className="h-8 font-mono text-xs text-emerald-500 border-emerald-500/30"
							/>
						</div>

						{/* Breakeven */}
						<div className="space-y-2 border-t border-border/40 pt-2 pb-2">
							<div className="flex justify-between items-center">
								<div className="flex items-center gap-2">
									<Switch
										checked={localConfig.be_enabled}
										onCheckedChange={(v) => handleChange("be_enabled", v)}
									/>
									<label className="text-[10px] font-medium uppercase text-muted-foreground">
										Breakeven
									</label>
								</div>
								<Select
									value={localConfig.be_type}
									onValueChange={(v: string) =>
										handleChange("be_type", v as "PERCENT" | "RR")
									}
									disabled={!localConfig.be_enabled}
								>
									<SelectTrigger className="h-6 w-24 text-[10px]">
										<SelectValue />
									</SelectTrigger>
									<SelectContent>
										<SelectItem value="PERCENT" className="text-xs">
											PERCENT
										</SelectItem>
										<SelectItem value="RR" className="text-xs">
											RR
										</SelectItem>
									</SelectContent>
								</Select>
							</div>
							{localConfig.be_enabled && (
								<div className="space-y-2">
									<Input
										type="number"
										step="0.1"
										value={localConfig.be_threshold}
										onChange={(e) =>
											handleChange("be_threshold", parseFloat(e.target.value))
										}
										className="h-8 font-mono text-xs text-amber-500 border-amber-500/30"
										placeholder="Threshold (R)"
									/>
									<div className="flex items-center gap-2">
										<label className="text-[9px] uppercase text-muted-foreground whitespace-nowrap min-w-[50px]">
											Fees Offset %
										</label>
										<Input
											type="number"
											step="0.01"
											value={localConfig.be_offset_pct || 0}
											onChange={(e) =>
												handleChange(
													"be_offset_pct",
													parseFloat(e.target.value),
												)
											}
											className="h-7 font-mono text-[10px] text-amber-500 border-amber-500/30"
											placeholder="0.1"
										/>
									</div>
								</div>
							)}
						</div>

						{/* Partial TPs */}
						<div className="space-y-3 border-t border-border/40 pt-4">
							<div className="flex items-center justify-between">
								<label className="text-[10px] font-bold uppercase text-muted-foreground tracking-widest">
									Partial Take Profits (RR)
								</label>
								<div className="flex items-center gap-1">
									<span className="text-[8px] text-cyan-400 font-bold uppercase">
										Limit Orders
									</span>
									<Switch
										checked={localConfig.partial_tp.use_limit_orders}
										onCheckedChange={(v) =>
											handlePtpChange("use_limit_orders", v)
										}
										className="scale-75"
									/>
								</div>
							</div>

							{[1, 2, 3, 4].map((num) => {
								const ptp = localConfig.partial_tp as unknown as Record<
									string,
									unknown
								>;
								const isEnabled = Boolean(ptp[`ptp${num}_enabled`]);
								const rrVal = Number(ptp[`ptp${num}_rr`] ?? 0);
								const pctVal = Number(ptp[`ptp${num}_percent`] ?? 0);
								return (
									<div
										key={num}
										className="space-y-2 p-2 rounded border border-border/20 bg-muted/5"
									>
										<div className="flex items-center justify-between">
											<div className="flex items-center gap-2">
												<Switch
													checked={isEnabled}
													onCheckedChange={(v) =>
														handlePtpChange(
															`ptp${num}_enabled` as keyof PartialTakeProfitConfig,
															v,
														)
													}
												/>
												<span className="text-[10px] font-medium">
													PTP {num}
												</span>
											</div>
										</div>
										{isEnabled && (
											<div className="grid grid-cols-2 gap-2">
												<div className="space-y-1">
													<label className="text-[10px] uppercase text-muted-foreground italic">
														Target RR
													</label>
													<Input
														type="number"
														step="1"
														value={rrVal}
														onChange={(e) =>
															handlePtpChange(
																`ptp${num}_rr` as keyof PartialTakeProfitConfig,
																parseFloat(e.target.value),
															)
														}
														className="h-6 font-mono text-[10px] bg-background"
													/>
												</div>
												<div className="space-y-1">
													<label className="text-[9px] uppercase text-muted-foreground italic">
														Close %
													</label>
													<Input
														type="number"
														step="1"
														value={pctVal}
														onChange={(e) =>
															handlePtpChange(
																`ptp${num}_percent` as keyof PartialTakeProfitConfig,
																parseFloat(e.target.value),
															)
														}
														className="h-6 font-mono text-[10px] bg-background"
													/>
												</div>
											</div>
										)}
									</div>
								);
							})}
						</div>
					</div>
				</div>

				<Button
					variant={configLocked ? "secondary" : "default"}
					className="w-full text-xs font-bold uppercase tracking-widest gap-2"
					onClick={handleSave}
					disabled={configLocked}
				>
					{configLocked ? <Lock size={12} /> : <Unlock size={12} />}
					Sync Parameters
				</Button>
			</div>
		</div>
	);
};
