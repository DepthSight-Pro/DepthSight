import React, { useState, useEffect } from "react";
import {
	Layers,
	Plus,
	Trash2,
	RotateCcw,
	Save,
	Check,
	Shield,
	Zap,
	Coins,
	Award,
	Edit3,
} from "lucide-react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Switch } from "@/components/ui/switch";
import { Skeleton } from "@/components/ui/skeleton";
import { Label } from "@/components/ui/label";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
	Dialog,
	DialogContent,
	DialogDescription,
	DialogFooter,
	DialogHeader,
	DialogTitle,
} from "@/components/ui/dialog";
import {
	useAdminPlansConfig,
	useAdminUpdatePlansConfig,
	useAdminResetPlansConfig,
} from "@/lib/api";
import type { AdminPlanItem, AdminPlansConfig } from "@/types/api";

const ALL_PERMISSIONS = [
	{ id: "view_dashboard", label: "View Dashboard", desc: "Access to basic monitoring and metrics" },
	{ id: "run_backtest", label: "Vector Backtest", desc: "Run ultra-fast vector simulations" },
	{ id: "run_portfolio_backtest", label: "Portfolio Backtest", desc: "Multi-symbol portfolio backtesting" },
	{ id: "run_optimization", label: "Parameter Optimization", desc: "Grid and random parameter search" },
	{ id: "run_genetic_search", label: "Genetic Search", desc: "Automated genetic strategy evolution" },
	{ id: "run_simulation", label: "Order Simulation", desc: "Granular order microstructure simulation" },
	{ id: "generate_dataset", label: "Dataset Generation", desc: "Generate training datasets in the ML lab" },
	{ id: "train_model", label: "Train ML Models", desc: "Train neural networks and predictive models" },
	{ id: "save_strategy_config", label: "Save Strategies", desc: "Save and export strategy configurations" },
	{ id: "view_strategies", label: "View Strategies", desc: "Browse and inspect strategy library" },
	{ id: "allow_real_trading", label: "Live Trading", desc: "Deploy live automated trading bots" },
	{ id: "use_ai_assistant", label: "AI Assistant", desc: "Access to AI chat and strategy builder" },
];

const QUOTA_FIELDS = [
	{ key: "run_vector_backtest_per_day", label: "Vector Backtests / Day", unit: "runs" },
	{ key: "run_kline_backtest_per_day", label: "Kline Backtests / Day", unit: "runs" },
	{ key: "use_ai_assistant_per_day", label: "AI Queries / Day", unit: "queries" },
	{ key: "run_portfolio_backtest_per_day", label: "Portfolio Backtests / Day", unit: "runs" },
	{ key: "run_optimization_per_month", label: "Optimizations / Month", unit: "runs" },
	{ key: "run_genetic_search_per_month", label: "Genetic Searches / Month", unit: "runs" },
	{ key: "generate_dataset_per_month", label: "Dataset Generations / Month", unit: "runs" },
	{ key: "train_model_per_month", label: "Model Trainings / Month", unit: "runs" },
];

