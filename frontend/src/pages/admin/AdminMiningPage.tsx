import React, { useState, useEffect } from "react";
import { Pickaxe, Settings, Coins, RefreshCw, AlertCircle, Server, Globe, ShieldCheck, Check, ChevronDown, ChevronUp, ChevronLeft, ChevronRight, KeyRound, CalendarIcon, UploadCloud, FileSpreadsheet, CheckCircle2 } from "lucide-react";
import { useTranslation } from "react-i18next";
import { format, startOfToday } from "date-fns";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { Label } from "@/components/ui/label";
import { Calendar } from "@/components/ui/calendar";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { NodeWalletModal } from "@/components/mining/NodeWalletModal";
import {
	Table,
	TableBody,
	TableCell,
	TableHead,
	TableHeader,
	TableRow,
} from "@/components/ui/table";
import { useToast } from "@/components/ui/use-toast";
import {
	useGetMiningStatus,
	useGetNodeMiningConfig,
	useUpdateNodeMiningConfig,
	useSystemStatus,
	useGetHubMiningConfig,
	useUpdateHubMiningConfig,
	useTriggerMiningEpoch,
	useImportBybitXlsx,
	type ImportBybitXlsxResult,
} from "@/lib/api";

const PRESET_EXCHANGES = [
	{ id: "weex_futures", name: "WEEX Futures" },
	{ id: "weex_spot", name: "WEEX Spot" },
	{ id: "bybit_futures", name: "Bybit Futures" },
	{ id: "bybit_spot", name: "Bybit Spot" },
	{ id: "binance_futures", name: "Binance Futures" },
	{ id: "binance_spot", name: "Binance Spot" },
	{ id: "okx_futures", name: "OKX Futures" },
	{ id: "okx_spot", name: "OKX Spot" },
];