export const AdminPlansPage: React.FC = () => {
	const { data: remoteConfig, isLoading } = useAdminPlansConfig();
	const { mutate: updateConfig, isPending: isUpdating } = useAdminUpdatePlansConfig();
	const { mutate: resetDefaults, isPending: isResetting } = useAdminResetPlansConfig();

	const [config, setConfig] = useState<AdminPlansConfig | null>(null);

	// Plan Editor Dialog State
	const [editingPlanKey, setEditingPlanKey] = useState<string | null>(null);
	const [editingPlanData, setEditingPlanData] = useState<AdminPlanItem | null>(null);
	const [isNewPlan, setIsNewPlan] = useState(false);
	const [newPlanKeyInput, setNewPlanKeyInput] = useState("");

	// Temporary inputs for features and symbols
	const [newFeatureText, setNewFeatureText] = useState("");
	const [newSymbolText, setNewSymbolText] = useState("");
	const [newProBlockText, setNewProBlockText] = useState("");
	const [newKlineBlockText, setNewKlineBlockText] = useState("");

	useEffect(() => {
		if (remoteConfig) {
			setConfig(JSON.parse(JSON.stringify(remoteConfig)));
		}
	}, [remoteConfig]);

	if (isLoading || !config) {
		return (
			<div className="space-y-6">
				<div className="flex justify-between items-center">
					<Skeleton className="h-8 w-64" />
					<Skeleton className="h-10 w-32" />
				</div>
				<div className="grid grid-cols-1 md:grid-cols-3 gap-6">
					<Skeleton className="h-80 w-full" />
					<Skeleton className="h-80 w-full" />
					<Skeleton className="h-80 w-full" />
				</div>
			</div>
		);
	}

	const handleOpenEditPlan = (key: string, plan: AdminPlanItem) => {
		setEditingPlanKey(key);
		setEditingPlanData(JSON.parse(JSON.stringify(plan)));
		setIsNewPlan(false);
	};

	const handleOpenCreatePlan = () => {
		const template: AdminPlanItem = {
			name: "New Tier",
			price_usd: 50,
			active: true,
			description: "Custom subscription tier",
			features: ["Access to core platform features"],
			permissions: ["view_dashboard", "run_backtest", "view_strategies"],
			allowed_symbols: [],
			quotas: {
				run_vector_backtest_per_day: 30,
				run_kline_backtest_per_day: 0,
				use_ai_assistant_per_day: 15,
				run_portfolio_backtest_per_day: 0,
				run_optimization_per_month: 0,
				run_genetic_search_per_month: 0,
				generate_dataset_per_month: 0,
				train_model_per_month: 0,
			},
			limits: {
				allow_real_trading: false,
				max_live_strategies: 0,
				allow_intracandle_triggers: false,
				max_backtest_duration_days: 180,
				celery_task_priority: 7,
				max_concurrent_tasks: 2,
			},
			billing: {
				monthly: { price_usd: 50, period_days: 30 },
				lifetime: { enabled: false, price_usd: 150, slot_limit: 50 },
			},
		};
		setEditingPlanKey("custom_plan");
		setNewPlanKeyInput("");
		setEditingPlanData(template);
		setIsNewPlan(true);
	};

	const handleSavePlanDialog = () => {
		if (!editingPlanData || !config) return;
		const targetKey = isNewPlan ? newPlanKeyInput.trim().toLowerCase() : editingPlanKey;
		if (!targetKey) return;

		const updatedPlans = {
			...config.plans,
			[targetKey]: editingPlanData,
		};

		const newConfig: AdminPlansConfig = {
			...config,
			plans: updatedPlans,
		};

		setConfig(newConfig);
		setEditingPlanKey(null);
		setEditingPlanData(null);

		// Immediately persist changes to backend database
		updateConfig(newConfig);
	};

	const handleDeletePlan = (keyToDelete: string) => {
		if (!config) return;
		const updatedPlans = { ...config.plans };
		delete updatedPlans[keyToDelete];
		const newConfig: AdminPlansConfig = {
			...config,
			plans: updatedPlans,
		};
		setConfig(newConfig);
		updateConfig(newConfig);
	};

	const handleSaveAll = () => {
		if (!config) return;
		updateConfig(config);
	};


	return (
		<div className="space-y-8">
			{/* Top Header */}
			<div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
				<div>
					<h1 className="text-3xl font-bold tracking-tight flex items-center gap-2">
						<Layers className="h-8 w-8 text-primary" />
						Plans & Billing Management
					</h1>
					<p className="text-muted-foreground mt-1">
						Configure pricing, daily quotas, access permissions, execution limits, and referral bonuses.
					</p>
				</div>
				<div className="flex items-center gap-3">
					<Button
						variant="outline"
						size="sm"
						onClick={() => resetDefaults()}
						disabled={isResetting}
						className="flex items-center gap-2"
					>
						<RotateCcw className="h-4 w-4" />
						{isResetting ? "Resetting..." : "Reset to Defaults"}
					</Button>
					<Button
						size="sm"
						onClick={handleSaveAll}
						disabled={isUpdating}
						className="flex items-center gap-2"
					>
						<Save className="h-4 w-4" />
						{isUpdating ? "Saving..." : "Save All Changes"}
					</Button>
				</div>
			</div>

			{/* Main Content Tabs */}
			<Tabs defaultValue="plans" className="space-y-6">
				<TabsList className="grid grid-cols-3 w-full max-w-xl">
					<TabsTrigger value="plans" className="flex items-center gap-2">
						<Zap className="h-4 w-4" />
						Subscription Plans
					</TabsTrigger>
					<TabsTrigger value="billing" className="flex items-center gap-2">
						<Coins className="h-4 w-4" />
						Billing & Trials
					</TabsTrigger>
					<TabsTrigger value="restrictions" className="flex items-center gap-2">
						<Shield className="h-4 w-4" />
						Restrictions & Referrals
					</TabsTrigger>
				</TabsList>

				{/* TAB 1: Plans Grid */}
				<TabsContent value="plans" className="space-y-6">
					<div className="flex justify-between items-center">
						<h2 className="text-xl font-semibold">Configured Subscription Tiers</h2>
						<Button onClick={handleOpenCreatePlan} size="sm" className="flex items-center gap-2">
							<Plus className="h-4 w-4" />
							Add Plan
						</Button>
					</div>

					<div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
						{Object.entries(config.plans).map(([key, plan]) => {
							const effectivePrice = plan.price_usd;
							const isLifetime = plan.billing?.lifetime?.enabled;

							return (
								<Card key={key} className={`relative flex flex-col justify-between border-2 transition-all ${plan.active ? "border-border shadow-sm hover:border-primary/50" : "border-destructive/30 opacity-70"}`}>
									<CardHeader className="pb-3">
										<div className="flex justify-between items-start">
											<div>
												<Badge variant={plan.active ? "default" : "secondary"} className="mb-2">
													{key.toUpperCase()}
												</Badge>
												<CardTitle className="text-2xl">{plan.name}</CardTitle>
											</div>
											<div className="text-right">
												<span className="text-3xl font-black text-primary">${effectivePrice}</span>
												<span className="text-xs text-muted-foreground block">/month</span>
											</div>
										</div>
										<CardDescription className="line-clamp-2 mt-2">
											{plan.description || "No description provided"}
										</CardDescription>
									</CardHeader>

									<CardContent className="space-y-4 flex-1">
										{/* Badges / Highlights */}
										<div className="flex flex-wrap gap-1.5">
											{isLifetime && (
												<Badge variant="outline" className="bg-amber-500/10 text-amber-500 border-amber-500/30 text-xs">
													Lifetime: ${plan.billing?.lifetime?.price_usd} ({plan.billing?.lifetime?.slot_limit} slots)
												</Badge>
											)}
											{plan.limits?.allow_real_trading ? (
												<Badge variant="outline" className="bg-emerald-500/10 text-emerald-500 border-emerald-500/30 text-xs">
													Live Bots: {plan.limits?.max_live_strategies ?? 0}
												</Badge>
											) : (
												<Badge variant="outline" className="bg-zinc-500/10 text-zinc-400 text-xs">
													Simulation Only
												</Badge>
											)}
										</div>

										{/* Quotas preview */}
										<div className="text-xs bg-muted/40 p-2.5 rounded-md space-y-1">
											<div className="flex justify-between">
												<span className="text-muted-foreground">Backtests / day:</span>
												<span className="font-mono font-medium">
													{plan.quotas?.run_vector_backtest_per_day === -1 ? "Unlimited" : plan.quotas?.run_vector_backtest_per_day ?? 0}
												</span>
											</div>
											<div className="flex justify-between">
												<span className="text-muted-foreground">AI queries / day:</span>
												<span className="font-mono font-medium">
													{plan.quotas?.use_ai_assistant_per_day === -1 ? "Unlimited" : plan.quotas?.use_ai_assistant_per_day ?? 0}
												</span>
											</div>
											<div className="flex justify-between">
												<span className="text-muted-foreground">History depth:</span>
												<span className="font-mono font-medium">
													{plan.limits?.max_backtest_duration_days === -1 ? "Full history" : `${plan.limits?.max_backtest_duration_days ?? 90} days`}
												</span>
											</div>
										</div>

										{/* Features List */}
										<div className="space-y-1">
											<span className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">
												Plan Features ({plan.features?.length || 0}):
											</span>
											<ul className="text-xs space-y-1">
												{(plan.features || []).slice(0, 4).map((f, i) => (
													<li key={i} className="flex items-center gap-1.5 text-muted-foreground">
														<Check className="h-3 w-3 text-emerald-500 flex-shrink-0" />
														<span className="truncate">{f}</span>
													</li>
												))}
												{(plan.features?.length || 0) > 4 && (
													<li className="text-xs text-muted-foreground italic">
														+ {(plan.features?.length || 0) - 4} more items...
													</li>
												)}
											</ul>
										</div>
									</CardContent>

									<div className="p-4 pt-0 flex gap-2">
										<Button
											variant="outline"
											size="sm"
											className="w-full flex items-center justify-center gap-2"
											onClick={() => handleOpenEditPlan(key, plan)}
										>
											<Edit3 className="h-4 w-4" />
											Edit Plan
										</Button>
										{key !== "free" && key !== "standard" && key !== "pro" && (
											<Button
												variant="destructive"
												size="sm"
												onClick={() => handleDeletePlan(key)}
											>
												<Trash2 className="h-4 w-4" />
											</Button>
										)}
									</div>
								</Card>
							);
						})}
					</div>
				</TabsContent>

				{/* TAB 2: Global Billing & Trial */}
				<TabsContent value="billing" className="space-y-6">
					<div className="grid grid-cols-1 md:grid-cols-2 gap-6">
						{/* Billing Mode */}
						<Card>
							<CardHeader>
								<CardTitle className="text-lg flex items-center gap-2">
									<Coins className="h-5 w-5 text-primary" />
									Platform Billing Mode
								</CardTitle>
								<CardDescription>
									Controls whether users see monthly recurring subscriptions or limited lifetime slot reservations during checkout.
								</CardDescription>
							</CardHeader>
							<CardContent className="space-y-4">
								<div className="flex items-center justify-between p-3 border rounded-lg">
									<div>
										<Label className="font-semibold block">Billing Mode</Label>
										<span className="text-xs text-muted-foreground">
											{config.billing?.mode === "lifetime" ? "Limited Lifetime Slots" : "Monthly Subscriptions"}
										</span>
									</div>
									<div className="flex items-center gap-2">
										<Badge variant={config.billing?.mode === "monthly" ? "default" : "outline"} className="cursor-pointer" onClick={() => setConfig({ ...config, billing: { ...config.billing, mode: "monthly" } })}>
											Monthly
										</Badge>
										<Badge variant={config.billing?.mode === "lifetime" ? "default" : "outline"} className="cursor-pointer" onClick={() => setConfig({ ...config, billing: { ...config.billing, mode: "lifetime" } })}>
											Lifetime
										</Badge>
									</div>
								</div>

								<div className="space-y-2">
									<Label>Lifetime Slot Reservation TTL (seconds)</Label>
									<Input
										type="number"
										value={config.billing?.lifetime?.reservation_ttl_seconds ?? 900}
										onChange={(e) =>
											setConfig({
												...config,
												billing: {
													...config.billing,
													mode: config.billing?.mode || "monthly",
													lifetime: {
														reservation_ttl_seconds: parseInt(e.target.value) || 900,
													},
												},
											})
										}
									/>
									<span className="text-xs text-muted-foreground">
										Duration in seconds a lifetime slot is reserved while the user completes cryptocurrency payment.
									</span>
								</div>
							</CardContent>
						</Card>

						{/* Registration Trial */}
						<Card>
							<CardHeader>
								<CardTitle className="text-lg flex items-center gap-2">
									<Award className="h-5 w-5 text-amber-500" />
									Registration Trial Period
								</CardTitle>
								<CardDescription>
									Automatically grant a temporary premium tier to newly registered user accounts.
								</CardDescription>
							</CardHeader>
							<CardContent className="space-y-4">
								<div className="flex items-center justify-between p-3 border rounded-lg">
									<div>
										<Label className="font-semibold block">Enable Trial</Label>
										<span className="text-xs text-muted-foreground">
											Grant trial access upon initial account registration
										</span>
									</div>
									<Switch
										checked={config.registration_trial?.enabled ?? false}
										onCheckedChange={(val) =>
											setConfig({
												...config,
												registration_trial: {
													enabled: val,
													plan: config.registration_trial?.plan || "standard",
													days: config.registration_trial?.days ?? 7,
												},
											})
										}
									/>
								</div>

								<div className="grid grid-cols-2 gap-4">
									<div className="space-y-2">
										<Label>Trial Tier</Label>
										<Input
											value={config.registration_trial?.plan || "standard"}
											onChange={(e) =>
												setConfig({
													...config,
													registration_trial: {
														enabled: config.registration_trial?.enabled ?? false,
														plan: e.target.value,
														days: config.registration_trial?.days ?? 7,
													},
												})
											}
										/>
									</div>
									<div className="space-y-2">
										<Label>Duration (Days)</Label>
										<Input
											type="number"
											value={config.registration_trial?.days ?? 7}
											onChange={(e) =>
												setConfig({
													...config,
													registration_trial: {
														enabled: config.registration_trial?.enabled ?? false,
														plan: config.registration_trial?.plan || "standard",
														days: parseInt(e.target.value) || 0,
													},
												})
											}
										/>
									</div>
								</div>
							</CardContent>
						</Card>
					</div>
					<div className="flex justify-end pt-2">
						<Button onClick={handleSaveAll} disabled={isUpdating} className="flex items-center gap-2">
							<Save className="h-4 w-4" />
							{isUpdating ? "Saving..." : "Save Billing Settings"}
						</Button>
					</div>
				</TabsContent>

				{/* TAB 3: Block Restrictions & Referral / Affiliate */}
				<TabsContent value="restrictions" className="space-y-6">
					<div className="grid grid-cols-1 md:grid-cols-2 gap-6">
						{/* Block Restrictions */}
						<Card>
							<CardHeader>
								<CardTitle className="text-lg flex items-center gap-2">
									<Shield className="h-5 w-5 text-indigo-500" />
									Strategy Builder Block Restrictions
								</CardTitle>
								<CardDescription>
									Specific visual builder nodes restricted to PRO plans or Kline execution mode.
								</CardDescription>
							</CardHeader>
							<CardContent className="space-y-6">
								{/* PRO Only */}
								<div className="space-y-2">
									<Label className="font-semibold block">PRO-Only Blocks:</Label>
									<div className="flex flex-wrap gap-1.5 mb-2">
										{(config.block_restrictions?.pro_only || []).map((blockName, idx) => (
											<Badge key={idx} variant="secondary" className="gap-1 font-mono text-xs">
												{blockName}
												<button
													type="button"
													className="text-muted-foreground hover:text-destructive ml-1"
													onClick={() => {
														const updated = (config.block_restrictions?.pro_only || []).filter((_, i) => i !== idx);
														setConfig({
															...config,
															block_restrictions: {
																...config.block_restrictions,
																pro_only: updated,
															},
														});
													}}
												>
													×
												</button>
											</Badge>
										))}
									</div>
									<div className="flex gap-2">
										<Input
											placeholder="Block identifier (e.g. btc_state_filter)"
											value={newProBlockText}
											onChange={(e) => setNewProBlockText(e.target.value)}
											onKeyDown={(e) => {
												if (e.key === "Enter" && newProBlockText.trim()) {
													e.preventDefault();
													const current = config.block_restrictions?.pro_only || [];
													if (!current.includes(newProBlockText.trim())) {
														setConfig({
															...config,
															block_restrictions: {
																...config.block_restrictions,
																pro_only: [...current, newProBlockText.trim()],
															},
														});
													}
													setNewProBlockText("");
												}
											}}
										/>
										<Button
											type="button"
											variant="outline"
											size="sm"
											onClick={() => {
												if (!newProBlockText.trim()) return;
												const current = config.block_restrictions?.pro_only || [];
												if (!current.includes(newProBlockText.trim())) {
													setConfig({
														...config,
														block_restrictions: {
															...config.block_restrictions,
															pro_only: [...current, newProBlockText.trim()],
														},
													});
												}
												setNewProBlockText("");
											}}
										>
											+
										</Button>
									</div>
								</div>

								{/* Kline Only */}
								<div className="space-y-2">
									<Label className="font-semibold block">Kline-Only Blocks:</Label>
									<div className="flex flex-wrap gap-1.5 mb-2">
										{(config.block_restrictions?.kline_only || []).map((blockName, idx) => (
											<Badge key={idx} variant="secondary" className="gap-1 font-mono text-xs">
												{blockName}
												<button
													type="button"
													className="text-muted-foreground hover:text-destructive ml-1"
													onClick={() => {
														const updated = (config.block_restrictions?.kline_only || []).filter((_, i) => i !== idx);
														setConfig({
															...config,
															block_restrictions: {
																...config.block_restrictions,
																kline_only: updated,
															},
														});
													}}
												>
													×
												</button>
											</Badge>
										))}
									</div>
									<div className="flex gap-2">
										<Input
											placeholder="Block identifier (e.g. tape_condition)"
											value={newKlineBlockText}
											onChange={(e) => setNewKlineBlockText(e.target.value)}
											onKeyDown={(e) => {
												if (e.key === "Enter" && newKlineBlockText.trim()) {
													e.preventDefault();
													const current = config.block_restrictions?.kline_only || [];
													if (!current.includes(newKlineBlockText.trim())) {
														setConfig({
															...config,
															block_restrictions: {
																...config.block_restrictions,
																kline_only: [...current, newKlineBlockText.trim()],
															},
														});
													}
													setNewKlineBlockText("");
												}
											}}
										/>
										<Button
											type="button"
											variant="outline"
											size="sm"
											onClick={() => {
												if (!newKlineBlockText.trim()) return;
												const current = config.block_restrictions?.kline_only || [];
												if (!current.includes(newKlineBlockText.trim())) {
													setConfig({
														...config,
														block_restrictions: {
															...config.block_restrictions,
															kline_only: [...current, newKlineBlockText.trim()],
														},
													});
												}
												setNewKlineBlockText("");
											}}
										>
											+
										</Button>
									</div>
								</div>
							</CardContent>
						</Card>

						{/* Referral & Affiliate Programs */}
						<Card>
							<CardHeader>
								<CardTitle className="text-lg flex items-center gap-2">
									<Award className="h-5 w-5 text-primary" />
									Referral & Affiliate Programs
								</CardTitle>
								<CardDescription>
									Configure invite rewards and affiliate commission terms.
								</CardDescription>
							</CardHeader>
							<CardContent className="space-y-4">
								<div className="space-y-2">
									<Label className="font-semibold">Referrer Reward Bonus</Label>
									<div className="grid grid-cols-2 gap-3">
										<Input
											placeholder="Feature name (run_backtest)"
											value={config.referral_program?.referrer_bonus?.feature_name || "run_backtest"}
											onChange={(e) =>
												setConfig({
													...config,
													referral_program: {
														...config.referral_program,
														referrer_bonus: {
															feature_name: e.target.value,
															quantity: config.referral_program?.referrer_bonus?.quantity ?? 50,
														},
													},
												})
											}
										/>
										<Input
											type="number"
											placeholder="Quantity (+50)"
											value={config.referral_program?.referrer_bonus?.quantity ?? 50}
											onChange={(e) =>
												setConfig({
													...config,
													referral_program: {
														...config.referral_program,
														referrer_bonus: {
															feature_name: config.referral_program?.referrer_bonus?.feature_name || "run_backtest",
															quantity: parseInt(e.target.value) || 0,
														},
													},
												})
											}
										/>
									</div>
								</div>

								<div className="space-y-2">
									<Label className="font-semibold">Referred User Welcome Bonus</Label>
									<div className="grid grid-cols-2 gap-3">
										<Input
											placeholder="Feature name (run_backtest)"
											value={config.referral_program?.referred_user_bonus?.feature_name || "run_backtest"}
											onChange={(e) =>
												setConfig({
													...config,
													referral_program: {
														...config.referral_program,
														referred_user_bonus: {
															feature_name: e.target.value,
															quantity: config.referral_program?.referred_user_bonus?.quantity ?? 25,
														},
													},
												})
											}
										/>
										<Input
											type="number"
											placeholder="Quantity (+25)"
											value={config.referral_program?.referred_user_bonus?.quantity ?? 25}
											onChange={(e) =>
												setConfig({
													...config,
													referral_program: {
														...config.referral_program,
														referred_user_bonus: {
															feature_name: config.referral_program?.referred_user_bonus?.feature_name || "run_backtest",
															quantity: parseInt(e.target.value) || 0,
														},
													},
												})
											}
										/>
									</div>
								</div>

								<div className="border-t pt-4 grid grid-cols-2 gap-3">
									<div className="space-y-1">
										<Label className="font-semibold">Affiliate Commission (0.40 = 40%)</Label>
										<Input
											type="number"
											step="0.05"
											value={config.affiliate_program?.default_commission_rate ?? 0.4}
											onChange={(e) =>
												setConfig({
													...config,
													affiliate_program: {
														...config.affiliate_program,
														default_commission_rate: parseFloat(e.target.value) || 0.4,
														commission_hold_period_days: config.affiliate_program?.commission_hold_period_days ?? 10,
													},
												})
											}
										/>
									</div>
									<div className="space-y-1">
										<Label className="font-semibold">Payout Hold Period (Days)</Label>
										<Input
											type="number"
											value={config.affiliate_program?.commission_hold_period_days ?? 10}
											onChange={(e) =>
												setConfig({
													...config,
													affiliate_program: {
														...config.affiliate_program,
														default_commission_rate: config.affiliate_program?.default_commission_rate ?? 0.4,
														commission_hold_period_days: parseInt(e.target.value) || 10,
													},
												})
											}
										/>
									</div>
								</div>
							</CardContent>
						</Card>
					</div>
					<div className="flex justify-end pt-2">
						<Button onClick={handleSaveAll} disabled={isUpdating} className="flex items-center gap-2">
							<Save className="h-4 w-4" />
							{isUpdating ? "Saving..." : "Save Restrictions"}
						</Button>
					</div>
				</TabsContent>
			</Tabs>

			{/* PLAN EDITOR MODAL */}
			<Dialog open={editingPlanKey !== null} onOpenChange={(open) => !open && setEditingPlanKey(null)}>
				<DialogContent className="max-w-3xl max-h-[90vh] overflow-y-auto">
					<DialogHeader>
						<DialogTitle className="text-xl">
							{isNewPlan ? "Create New Subscription Tier" : `Edit Plan: ${editingPlanData?.name || editingPlanKey}`}
						</DialogTitle>
						<DialogDescription>
							Configure pricing, quotas, operational limits, and permissions for this subscription tier.
						</DialogDescription>
					</DialogHeader>

					{editingPlanData && (
						<div className="space-y-6 py-2">
							{isNewPlan && (
								<div className="space-y-2">
									<Label className="font-semibold">Unique Plan Identifier (Slug):</Label>
									<Input
										placeholder="e.g. starter, ultra, enterprise"
										value={newPlanKeyInput}
										onChange={(e) => setNewPlanKeyInput(e.target.value)}
									/>
								</div>
							)}

							<Tabs defaultValue="general" className="w-full">
								<TabsList className="grid grid-cols-5 w-full">
									<TabsTrigger value="general">General</TabsTrigger>
									<TabsTrigger value="permissions">Permissions</TabsTrigger>
									<TabsTrigger value="quotas">Quotas</TabsTrigger>
									<TabsTrigger value="limits">Limits</TabsTrigger>
									<TabsTrigger value="features">Features & Symbols</TabsTrigger>
								</TabsList>

								{/* GENERAL */}
								<TabsContent value="general" className="space-y-4 pt-4">
									<div className="grid grid-cols-2 gap-4">
										<div className="space-y-2">
											<Label>Display Name</Label>
											<Input
												value={editingPlanData.name}
												onChange={(e) => setEditingPlanData({ ...editingPlanData, name: e.target.value })}
											/>
										</div>
										<div className="space-y-2">
											<Label>Base Price ($/month)</Label>
											<Input
												type="number"
												value={editingPlanData.price_usd}
												onChange={(e) => {
													const val = parseFloat(e.target.value);
													const newPrice = isNaN(val) ? 0 : val;
													setEditingPlanData({
														...editingPlanData,
														price_usd: newPrice,
														billing: {
															...editingPlanData.billing,
															monthly: {
																...(editingPlanData.billing?.monthly || { period_days: 30 }),
																price_usd: newPrice,
															},
														},
													});
												}}
											/>
										</div>

									</div>

									<div className="flex items-center justify-between p-3 border rounded-lg">
										<div>
											<Label className="font-semibold block">Active for Purchase</Label>
											<span className="text-xs text-muted-foreground">Whether users can select and subscribe to this tier</span>
										</div>
										<Switch
											checked={editingPlanData.active}
											onCheckedChange={(val) => setEditingPlanData({ ...editingPlanData, active: val })}
										/>
									</div>

									<div className="space-y-2">
										<Label>Description</Label>
										<Input
											value={editingPlanData.description || ""}
											onChange={(e) => setEditingPlanData({ ...editingPlanData, description: e.target.value })}
										/>
									</div>

									{/* Lifetime option */}
									<div className="border p-3 rounded-lg space-y-3 bg-muted/20">
										<div className="flex items-center justify-between">
											<div>
												<Label className="font-semibold block">Lifetime Offer</Label>
												<span className="text-xs text-muted-foreground">Enable one-time lifetime payment option for this plan</span>
											</div>
											<Switch
												checked={editingPlanData.billing?.lifetime?.enabled ?? false}
												onCheckedChange={(val) =>
													setEditingPlanData({
														...editingPlanData,
														billing: {
															...editingPlanData.billing,
															lifetime: {
																enabled: val,
																price_usd: editingPlanData.billing?.lifetime?.price_usd ?? 199,
																slot_limit: editingPlanData.billing?.lifetime?.slot_limit ?? 50,
															},
														},
													})
												}
											/>
										</div>

										{editingPlanData.billing?.lifetime?.enabled && (
											<div className="grid grid-cols-2 gap-4 pt-2">
												<div className="space-y-1">
													<Label>Lifetime Price ($)</Label>
													<Input
														type="number"
														value={editingPlanData.billing?.lifetime?.price_usd ?? 199}
														onChange={(e) =>
															setEditingPlanData({
																...editingPlanData,
																billing: {
																	...editingPlanData.billing,
																	lifetime: {
																		enabled: true,
																		price_usd: parseFloat(e.target.value) || 0,
																		slot_limit: editingPlanData.billing?.lifetime?.slot_limit ?? 50,
																	},
																},
															})
														}
													/>
												</div>
												<div className="space-y-1">
													<Label>Slot Limit</Label>
													<Input
														type="number"
														value={editingPlanData.billing?.lifetime?.slot_limit ?? 50}
														onChange={(e) =>
															setEditingPlanData({
																...editingPlanData,
																billing: {
																	...editingPlanData.billing,
																	lifetime: {
																		enabled: true,
																		price_usd: editingPlanData.billing?.lifetime?.price_usd ?? 199,
																		slot_limit: parseInt(e.target.value) || 0,
																	},
																},
															})
														}
													/>
												</div>
											</div>
										)}
									</div>
								</TabsContent>

								{/* PERMISSIONS */}
								<TabsContent value="permissions" className="space-y-3 pt-4">
									<span className="text-xs text-muted-foreground block">
										Select capabilities granted to users on this tier:
									</span>
									<div className="grid grid-cols-1 md:grid-cols-2 gap-2.5">
										{ALL_PERMISSIONS.map((perm) => {
											const isChecked = (editingPlanData.permissions || []).includes(perm.id);
											return (
												<div
													key={perm.id}
													className={`flex items-start gap-3 p-2.5 border rounded-lg cursor-pointer transition-all ${isChecked ? "bg-primary/5 border-primary/40" : "bg-card hover:bg-muted/30"}`}
													onClick={() => {
														const current = editingPlanData.permissions || [];
														const updated = isChecked
															? current.filter((p) => p !== perm.id)
															: [...current, perm.id];
														setEditingPlanData({ ...editingPlanData, permissions: updated });
													}}
												>
													<input
														type="checkbox"
														checked={isChecked}
														onChange={() => {}}
														className="mt-1 h-4 w-4 rounded border-gray-300 text-primary"
													/>
													<div>
														<span className="text-sm font-semibold block">{perm.label}</span>
														<span className="text-xs text-muted-foreground">{perm.desc}</span>
													</div>
												</div>
											);
										})}
									</div>
								</TabsContent>

								{/* QUOTAS */}
								<TabsContent value="quotas" className="space-y-3 pt-4">
									<span className="text-xs text-muted-foreground block">
										Specify numerical usage limits (-1 indicates unlimited access):
									</span>
									<div className="grid grid-cols-1 md:grid-cols-2 gap-4">
										{QUOTA_FIELDS.map((q) => (
											<div key={q.key} className="space-y-1.5 p-2.5 border rounded-lg">
												<div className="flex justify-between items-center">
													<Label className="text-xs font-semibold">{q.label}</Label>
													<span className="text-xs text-muted-foreground">{q.unit}</span>
												</div>
												<Input
													type="number"
													value={editingPlanData.quotas?.[q.key] ?? 0}
													onChange={(e) =>
														setEditingPlanData({
															...editingPlanData,
															quotas: {
																...editingPlanData.quotas,
																[q.key]: parseInt(e.target.value) || 0,
															},
														})
													}
												/>
											</div>
										))}
									</div>
								</TabsContent>

								{/* LIMITS */}
								<TabsContent value="limits" className="space-y-4 pt-4">
									<div className="grid grid-cols-1 md:grid-cols-2 gap-4">
										<div className="flex items-center justify-between p-3 border rounded-lg">
											<div>
												<Label className="font-semibold block">Live Real Trading</Label>
												<span className="text-xs text-muted-foreground">Allow deploying live trading bots</span>
											</div>
											<Switch
												checked={Boolean(editingPlanData.limits?.allow_real_trading)}
												onCheckedChange={(val) =>
													setEditingPlanData({
														...editingPlanData,
														limits: { ...editingPlanData.limits, allow_real_trading: val },
													})
												}
											/>
										</div>

										<div className="space-y-1.5 p-3 border rounded-lg">
											<Label className="text-xs font-semibold block">Max Live Strategies</Label>
											<Input
												type="number"
												value={editingPlanData.limits?.max_live_strategies ?? 0}
												onChange={(e) =>
													setEditingPlanData({
														...editingPlanData,
														limits: {
															...editingPlanData.limits,
															max_live_strategies: parseInt(e.target.value) || 0,
														},
													})
												}
											/>
										</div>

										<div className="flex items-center justify-between p-3 border rounded-lg">
											<div>
												<Label className="font-semibold block">Intracandle Triggers</Label>
												<span className="text-xs text-muted-foreground">Sub-bar signal execution</span>
											</div>
											<Switch
												checked={Boolean(editingPlanData.limits?.allow_intracandle_triggers)}
												onCheckedChange={(val) =>
													setEditingPlanData({
														...editingPlanData,
														limits: { ...editingPlanData.limits, allow_intracandle_triggers: val },
													})
												}
											/>
										</div>

										<div className="space-y-1.5 p-3 border rounded-lg">
											<Label className="text-xs font-semibold block">History Depth (-1 = All)</Label>
											<Input
												type="number"
												value={editingPlanData.limits?.max_backtest_duration_days ?? 90}
												onChange={(e) =>
													setEditingPlanData({
														...editingPlanData,
														limits: {
															...editingPlanData.limits,
															max_backtest_duration_days: parseInt(e.target.value) || 0,
														},
													})
												}
											/>
										</div>

										<div className="space-y-1.5 p-3 border rounded-lg">
											<Label className="text-xs font-semibold block">Celery Priority (1-9, 1=highest)</Label>
											<Input
												type="number"
												min={1}
												max={9}
												value={editingPlanData.limits?.celery_task_priority ?? 5}
												onChange={(e) =>
													setEditingPlanData({
														...editingPlanData,
														limits: {
															...editingPlanData.limits,
															celery_task_priority: parseInt(e.target.value) || 5,
														},
													})
												}
											/>
										</div>

										<div className="space-y-1.5 p-3 border rounded-lg">
											<Label className="text-xs font-semibold block">Max Concurrent Tasks</Label>
											<Input
												type="number"
												value={editingPlanData.limits?.max_concurrent_tasks ?? 1}
												onChange={(e) =>
													setEditingPlanData({
														...editingPlanData,
														limits: {
															...editingPlanData.limits,
															max_concurrent_tasks: parseInt(e.target.value) || 1,
														},
													})
												}
											/>
										</div>
									</div>
								</TabsContent>

								{/* FEATURES & SYMBOLS */}
								<TabsContent value="features" className="space-y-6 pt-4">
									{/* Features List */}
									<div className="space-y-2">
										<Label className="font-semibold block">Bullet Points (Features for Pricing Cards):</Label>
										<div className="space-y-1.5 mb-2">
											{(editingPlanData.features || []).map((feat, idx) => (
												<div key={idx} className="flex items-center justify-between p-2 bg-muted/30 border rounded text-xs">
													<span>{feat}</span>
													<button
														type="button"
														className="text-destructive hover:text-destructive/80 font-bold ml-2"
														onClick={() => {
															const updated = (editingPlanData.features || []).filter((_, i) => i !== idx);
															setEditingPlanData({ ...editingPlanData, features: updated });
														}}
													>
														×
													</button>
												</div>
											))}
										</div>
										<div className="flex gap-2">
											<Input
												placeholder="Add feature (e.g. 50 vector backtests per day)"
												value={newFeatureText}
												onChange={(e) => setNewFeatureText(e.target.value)}
												onKeyDown={(e) => {
													if (e.key === "Enter" && newFeatureText.trim()) {
														e.preventDefault();
														setEditingPlanData({
															...editingPlanData,
															features: [...(editingPlanData.features || []), newFeatureText.trim()],
														});
														setNewFeatureText("");
													}
												}}
											/>
											<Button
												type="button"
												variant="outline"
												onClick={() => {
													if (!newFeatureText.trim()) return;
													setEditingPlanData({
														...editingPlanData,
														features: [...(editingPlanData.features || []), newFeatureText.trim()],
													});
													setNewFeatureText("");
												}}
											>
												Add
											</Button>
										</div>
									</div>

									{/* Allowed Symbols */}
									<div className="space-y-2 border-t pt-4">
										<Label className="font-semibold block">Whitelisted Trading Symbols (empty = all symbols):</Label>
										<div className="flex flex-wrap gap-1.5 mb-2 max-h-36 overflow-y-auto p-1 border rounded">
											{(editingPlanData.allowed_symbols || []).map((sym, idx) => (
												<Badge key={idx} variant="secondary" className="font-mono text-xs">
													{sym}
													<button
														type="button"
														className="text-muted-foreground hover:text-destructive ml-1"
														onClick={() => {
															const updated = (editingPlanData.allowed_symbols || []).filter((_, i) => i !== idx);
															setEditingPlanData({ ...editingPlanData, allowed_symbols: updated });
														}}
													>
														×
													</button>
												</Badge>
											))}
											{(editingPlanData.allowed_symbols || []).length === 0 && (
												<span className="text-xs text-muted-foreground p-2">
													All exchange symbols allowed without restrictions.
												</span>
											)}
										</div>
										<div className="flex gap-2">
											<Input
												placeholder="Symbol (e.g. BTCUSDT)"
												value={newSymbolText}
												onChange={(e) => setNewSymbolText(e.target.value.toUpperCase())}
												onKeyDown={(e) => {
													if (e.key === "Enter" && newSymbolText.trim()) {
														e.preventDefault();
														const sym = newSymbolText.trim().toUpperCase();
														const current = editingPlanData.allowed_symbols || [];
														if (!current.includes(sym)) {
															setEditingPlanData({
																...editingPlanData,
																allowed_symbols: [...current, sym],
															});
														}
														setNewSymbolText("");
													}
												}}
											/>
											<Button
												type="button"
												variant="outline"
												onClick={() => {
													if (!newSymbolText.trim()) return;
													const sym = newSymbolText.trim().toUpperCase();
													const current = editingPlanData.allowed_symbols || [];
													if (!current.includes(sym)) {
														setEditingPlanData({
															...editingPlanData,
															allowed_symbols: [...current, sym],
														});
													}
													setNewSymbolText("");
												}}
											>
												Add
											</Button>
										</div>
									</div>
								</TabsContent>
							</Tabs>
						</div>
					)}

					<DialogFooter>
						<Button variant="outline" onClick={() => setEditingPlanKey(null)}>
							Cancel
						</Button>
						<Button onClick={handleSavePlanDialog} disabled={isUpdating} className="flex items-center gap-2">
							<Save className="h-4 w-4" />
							{isUpdating ? "Saving..." : "Save Plan"}
						</Button>
					</DialogFooter>
				</DialogContent>
			</Dialog>
		</div>
	);
};

export default AdminPlansPage;