const AdminMiningPage: React.FC = () => {
	const { toast } = useToast();
	const { t } = useTranslation("mining");
	const [isWalletModalOpen, setIsWalletModalOpen] = useState(false);

	// Default the epoch date picker to T-2 (2 days ago in UTC), matching the settlement schedule.
	const [epochDate, setEpochDate] = useState<Date>(() => {
		const d = new Date();
		d.setDate(d.getDate() - 2);
		return d;
	});

	// Check if this server is running in Central Hub mode
	const { data: systemStatus } = useSystemStatus();
	const isCentralHub = Boolean(systemStatus?.isCentralHub);

	// Collapsible state for Central Hub configuration card (default: collapsed)
	const [isHubControlsOpen, setIsHubControlsOpen] = useState(false);

	// Table Pagination state
	const [tablePage, setTablePage] = useState(1);
	const ITEMS_PER_PAGE = 10;

	// React Query hooks for Node config
	const { data: statusData, isLoading: isLoadingStatus, refetch: refetchStatus } = useGetMiningStatus();
	const { data: configData, isLoading: isLoadingConfig, refetch: refetchConfig } = useGetNodeMiningConfig();
	const { mutate: updateConfig, isPending: isUpdating } = useUpdateNodeMiningConfig();

	// React Query hooks for Central Hub config (only active if isCentralHub)
	const { data: hubConfig, isLoading: isLoadingHubConfig, refetch: refetchHubConfig } = useGetHubMiningConfig(isCentralHub);
	const { mutate: updateHubConfig, isPending: isUpdatingHub } = useUpdateHubMiningConfig();
	const { mutate: processEpoch, isPending: isProcessingEpoch } = useTriggerMiningEpoch();

	// Bybit XLSX Import state
	const [bybitFile, setBybitFile] = useState<File | null>(null);
	const [isDryRun, setIsDryRun] = useState(false);
	const [importResult, setImportResult] = useState<ImportBybitXlsxResult | null>(null);
	const { mutate: importBybitXlsx, isPending: isImportingXlsx } = useImportBybitXlsx();

	const handleBybitFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
		if (e.target.files && e.target.files[0]) {
			setBybitFile(e.target.files[0]);
			setImportResult(null);
		}
	};

	const handleImportBybit = () => {
		if (!bybitFile) {
			toast({
				title: "No file selected",
				description: "Please select an .xlsx file downloaded from Bybit Broker Dashboard.",
				variant: "destructive",
			});
			return;
		}
		importBybitXlsx(
			{ file: bybitFile, dryRun: isDryRun },
			{
				onSuccess: (res: any) => {
					const data: ImportBybitXlsxResult = res?.data || res;
					setImportResult(data);
					toast({
						title: isDryRun ? "Dry Run Completed" : "Bybit Import Successful",
						description: data?.message || `Processed ${data?.stats?.verified_reports || 0} verified reports.`,
					});
					refetchStatus();
				},
				onError: (err: any) => {
					toast({
						title: "Bybit Import Failed",
						description: err.message || "Failed to parse or apply Bybit XLSX file.",
						variant: "destructive",
					});
				},
			}
		);
	};

	// Local state for local node configuration form
	const [globalMiningEnabled, setGlobalMiningEnabled] = useState(true);
	const [userRewardShare, setUserRewardShare] = useState(0);

	// Local state for Central Hub configuration form
	const [hubMiningEnabled, setHubMiningEnabled] = useState(false);
	const [eligibleExchanges, setEligibleExchanges] = useState<string[]>([]);
	const [dailyEmission, setDailyEmission] = useState(547945.21);
	const [minTradeDuration, setMinTradeDuration] = useState(30);
	const [minPriceMovement, setMinPriceMovement] = useState(0.15);
	const [referralBoost, setReferralBoost] = useState(0.10);
	const [rebateRates, setRebateRates] = useState<Record<string, number>>({
		weex_futures: 0.60,
		weex_spot: 0.45,
		weex: 0.60,
		bybit_futures: 0.40,
		bybit_spot: 0.30,
		binance_futures: 0.25,
		binance_spot: 0.20,
	});
	const [customExchange, setCustomExchange] = useState("");

	// Sync local node state when configData loads
	useEffect(() => {
		if (configData) {
			setGlobalMiningEnabled(configData.isGlobalMiningEnabled);
			setUserRewardShare(configData.userRewardSharePercent);
		}
	}, [configData]);

	// Sync Central Hub state when hubConfig loads
	useEffect(() => {
		if (hubConfig) {
			setHubMiningEnabled(hubConfig.isMiningEnabled ?? false);
			setEligibleExchanges(hubConfig.eligibleExchanges || []);
			if (hubConfig.dailyEmissionBase !== undefined) {
				setDailyEmission(hubConfig.dailyEmissionBase);
			}
			if (hubConfig.minTradeDurationSec !== undefined) {
				setMinTradeDuration(hubConfig.minTradeDurationSec);
			}
			if (hubConfig.minPriceMovementPercent !== undefined) {
				setMinPriceMovement(hubConfig.minPriceMovementPercent);
			}
			if (hubConfig.referralMiningBoost !== undefined) {
				setReferralBoost(hubConfig.referralMiningBoost);
			}
			if (hubConfig.rebateRates) {
				setRebateRates((prev) => ({ ...prev, ...hubConfig.rebateRates }));
			}
		}
	}, [hubConfig]);

	const handleSaveConfig = () => {
		updateConfig(
			{
				isGlobalMiningEnabled: globalMiningEnabled,
				userRewardSharePercent: userRewardShare,
			},
			{
				onSuccess: () => {
					toast({
						title: "Configuration Saved",
						description: "Node mining configuration has been successfully updated.",
					});
					refetchConfig();
					refetchStatus();
				},
				onError: (error: any) => {
					toast({
						title: "Failed to Update",
						description: error.message || "An error occurred while updating settings.",
						variant: "destructive",
					});
				},
			}
		);
	};

	const handleSaveHubConfig = () => {
		updateHubConfig(
			{
				isMiningEnabled: hubMiningEnabled,
				eligibleExchanges,
				dailyEmissionBase: dailyEmission,
				minTradeDurationSec: minTradeDuration,
				minPriceMovementPercent: minPriceMovement,
				referralMiningBoost: referralBoost,
				rebateRates,
			},
			{
				onSuccess: () => {
					toast({
						title: "Central Hub Settings Saved",
						description: "Global federation mining rules updated successfully.",
					});
					refetchHubConfig();
					refetchStatus();
				},
				onError: (error: any) => {
					toast({
						title: "Failed to Update Hub",
						description: error.message || "An error occurred while updating Hub settings.",
						variant: "destructive",
					});
				},
			}
		);
	};

	const handleProcessEpoch = () => {
		processEpoch(format(epochDate, "yyyy-MM-dd"), {
			onSuccess: (data) => {
				toast({
					title: t("epochProcessedTitle"),
					description: data?.message || t("epochProcessedDesc"),
				});
				refetchStatus();
			},
			onError: (error: any) => {
				toast({
					title: t("epochProcessingFailedTitle"),
					description: error.message || t("epochProcessingFailedDesc"),
					variant: "destructive",
				});
			},
		});
	};

	const toggleExchange = (id: string) => {
		if (eligibleExchanges.includes(id)) {
			setEligibleExchanges(eligibleExchanges.filter((item) => item !== id));
		} else {
			setEligibleExchanges([...eligibleExchanges, id]);
		}
	};

	const handleAddCustomExchange = () => {
		const trimmed = customExchange.trim().toLowerCase();
		if (trimmed && !eligibleExchanges.includes(trimmed)) {
			setEligibleExchanges([...eligibleExchanges, trimmed]);
			setCustomExchange("");
		}
	};

	const handleRefresh = async () => {
		const promises: Promise<any>[] = [refetchStatus(), refetchConfig()];
		if (isCentralHub) promises.push(refetchHubConfig());
		await Promise.all(promises);
		toast({
			title: "Data Refreshed",
			description: "Latest mining metrics have been loaded.",
		});
	};

	// Parse user metrics from stats dict
	const userMetrics = (statusData?.stats as any)?.userMetrics || [];
	const totalNodeMined = (statusData?.stats as any)?.serverTotalMined || statusData?.totalMined || 0.0;
	const operatorFeeBalance = (statusData?.stats as any)?.operatorFeeBalance || 0.0;
	const totalNodeVol = (statusData?.stats as any)?.serverTotalVolume || statusData?.userTradeVolume || 0.0;
	const hubStatus = statusData?.registeredOnHub ? "Connected" : "Disconnected";

	const totalTablePages = Math.ceil(userMetrics.length / ITEMS_PER_PAGE) || 1;
	const paginatedUserMetrics = userMetrics.slice(
		(tablePage - 1) * ITEMS_PER_PAGE,
		tablePage * ITEMS_PER_PAGE
	);

	return (
		<div className="space-y-6">
			<div className="flex justify-between items-center">
				<div>
					<h1 className="text-3xl font-bold mb-2 flex items-center gap-2">
						<Pickaxe className="h-8 w-8 text-primary" />
						Node Trade Mining
					</h1>
					<p className="text-muted-foreground">
						Manage global mining participation, reward sharing policy, and track user contributions.
					</p>
				</div>
				<div className="flex items-center gap-2">
					<Button variant="outline" size="sm" onClick={() => setIsWalletModalOpen(true)} className="flex items-center gap-2 text-primary border-primary/30 bg-primary/5 hover:bg-primary/10">
						<KeyRound className="h-4 w-4" />
						Node Admin Wallet
					</Button>
					<Button variant="outline" size="sm" onClick={handleRefresh} className="flex items-center gap-2">
						<RefreshCw className="h-4 w-4" />
						Refresh Metrics
					</Button>
				</div>
			</div>

			{/* Central Hub Configuration Card (Rendered ONLY if IS_CENTRAL_HUB=true) */}
			{isCentralHub && (
				<Card className="border-2 border-primary/40 bg-gradient-to-r from-primary/5 via-background to-purple-500/5 shadow-xl">
					<CardHeader
						className="cursor-pointer select-none"
						onClick={() => setIsHubControlsOpen(!isHubControlsOpen)}
					>
						<div className="flex items-center justify-between">
							<CardTitle className="flex items-center gap-2 text-xl font-black">
								<Globe className="h-6 w-6 text-primary" />
								Central Federation Hub Mining Controls
								<Badge variant="default" className="bg-primary font-bold uppercase tracking-wider text-[10px]">
									IS_CENTRAL_HUB = TRUE
								</Badge>
							</CardTitle>
							<Button variant="ghost" size="sm" className="h-8 w-8 p-0">
								{isHubControlsOpen ? <ChevronUp className="h-5 w-5 text-primary" /> : <ChevronDown className="h-5 w-5 text-primary" />}
							</Button>
						</div>
						<CardDescription>
							Global network emission rate, anti-abuse security rules, and exchange whitelist for all nodes.
						</CardDescription>
					</CardHeader>
					{isHubControlsOpen && (
						<CardContent className="space-y-6">
							{isLoadingHubConfig ? (
								<div className="space-y-4">
									<Skeleton className="h-10 w-full" />
									<Skeleton className="h-20 w-full" />
								</div>
							) : (
								<>
									{/* Global Master Switch */}
									<div className="flex items-center justify-between p-4 border rounded-xl bg-card/60 backdrop-blur-sm">
										<div>
											<p className="font-bold text-sm flex items-center gap-2">
												<ShieldCheck className="h-4 w-4 text-emerald-500" />
												Global Federation Mining Enabled
											</p>
											<p className="text-xs text-muted-foreground mt-0.5">
												Master switch for trade mining across all connected nodes in the federation network.
											</p>
										</div>
										<input
											type="checkbox"
											checked={hubMiningEnabled}
											onChange={(e) => setHubMiningEnabled(e.target.checked)}
											className="h-6 w-6 rounded border-gray-300 text-primary focus:ring-primary cursor-pointer"
										/>
									</div>

									{/* Parameters Grid */}
									<div className="grid grid-cols-1 md:grid-cols-3 gap-4">
										<div className="space-y-2 p-4 border rounded-xl bg-card/40">
											<label className="text-xs font-bold text-muted-foreground uppercase tracking-wider block">
												Daily Emission Base ($DEPTH)
											</label>
											<Input
												type="number"
												value={dailyEmission}
												onChange={(e) => setDailyEmission(Number(e.target.value))}
												className="font-mono font-bold"
											/>
											<span className="text-[10px] text-muted-foreground">Total daily emission pool across network</span>
										</div>

										<div className="space-y-2 p-4 border rounded-xl bg-card/40">
											<label className="text-xs font-bold text-muted-foreground uppercase tracking-wider block">
												Min Trade Duration (sec)
											</label>
											<Input
												type="number"
												value={minTradeDuration}
												onChange={(e) => setMinTradeDuration(Number(e.target.value))}
												className="font-mono font-bold"
											/>
											<span className="text-[10px] text-muted-foreground">Anti-wash trading minimum hold time</span>
										</div>

										<div className="space-y-2 p-4 border rounded-xl bg-card/40">
											<label className="text-xs font-bold text-muted-foreground uppercase tracking-wider block">
												Min Price Movement (%)
											</label>
											<Input
												type="number"
												step="0.01"
												min="0"
												value={minPriceMovement}
												onChange={(e) => setMinPriceMovement(Number(e.target.value))}
												className="font-mono font-bold"
											/>
											<span className="text-[10px] text-muted-foreground">Anti-instant-exit: minimum |entry→exit| move; re-checked against real exchange prices</span>
										</div>

										<div className="space-y-2 p-4 border rounded-xl bg-card/40">
											<label className="text-xs font-bold text-muted-foreground uppercase tracking-wider block">
												Referral Mining Boost
											</label>
											<Input
												type="number"
												step="0.01"
												value={referralBoost}
												onChange={(e) => setReferralBoost(Number(e.target.value))}
												className="font-mono font-bold"
											/>
											<span className="text-[10px] text-muted-foreground">e.g. 0.10 = +10% daily boost for referrals</span>
										</div>
									</div>

									{/* Eligible Exchanges Selector */}
									<div className="space-y-3 p-4 border rounded-xl bg-card/40">
										<div>
											<p className="font-bold text-sm">Eligible Exchanges & Markets</p>
											<p className="text-xs text-muted-foreground">
												Select exchanges and markets where trade volume qualifies for $DEPTH mining rewards.
											</p>
										</div>

										<div className="grid grid-cols-2 sm:grid-cols-4 gap-2.5 pt-2">
											{PRESET_EXCHANGES.map((ex) => {
												const isSelected = eligibleExchanges.includes(ex.id);
												return (
													<button
														key={ex.id}
														type="button"
														onClick={() => toggleExchange(ex.id)}
														className={`p-2.5 rounded-lg border text-xs font-semibold flex items-center justify-between transition-all ${
															isSelected
																? "bg-primary/10 border-primary text-primary shadow-sm"
																: "bg-card/50 border-border text-muted-foreground hover:border-primary/40"
														}`}
													>
														<span>{ex.name}</span>
														{isSelected && <Check className="h-4 w-4 shrink-0 text-primary" />}
													</button>
												);
											})}
										</div>

										{/* Custom Exchange Input */}
										<div className="flex gap-2 pt-2">
											<Input
												placeholder="Add custom exchange ID (e.g., bitget_futures)..."
												value={customExchange}
												onChange={(e) => setCustomExchange(e.target.value)}
												className="text-xs font-mono flex-1 bg-background/50"
											/>
											<Button type="button" variant="secondary" size="sm" onClick={handleAddCustomExchange}>
												Add
											</Button>
										</div>

										{/* Current Whitelisted Exchanges Chips */}
										<div className="flex flex-wrap gap-1.5 pt-2">
											{eligibleExchanges.map((ex) => (
												<Badge
													key={ex}
													variant="outline"
													className="font-mono text-[10px] bg-primary/5 text-primary border-primary/30 flex items-center gap-1 cursor-pointer hover:bg-destructive/10 hover:text-destructive hover:border-destructive/30"
													onClick={() => toggleExchange(ex)}
												>
													{ex} &times;
												</Badge>
											))}
										</div>
									</div>

									{/* Exchange Specific Rebate Rates */}
									{eligibleExchanges.length > 0 && (
										<div className="space-y-3 p-4 border rounded-xl bg-card/40">
											<div>
												<p className="font-bold text-sm">Exchange Rebate Rates (% Cashback / Affiliate Share)</p>
												<p className="text-xs text-muted-foreground">
													Configure customized affiliate rebate rates per exchange to accurately calculate estimated USDT revenue.
												</p>
											</div>

											<div className="grid grid-cols-1 md:grid-cols-2 gap-3 pt-2">
												{eligibleExchanges.map((ex) => {
													const currentRate = rebateRates[ex] ?? 0.60;
													return (
														<div key={ex} className="flex items-center justify-between p-2.5 border rounded-lg bg-background/50 text-xs">
															<span className="font-mono font-semibold">{ex}</span>
															<div className="flex items-center gap-2">
																<Input
																	type="number"
																	step="0.05"
																	min="0"
																	max="1"
																	value={currentRate}
																	onChange={(e) =>
																		setRebateRates({
																			...rebateRates,
																			[ex]: parseFloat(e.target.value) || 0,
																		})
																	}
																	className="w-20 h-8 text-xs font-mono font-bold text-right"
																/>
																<span className="font-bold text-primary w-12 text-right">
																	{(currentRate * 100).toFixed(0)}%
																</span>
															</div>
														</div>
													);
												})}
											</div>
										</div>
									)}

									<Button
										onClick={handleSaveHubConfig}
										disabled={isUpdatingHub}
										className="w-full font-bold bg-primary hover:bg-primary/90 text-primary-foreground py-6 text-base"
									>
										{isUpdatingHub ? "Saving Central Hub Rules..." : "Save Central Hub Global Configuration"}
									</Button>

								<div className="border-t border-border/40 pt-4">
									<p className="font-bold text-sm mb-1 flex items-center gap-2">
										<RefreshCw className="h-4 w-4 text-amber-500" />
										{t("manualEpochProcessing")}
									</p>
									<p className="text-xs text-muted-foreground mb-3">
										{t("manualEpochDesc")}
									</p>
									<div className="mb-3">
										<Label
											htmlFor="epoch-date-picker"
											className="text-xs text-muted-foreground mb-1 block"
										>
											{t("epochDateLabel")}
										</Label>
										<Popover>
											<PopoverTrigger asChild>
												<Button
													id="epoch-date-picker"
													variant="outline"
													className="w-full justify-start text-left font-normal h-9 text-sm"
												>
													<CalendarIcon className="mr-2 h-4 w-4" />
													{format(epochDate, "yyyy-MM-dd")}
												</Button>
											</PopoverTrigger>
											<PopoverContent className="w-auto p-0" align="start">
												<Calendar
													initialFocus
													mode="single"
													defaultMonth={epochDate}
													selected={epochDate}
													onSelect={(d) => {
														if (d) setEpochDate(d);
													}}
													disabled={(d: Date) => d >= startOfToday()}
												/>
											</PopoverContent>
										</Popover>
										<p className="text-[11px] text-muted-foreground mt-1.5">
											{t("epochDateHint")}
										</p>
									</div>
									<Button
										onClick={handleProcessEpoch}
										disabled={isProcessingEpoch}
										variant="outline"
										className="w-full font-semibold border-amber-500/50 text-amber-600 hover:bg-amber-500/10"
									>
										{isProcessingEpoch ? (
											<span className="flex items-center gap-2">
												<RefreshCw className="h-4 w-4 animate-spin" />
												{t("processingEpoch")}
											</span>
										) : (
											<span className="flex items-center gap-2">
												<RefreshCw className="h-4 w-4" />
												{t("runEpochNow")}
											</span>
										)}
									</Button>
								</div>

								{/* Bybit XLSX Broker Import (Central Hub only) */}
								<div className="border-t border-border/40 pt-4">
									<p className="font-bold text-sm mb-1 flex items-center gap-2">
										<FileSpreadsheet className="h-4 w-4 text-blue-500" />
										Bybit Broker XLSX Import
									</p>
									<p className="text-xs text-muted-foreground mb-3">
										Upload official Bybit Broker Transaction History export (<code className="text-[11px] bg-muted px-1 rounded">.xlsx</code>) to directly verify trading volumes and distribute exact USDT broker rebates.
									</p>

									<div className="space-y-3 p-3.5 border rounded-xl bg-card/60">
										<div className="flex flex-col gap-2">
											<Label htmlFor="bybit-xlsx-file" className="text-xs font-semibold text-muted-foreground">
												Select .xlsx file from Bybit Broker Dashboard
											</Label>
											<Input
												id="bybit-xlsx-file"
												type="file"
												accept=".xlsx,.csv"
												onChange={handleBybitFileChange}
												className="text-xs cursor-pointer file:cursor-pointer file:font-semibold file:text-xs file:bg-primary/10 file:text-primary file:border-0 file:rounded-md file:mr-2 file:px-2 file:py-1"
											/>
										</div>

										<div className="flex items-center justify-between pt-1">
											<label className="flex items-center gap-2 text-xs text-muted-foreground cursor-pointer select-none">
												<input
													type="checkbox"
													checked={isDryRun}
													onChange={(e) => setIsDryRun(e.target.checked)}
													className="h-4 w-4 rounded border-gray-300 text-primary focus:ring-primary"
												/>
												<span>Dry Run (simulate without committing)</span>
											</label>

											<Button
												onClick={handleImportBybit}
												disabled={!bybitFile || isImportingXlsx}
												size="sm"
												className="font-semibold bg-blue-600 hover:bg-blue-700 text-white"
											>
												{isImportingXlsx ? (
													<span className="flex items-center gap-2">
														<RefreshCw className="h-3.5 w-3.5 animate-spin" />
														Importing...
													</span>
												) : (
													<span className="flex items-center gap-2">
														<UploadCloud className="h-3.5 w-3.5" />
														Upload & Apply
													</span>
												)}
											</Button>
										</div>

										{/* Import Result Box */}
										{importResult && (
											<div className="mt-3 p-3 rounded-lg border bg-blue-950/20 border-blue-800/40 text-xs space-y-1.5">
												<div className="flex items-center gap-1.5 font-bold text-blue-400">
													<CheckCircle2 className="h-4 w-4 text-emerald-400" />
													<span>{importResult.message}</span>
												</div>
												<div className="grid grid-cols-2 md:grid-cols-4 gap-2 pt-1 font-mono text-[11px]">
													<div className="p-1.5 rounded bg-background/60">
														<span className="text-muted-foreground block text-[10px]">Verified Trades</span>
														<span className="font-bold text-emerald-400">{importResult.stats.verified_reports}</span>
													</div>
													<div className="p-1.5 rounded bg-background/60">
														<span className="text-muted-foreground block text-[10px]">Rebate Assigned</span>
														<span className="font-bold text-primary">${importResult.stats.total_rebate_distributed.toFixed(4)} USDT</span>
													</div>
													<div className="p-1.5 rounded bg-background/60">
														<span className="text-muted-foreground block text-[10px]">Matched Nodes</span>
														<span className="font-bold">{importResult.stats.matched_nodes}</span>
													</div>
													<div className="p-1.5 rounded bg-background/60">
														<span className="text-muted-foreground block text-[10px]">Gated / Skipped</span>
														<span className="font-bold text-muted-foreground">{importResult.stats.skipped_gated_reports}</span>
													</div>
												</div>
											</div>
										)}
									</div>
								</div>
								</>
							)}
						</CardContent>
					)}
				</Card>
			)}

			<div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
				{/* Global Configuration Card */}
				<Card className="lg:col-span-1">
					<CardHeader>
						<CardTitle className="flex items-center gap-2">
							<Settings className="h-5 w-5 text-primary" />
							Mining Settings
						</CardTitle>
						<CardDescription>Adjust node-wide parameters</CardDescription>
					</CardHeader>
					<CardContent className="space-y-6">
						{isLoadingConfig ? (
							<div className="space-y-4">
								<Skeleton className="h-10 w-full" />
								<Skeleton className="h-14 w-full" />
								<Skeleton className="h-10 w-24" />
							</div>
						) : (
							<>
								{/* Global Toggle */}
								<div className="flex items-center justify-between p-4 border rounded-lg bg-card">
									<div>
										<p className="font-semibold text-sm">Enable Mining</p>
										<p className="text-xs text-muted-foreground">
											Toggle trade telemetry collection and pool mining node-wide.
										</p>
									</div>
									<input
										type="checkbox"
										checked={globalMiningEnabled}
										onChange={(e) => setGlobalMiningEnabled(e.target.checked)}
										className="h-5 w-5 rounded border-gray-300 text-primary focus:ring-primary"
									/>
								</div>

								{/* Share Slider */}
								<div className="space-y-3 p-4 border rounded-lg bg-card">
									<div className="flex justify-between items-center">
										<div>
											<p className="font-semibold text-sm">User Share</p>
											<p className="text-xs text-muted-foreground font-normal">
												Percentage of USDT reward distributed to users.
											</p>
										</div>
										<span className="text-lg font-bold text-primary">{userRewardShare}%</span>
									</div>
									<input
										type="range"
										min="0"
										max="100"
										value={userRewardShare}
										onChange={(e) => setUserRewardShare(Number(e.target.value))}
										className="w-full h-2 bg-muted rounded-lg appearance-none cursor-pointer accent-primary"
									/>
									<div className="flex justify-between text-xs text-muted-foreground">
										<span>0% (Admin Only)</span>
										<span>50%</span>
										<span>100% (Users Only)</span>
									</div>
								</div>

								<Button onClick={handleSaveConfig} className="w-full" disabled={isUpdating}>
									{isUpdating ? "Saving..." : "Save Settings"}
								</Button>
							</>
						)}
					</CardContent>
				</Card>

				{/* Overarching Node Status Card */}
				<Card className="lg:col-span-2">
					<CardHeader>
						<CardTitle className="flex items-center gap-2">
							<Coins className="h-5 w-5 text-primary" />
							Node Status & Pool Data
						</CardTitle>
						<CardDescription>Metrics verified by Central Hub</CardDescription>
					</CardHeader>
					<CardContent className="space-y-6">
						{isLoadingStatus ? (
							<div className="grid grid-cols-2 gap-4">
								<Skeleton className="h-24 w-full" />
								<Skeleton className="h-24 w-full" />
								<Skeleton className="h-24 w-full" />
								<Skeleton className="h-24 w-full" />
							</div>
						) : (
							<div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
								<div className="p-4 border rounded-lg bg-card">
									<p className="text-xs text-muted-foreground">Hub Connectivity</p>
									<p className={`text-xl font-bold ${statusData?.registeredOnHub ? "text-green-600" : "text-amber-500"}`}>
										{hubStatus}
									</p>
									<p className="text-[10px] text-muted-foreground break-all mt-1">
										UUID: {statusData?.nodeUuid || "N/A"}
									</p>
								</div>
								<div className="p-4 border rounded-lg bg-card">
									<p className="text-xs text-muted-foreground">Server Total Mined</p>
									<p className="text-xl font-bold text-primary">
										{totalNodeMined.toFixed(4)} $DEPTH
									</p>
									<p className="text-xs text-muted-foreground mt-1">
										All-time earnings across all nodes on this server.
									</p>
								</div>
								<div className="p-4 border rounded-lg bg-card">
									<p className="text-xs text-muted-foreground">Operator Fee Collected ({100 - userRewardShare}%)</p>
									<p className="text-xl font-bold text-amber-500">
										{operatorFeeBalance.toFixed(4)} $DEPTH
									</p>
									<p className="text-xs text-muted-foreground mt-1">
										{100 - userRewardShare}% retained from node earnings.
									</p>
								</div>
								<div className="p-4 border rounded-lg bg-card">
									<p className="text-xs text-muted-foreground">Total Node Volume</p>
									<p className="text-xl font-bold text-blue-500">
										{totalNodeVol.toFixed(2)} USDT
									</p>
									<p className="text-xs text-muted-foreground mt-1">
										Aggregated trade volume across all users.
									</p>
								</div>
								<div className="p-4 border rounded-lg bg-card">
									<p className="text-xs text-muted-foreground">Referral Link / Code</p>
									<p className="text-xl font-bold">
										{statusData?.nodeReferralCode || "No referral code"}
									</p>
									<p className="text-xs text-muted-foreground mt-1">
										Invite other nodes to earn 10% boost.
									</p>
								</div>
							</div>
						)}
					</CardContent>
				</Card>
			</div>

			{/* User Leaderboard & Contributions */}
			<Card>
				<CardHeader>
					<CardTitle>{isCentralHub ? "Server Nodes & Balances" : "User Contributions & Balances"}</CardTitle>
					<CardDescription>
						{isCentralHub
							? "All nodes connected to this server and their generated share."
							: "Local users trading on this node and their generated share."}
					</CardDescription>
				</CardHeader>
				<CardContent>
					{isLoadingStatus ? (
						<Skeleton className="h-48 w-full" />
					) : userMetrics.length > 0 ? (
						<>
							<Table>
								<TableHeader>
									<TableRow>
										<TableHead>User ID</TableHead>
										<TableHead>Username</TableHead>
										<TableHead>Volume (USDT)</TableHead>
										<TableHead>Estimated Rebate (USDT)</TableHead>
										<TableHead>User Earned Share ({userRewardShare}%)</TableHead>
										<TableHead>Node Admin Fee ({100 - userRewardShare}%)</TableHead>
									</TableRow>
								</TableHeader>
								<TableBody>
									{paginatedUserMetrics.map((user: any) => {
										const volume = Number(user.tradeVolume) || 0.0;
										const rebate = Number(user.estimatedRebate) || 0.0;
										
										// Calculate user's proportional share of the total node/hub mined tokens
										const totalRebate = userMetrics.reduce((sum: number, u: any) => sum + (Number(u.estimatedRebate) || 0), 0);
										const userTokens = totalRebate > 0 ? (rebate / totalRebate) * totalNodeMined : 0.0;
										
										const shareEarned = userTokens * (userRewardShare / 100.0);
										const adminShareEarned = userTokens * ((100.0 - userRewardShare) / 100.0);
										return (
											<TableRow key={user.userId}>
												<TableCell>{user.userId}</TableCell>
												<TableCell className="font-semibold">{user.username}</TableCell>
												<TableCell>{volume.toFixed(2)} USDT</TableCell>
												<TableCell>{rebate.toFixed(4)} USDT</TableCell>
												<TableCell className="font-bold text-green-600">
													{shareEarned.toFixed(2)} $DEPTH
												</TableCell>
												<TableCell className="font-bold text-amber-500">
													{adminShareEarned.toFixed(2)} $DEPTH
												</TableCell>
											</TableRow>
										);
									})}
								</TableBody>
							</Table>

							{userMetrics.length > ITEMS_PER_PAGE && (
								<div className="flex items-center justify-between pt-4 border-t mt-4 text-xs">
									<span className="text-muted-foreground">
										Showing {(tablePage - 1) * ITEMS_PER_PAGE + 1} to{" "}
										{Math.min(tablePage * ITEMS_PER_PAGE, userMetrics.length)} of{" "}
										{userMetrics.length} users
									</span>
									<div className="flex items-center gap-2">
										<Button
											variant="outline"
											size="sm"
											disabled={tablePage <= 1}
											onClick={() => setTablePage((p) => p - 1)}
											className="h-8 text-xs gap-1"
										>
											<ChevronLeft className="h-3.5 w-3.5" />
											Previous
										</Button>
										<span className="font-semibold text-muted-foreground">
											Page {tablePage} of {totalTablePages}
										</span>
										<Button
											variant="outline"
											size="sm"
											disabled={tablePage >= totalTablePages}
											onClick={() => setTablePage((p) => p + 1)}
											className="h-8 text-xs gap-1"
										>
											Next
											<ChevronRight className="h-3.5 w-3.5" />
										</Button>
									</div>
								</div>
							)}
						</>
					) : (
						<div className="flex flex-col items-center justify-center py-12 text-center text-muted-foreground">
							<AlertCircle className="h-10 w-10 text-muted-foreground/60 mb-2" />
							<p className="font-medium text-sm">No Active User Telemetry Recorded</p>
							<p className="text-xs max-w-sm mt-1">
								Once users enable telemetry and start executing live or paper trades, their statistics will accumulate here.
							</p>
						</div>
					)}
				</CardContent>
			</Card>

			<NodeWalletModal
				isOpen={isWalletModalOpen}
				onClose={() => setIsWalletModalOpen(false)}
				onWalletActivated={() => handleRefresh()}
			/>
		</div>
	);
};

export default AdminMiningPage;
