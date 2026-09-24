// frontend/src/pages/admin/AdminPromoPage.tsx
import React, { useState } from "react";
import { Link } from "react-router-dom";
import {
	Gift,
	Globe,
	ShieldAlert,
	ShieldCheck,
	Lock,
	Save,
	RefreshCw,
	Sparkles,
	Coins,
	Plus,
	CheckCircle2,
	Eye,
	ArrowLeft,
	Sliders,
} from "lucide-react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Switch } from "@/components/ui/switch";
import { Label } from "@/components/ui/label";
import { toast } from "@/components/ui/use-toast";
import {
	useSystemStatus,
	useGetAdminPromoCampaigns,
	useCreateOrUpdatePromoCampaign,
} from "@/lib/api";
import type {
	PromoCampaignAdmin,
	PromoCampaignCreateOrUpdate,
	PromoCampaignQuestsConfig,
	PromoCampaignUpsertPayload,
} from "@/types/api";
import { BitgetLogoSvg } from "@/components/mining/PromoBanner";

const DEFAULT_CAMPAIGN_FORM: PromoCampaignCreateOrUpdate = {
	campaign_id: "bitget_launch_2026",
	campaign_name: "Bitget Launch Airdrop",
	target_exchange: "bitget",
	total_pool: 10_000_000,
	is_active: false,
	admin_only: true,
	start_date: null,
	end_date: null,
	config: {
		quests: {
			api_pioneer: {
				enabled: true,
				reward: 5_000,
				total_slots: 1_000,
				min_volume_usd: 1_000,
			},
			node_runner: {
				enabled: true,
				reward: 25_000,
				total_slots: 200,
				min_volume_usd: 1_000,
				min_node_age_days: 14,
				trade_window_days: 7,
			},
		},
	},
};

const AdminPromoPage: React.FC = () => {
	const { data: systemStatus, isLoading: isLoadingStatus } = useSystemStatus();
	const isCentralHub = Boolean(systemStatus?.isCentralHub);

	const {
		data: campaigns,
		isLoading: isLoadingCampaigns,
		refetch: refetchCampaigns,
	} = useGetAdminPromoCampaigns();
	const { mutate: saveCampaign, isPending: isSaving } = useCreateOrUpdatePromoCampaign();

	const [formData, setFormData] = useState<PromoCampaignCreateOrUpdate>(DEFAULT_CAMPAIGN_FORM);
	const [selectedCampaignId, setSelectedCampaignId] = useState<string>("bitget_launch_2026");

	// Helper: convert backend quests list to form config dict
	const questsListToConfig = (
		quests: PromoCampaignAdmin["quests"],
	): NonNullable<PromoCampaignCreateOrUpdate["config"]> => {
		const questsCfg: PromoCampaignQuestsConfig = {};
		const cfg: NonNullable<PromoCampaignCreateOrUpdate["config"]> = { quests: questsCfg };
		for (const q of quests || []) {
			if (q.quest_type === "api_volume") {
				questsCfg.api_pioneer = {
					enabled: true,
					reward: q.reward,
					total_slots: q.total_slots,
					min_volume_usd: q.volume_threshold || 1000,
				};
			} else if (q.quest_type === "node_runner") {
				questsCfg.node_runner = {
					enabled: true,
					reward: q.reward,
					total_slots: q.total_slots,
					min_volume_usd: q.volume_threshold || 1000,
					min_node_age_days: q.min_node_age_days || 14,
					trade_window_days: q.trade_window_days || 7,
				};
			}
		}
		return cfg;
	};

	// Sync form when the campaigns list is fetched / refetched or the selection
	// changes. React's documented "adjust state when props change" pattern —
	// guarded setState during render — replaces the former sync effect that
	// tripped `react-hooks/set-state-in-effect` (cascading renders). The triggers
	// and the resulting state are the same as before.
	const [lastSyncedCampaigns, setLastSyncedCampaigns] = useState<{
		campaigns?: PromoCampaignAdmin[];
		selectedId?: string;
	}>({});
	if (
		campaigns &&
		campaigns.length > 0 &&
		(campaigns !== lastSyncedCampaigns.campaigns ||
			selectedCampaignId !== lastSyncedCampaigns.selectedId)
	) {
		const existing = campaigns.find((c) => c.id === selectedCampaignId) || campaigns[0];
		setLastSyncedCampaigns({ campaigns, selectedId: existing.id });
		setSelectedCampaignId(existing.id);
		setFormData({
			campaign_id: existing.id,
			campaign_name: existing.name,
			target_exchange: existing.exchangeId,
			total_pool: existing.totalPool,
			is_active: existing.isActive,
			admin_only: existing.adminOnly,
			start_date: null,
			end_date: null,
			config: questsListToConfig(existing.quests) || DEFAULT_CAMPAIGN_FORM.config,
		});
	}

	const handleSelectCampaign = (camp: PromoCampaignAdmin) => {
		setSelectedCampaignId(camp.id);
		setFormData({
			campaign_id: camp.id,
			campaign_name: camp.name,
			target_exchange: camp.exchangeId,
			total_pool: camp.totalPool,
			is_active: camp.isActive,
			admin_only: camp.adminOnly,
			start_date: null,
			end_date: null,
			config: questsListToConfig(camp.quests) || DEFAULT_CAMPAIGN_FORM.config,
		});
	};

	const handleCreateNew = () => {
		setSelectedCampaignId("new_promo");
		setFormData({
			...DEFAULT_CAMPAIGN_FORM,
			campaign_id: `promo_${Date.now().toString().slice(-6)}`,
			campaign_name: "New Promotional Airdrop",
			is_active: false,
			admin_only: true,
		});
	};

	const handleSave = () => {
		if (!formData.campaign_id.trim()) {
			toast({
				title: "Validation Error",
				description: "Campaign ID cannot be empty.",
				variant: "destructive",
			});
			return;
		}

		// Transform form data to match backend PromoCampaignCreateOrUpdate schema
		const questsCfg: PromoCampaignQuestsConfig = formData.config?.quests || {};
		const questsList: PromoCampaignUpsertPayload["quests"] = [];
		if (questsCfg.api_pioneer && questsCfg.api_pioneer.enabled !== false) {
			questsList.push({
				quest_type: "api_volume",
				title: "Bitget API Pioneer",
				description: `Connect your ${formData.target_exchange || "Bitget"} API key and achieve $${(questsCfg.api_pioneer.min_volume_usd || 1000).toLocaleString()} verified trading volume.`,
				reward: questsCfg.api_pioneer.reward || 5000,
				total_slots: questsCfg.api_pioneer.total_slots || 1000,
				volume_threshold: questsCfg.api_pioneer.min_volume_usd || 1000,
			});
		}
		if (questsCfg.node_runner && questsCfg.node_runner.enabled !== false) {
			questsList.push({
				quest_type: "node_runner",
				title: "Node Runner Veteran",
				description: `Run an active node for ${questsCfg.node_runner.min_node_age_days || 14}+ days with wallet linked and recent trades.`,
				reward: questsCfg.node_runner.reward || 25000,
				total_slots: questsCfg.node_runner.total_slots || 200,
				volume_threshold: questsCfg.node_runner.min_volume_usd || 1000,
				min_node_age_days: questsCfg.node_runner.min_node_age_days || 14,
				trade_window_days: questsCfg.node_runner.trade_window_days || 7,
			});
		}

		const apiPayload: PromoCampaignUpsertPayload = {
			id: formData.campaign_id,
			name: formData.campaign_name,
			exchange_id: formData.target_exchange || "bitget",
			total_pool: formData.total_pool,
			admin_only: formData.admin_only,
			is_active: formData.is_active,
			quests: questsList,
			ui_config: null,
		};

		saveCampaign(apiPayload, {
			onSuccess: () => {
				toast({
					title: "Campaign Saved Successfully",
					description: `Campaign "${formData.campaign_name}" has been updated. Status: ${
						formData.is_active ? (formData.admin_only ? "Preview Mode (Admins Only)" : "LIVE (Public)") : "Disabled"
					}`,
				});
				refetchCampaigns();
			},
			onError: (err: Error) => {
				toast({
					title: "Failed to Save Campaign",
					description: err?.message || "An error occurred while saving the campaign.",
					variant: "destructive",
				});
			},
		});
	};

	// Fallback guard: Non-central hub message
	if (!isLoadingStatus && !isCentralHub) {
		return (
			<div className="container mx-auto py-8 max-w-4xl">
				<Card className="border-red-500/30 bg-red-500/5 shadow-xl">
					<CardHeader>
						<div className="flex items-center gap-3">
							<ShieldAlert className="h-8 w-8 text-red-400" />
							<div>
								<CardTitle className="text-xl font-black text-red-400">
									Access Restricted: Central Federation Hub Required
								</CardTitle>
								<CardDescription className="text-muted-foreground mt-1">
									Promo Campaign Management is only available on the Central Federation Hub (IS_CENTRAL_HUB=true).
								</CardDescription>
							</div>
						</div>
					</CardHeader>
					<CardContent className="space-y-4">
						<p className="text-sm text-muted-foreground leading-relaxed">
							Local open-source federation nodes contribute trades and participate in network rewards, but
							promotional campaign pools, budget allocations, and token airdrops are configured centrally by the
							Federation Hub administrator.
						</p>
						<div className="pt-2">
							<Link to="/admin">
								<Button variant="outline" className="flex items-center gap-2">
									<ArrowLeft className="h-4 w-4" />
									Back to Admin Dashboard
								</Button>
							</Link>
						</div>
					</CardContent>
				</Card>
			</div>
		);
	}

	const apiQuest = formData.config?.quests?.api_pioneer || {
		reward: 5000,
		total_slots: 1000,
		min_volume_usd: 1000,
	};
	const nodeQuest = formData.config?.quests?.node_runner || {
		reward: 25000,
		total_slots: 200,
		min_volume_usd: 1000,
		min_node_age_days: 14,
		trade_window_days: 7,
	};

	const totalQuestsSlots = (apiQuest.total_slots || 0) + (nodeQuest.total_slots || 0);
	const totalMaxAllocated =
		(apiQuest.reward || 0) * (apiQuest.total_slots || 0) +
		(nodeQuest.reward || 0) * (nodeQuest.total_slots || 0);

	return (
		<div className="space-y-8 pb-16">
			{/* Header */}
			<div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
				<div>
					<div className="flex items-center gap-3">
						<div className="p-2.5 rounded-xl bg-primary/10 border border-primary/20 text-primary">
							<Gift className="h-7 w-7" />
						</div>
						<div>
							<h1 className="text-3xl font-black tracking-tight flex items-center gap-2">
								Federation Promo Campaign Constructor
								<Badge variant="default" className="bg-primary text-[10px] uppercase font-bold tracking-widest">
									IS_CENTRAL_HUB = TRUE
								</Badge>
							</h1>
							<p className="text-sm text-muted-foreground mt-0.5">
								Universal campaign engine: manage airdrop pools, quest quotas, volume thresholds, and target exchanges across the network.
							</p>
						</div>
					</div>
				</div>

				<div className="flex items-center gap-2">
					<Button
						variant="outline"
						size="sm"
						onClick={() => refetchCampaigns()}
						disabled={isLoadingCampaigns}
						className="flex items-center gap-2"
					>
						<RefreshCw className={`h-4 w-4 ${isLoadingCampaigns ? "animate-spin" : ""}`} />
						Refresh
					</Button>
					<Button
						onClick={handleSave}
						disabled={isSaving}
						className="flex items-center gap-2 bg-gradient-to-r from-primary to-cyan-500 hover:from-primary/90 hover:to-cyan-600 font-bold shadow-md shadow-primary/20"
					>
						<Save className="h-4 w-4" />
						{isSaving ? "Saving..." : "Save & Update"}
					</Button>
				</div>
			</div>

			{/* Existing Campaigns Bar */}
			<Card className="border border-border/70 bg-card/60 backdrop-blur-sm">
				<CardHeader className="py-3 px-4 border-b border-border/40">
					<div className="flex items-center justify-between">
						<CardTitle className="text-sm font-bold flex items-center gap-2">
							<Sliders className="h-4 w-4 text-primary" />
							Available Network Campaigns
						</CardTitle>
						<Button
							variant="outline"
							size="sm"
							onClick={handleCreateNew}
							className="h-7 text-xs flex items-center gap-1.5"
						>
							<Plus className="h-3.5 w-3.5" />
							New Campaign
						</Button>
					</div>
				</CardHeader>
				<CardContent className="p-3">
					<div className="flex flex-wrap gap-2">
						{campaigns && campaigns.length > 0 ? (
							campaigns.map((c) => (
								<button
									key={c.id}
									onClick={() => handleSelectCampaign(c)}
									className={`flex items-center gap-2.5 px-3 py-2 rounded-xl text-xs font-bold border transition-all text-left ${
										selectedCampaignId === c.id
											? "border-primary bg-primary/10 text-primary shadow-sm"
											: "border-border/60 bg-muted/30 hover:border-primary/40 text-muted-foreground"
									}`}
								>
									<BitgetLogoSvg className="h-4 w-4 shrink-0" />
									<div>
										<div className="text-white font-bold">{c.name}</div>
										<div className="text-[10px] text-muted-foreground flex items-center gap-1.5 mt-0.5">
											<span>ID: {c.id}</span>
											<span>•</span>
											<span>{(c.totalPool / 1_000_000).toFixed(1)}M $DEPTH</span>
										</div>
									</div>
									<div className="ml-2 flex items-center gap-1">
										{c.isActive ? (
											c.adminOnly ? (
												<Badge variant="outline" className="text-[9px] border-amber-500/50 text-amber-400 bg-amber-500/10">
													Preview
												</Badge>
											) : (
												<Badge variant="default" className="text-[9px] bg-emerald-500">
													LIVE
												</Badge>
											)
										) : (
											<Badge variant="secondary" className="text-[9px]">
												Disabled
											</Badge>
										)}
									</div>
								</button>
							))
						) : (
							<div className="text-xs text-muted-foreground py-2 px-3">
								No campaigns configured yet. Click "Save & Update" to initialize default Bitget Launch campaign.
							</div>
						)}
					</div>
				</CardContent>
			</Card>

			{/* Main Grid: Form Left, Live Preview Right */}
			<div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
				{/* Form Section (Cols 7) */}
				<div className="lg:col-span-7 space-y-6">
					{/* Core Settings */}
					<Card className="border border-border/80 shadow-md">
						<CardHeader>
							<CardTitle className="text-lg font-bold flex items-center gap-2">
								<Globe className="h-5 w-5 text-primary" />
								Campaign Identity & Status
							</CardTitle>
							<CardDescription>
								Define network identifiers, target broker exchange, and preview visibility.
							</CardDescription>
						</CardHeader>
						<CardContent className="space-y-4">
							<div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
								<div className="space-y-1.5">
									<Label className="text-xs font-bold uppercase tracking-wider text-muted-foreground">
										Campaign ID
									</Label>
									<Input
										value={formData.campaign_id}
										onChange={(e) => setFormData({ ...formData, campaign_id: e.target.value })}
										placeholder="e.g. bitget_launch_2026"
										className="font-mono text-sm"
									/>
									<span className="text-[10px] text-muted-foreground">Unique database identifier</span>
								</div>

								<div className="space-y-1.5">
									<Label className="text-xs font-bold uppercase tracking-wider text-muted-foreground">
										Target Exchange
									</Label>
									<Input
										value={formData.target_exchange}
										onChange={(e) => setFormData({ ...formData, target_exchange: e.target.value })}
										placeholder="e.g. bitget"
										className="font-mono text-sm"
									/>
									<span className="text-[10px] text-muted-foreground">Partner broker for telemetry</span>
								</div>
							</div>

							<div className="space-y-1.5">
								<Label className="text-xs font-bold uppercase tracking-wider text-muted-foreground">
									Campaign Display Name
								</Label>
								<Input
									value={formData.campaign_name}
									onChange={(e) => setFormData({ ...formData, campaign_name: e.target.value })}
									placeholder="e.g. Bitget Launch Airdrop"
								/>
							</div>

							<div className="space-y-1.5">
								<Label className="text-xs font-bold uppercase tracking-wider text-muted-foreground">
									Total Reward Pool ($DEPTH)
								</Label>
								<Input
									type="number"
									value={formData.total_pool}
									onChange={(e) => setFormData({ ...formData, total_pool: Number(e.target.value) })}
									className="font-mono font-bold text-base"
								/>
								<span className="text-[10px] text-muted-foreground">
									Max allocated across quests: {totalMaxAllocated.toLocaleString()} $DEPTH
								</span>
							</div>

							<div className="pt-2 border-t space-y-3">
								{/* Active Switch */}
								<div className="flex items-center justify-between p-3.5 rounded-xl border bg-muted/20">
									<div>
										<div className="text-sm font-bold flex items-center gap-2">
											<ShieldCheck className="h-4 w-4 text-primary" />
											Campaign Active
										</div>
										<p className="text-xs text-muted-foreground mt-0.5">
											Master switch to enable or pause this promotional campaign.
										</p>
									</div>
									<Switch
										checked={formData.is_active}
										onCheckedChange={(checked) => setFormData({ ...formData, is_active: checked })}
									/>
								</div>

								{/* Admin-Only Preview Switch (IMPORTANT FEATURE REQUESTED) */}
								<div className="flex items-center justify-between p-3.5 rounded-xl border border-amber-500/30 bg-amber-500/5">
									<div>
										<div className="text-sm font-bold flex items-center gap-2 text-amber-400">
											<Lock className="h-4 w-4 text-amber-400" />
											Admin-Only Preview Mode
										</div>
										<p className="text-xs text-muted-foreground mt-0.5 max-w-md">
											When enabled, this campaign is visible and claimable ONLY by Administrators for verification. Regular users will not see it.
										</p>
									</div>
									<Switch
										checked={formData.admin_only}
										onCheckedChange={(checked) => setFormData({ ...formData, admin_only: checked })}
									/>
								</div>
							</div>
						</CardContent>
					</Card>

					{/* Quest 1 Config: API Pioneer */}
					<Card className="border border-border/80 shadow-md">
						<CardHeader className="pb-3">
							<div className="flex items-center justify-between">
								<CardTitle className="text-base font-bold flex items-center gap-2">
									<Sparkles className="h-4 w-4 text-cyan-400" />
									Quest 1: API Pioneer
								</CardTitle>
								<Badge variant="outline" className="border-cyan-500/40 text-cyan-400">
									api_pioneer
								</Badge>
							</div>
							<CardDescription>
								Rewards users for connecting API key & achieving trading volume.
							</CardDescription>
						</CardHeader>
						<CardContent className="space-y-4">
							<div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
								<div className="space-y-1">
									<Label className="text-xs text-muted-foreground font-semibold">Reward ($DEPTH)</Label>
									<Input
										type="number"
										value={apiQuest.reward}
										onChange={(e) =>
											setFormData({
												...formData,
												config: {
													...formData.config,
													quests: {
														...formData.config?.quests,
														api_pioneer: {
															...apiQuest,
															reward: Number(e.target.value),
														},
													},
												},
											})
										}
										className="font-mono font-bold"
									/>
								</div>
								<div className="space-y-1">
									<Label className="text-xs text-muted-foreground font-semibold">Total Slots</Label>
									<Input
										type="number"
										value={apiQuest.total_slots}
										onChange={(e) =>
											setFormData({
												...formData,
												config: {
													...formData.config,
													quests: {
														...formData.config?.quests,
														api_pioneer: {
															...apiQuest,
															total_slots: Number(e.target.value),
														},
													},
												},
											})
										}
										className="font-mono font-bold"
									/>
								</div>
								<div className="space-y-1">
									<Label className="text-xs text-muted-foreground font-semibold">Min Volume ($)</Label>
									<Input
										type="number"
										value={apiQuest.min_volume_usd}
										onChange={(e) =>
											setFormData({
												...formData,
												config: {
													...formData.config,
													quests: {
														...formData.config?.quests,
														api_pioneer: {
															...apiQuest,
															min_volume_usd: Number(e.target.value),
														},
													},
												},
											})
										}
										className="font-mono font-bold"
									/>
								</div>
							</div>
							<div className="p-2.5 rounded-lg bg-muted/30 text-xs text-muted-foreground flex justify-between">
								<span>Subtotal Budget:</span>
								<span className="font-bold text-white">
									{((apiQuest.reward || 0) * (apiQuest.total_slots || 0)).toLocaleString()} $DEPTH
								</span>
							</div>
						</CardContent>
					</Card>

					{/* Quest 2 Config: Node Runner */}
					<Card className="border border-border/80 shadow-md">
						<CardHeader className="pb-3">
							<div className="flex items-center justify-between">
								<CardTitle className="text-base font-bold flex items-center gap-2">
									<Coins className="h-4 w-4 text-emerald-400" />
									Quest 2: Node Runner Veteran
								</CardTitle>
								<Badge variant="outline" className="border-emerald-500/40 text-emerald-400">
									node_runner
								</Badge>
							</div>
							<CardDescription>
								Rewards active nodes with longevity, wallet binding, and live trades.
							</CardDescription>
						</CardHeader>
						<CardContent className="space-y-4">
							<div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
								<div className="space-y-1">
									<Label className="text-xs text-muted-foreground font-semibold">Reward ($DEPTH)</Label>
									<Input
										type="number"
										value={nodeQuest.reward}
										onChange={(e) =>
											setFormData({
												...formData,
												config: {
													...formData.config,
													quests: {
														...formData.config?.quests,
														node_runner: {
															...nodeQuest,
															reward: Number(e.target.value),
														},
													},
												},
											})
										}
										className="font-mono font-bold"
									/>
								</div>
								<div className="space-y-1">
									<Label className="text-xs text-muted-foreground font-semibold">Total Slots</Label>
									<Input
										type="number"
										value={nodeQuest.total_slots}
										onChange={(e) =>
											setFormData({
												...formData,
												config: {
													...formData.config,
													quests: {
														...formData.config?.quests,
														node_runner: {
															...nodeQuest,
															total_slots: Number(e.target.value),
														},
													},
												},
											})
										}
										className="font-mono font-bold"
									/>
								</div>
								<div className="space-y-1">
									<Label className="text-xs text-muted-foreground font-semibold">Min Volume ($)</Label>
									<Input
										type="number"
										value={nodeQuest.min_volume_usd}
										onChange={(e) =>
											setFormData({
												...formData,
												config: {
													...formData.config,
													quests: {
														...formData.config?.quests,
														node_runner: {
															...nodeQuest,
															min_volume_usd: Number(e.target.value),
														},
													},
												},
											})
										}
										className="font-mono font-bold"
									/>
								</div>
							</div>

							<div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
								<div className="space-y-1">
									<Label className="text-xs text-muted-foreground font-semibold">Min Node Age (Days)</Label>
									<Input
										type="number"
										value={nodeQuest.min_node_age_days}
										onChange={(e) =>
											setFormData({
												...formData,
												config: {
													...formData.config,
													quests: {
														...formData.config?.quests,
														node_runner: {
															...nodeQuest,
															min_node_age_days: Number(e.target.value),
														},
													},
												},
											})
										}
										className="font-mono font-bold"
									/>
								</div>
								<div className="space-y-1">
									<Label className="text-xs text-muted-foreground font-semibold">Trade Window (Days)</Label>
									<Input
										type="number"
										value={nodeQuest.trade_window_days}
										onChange={(e) =>
											setFormData({
												...formData,
												config: {
													...formData.config,
													quests: {
														...formData.config?.quests,
														node_runner: {
															...nodeQuest,
															trade_window_days: Number(e.target.value),
														},
													},
												},
											})
										}
										className="font-mono font-bold"
									/>
								</div>
							</div>

							<div className="p-2.5 rounded-lg bg-muted/30 text-xs text-muted-foreground flex justify-between">
								<span>Subtotal Budget:</span>
								<span className="font-bold text-white">
									{((nodeQuest.reward || 0) * (nodeQuest.total_slots || 0)).toLocaleString()} $DEPTH
								</span>
							</div>
						</CardContent>
					</Card>
				</div>

				{/* Preview Section Right (Cols 5) */}
				<div className="lg:col-span-5 space-y-6">
					<Card className="border border-primary/40 bg-gradient-to-b from-card to-background shadow-lg sticky top-6">
						<CardHeader className="pb-3 border-b border-border/40">
							<div className="flex items-center justify-between">
								<CardTitle className="text-sm font-bold flex items-center gap-2">
									<Eye className="h-4 w-4 text-primary" />
									Live Campaign Simulator
								</CardTitle>
								<Badge variant="outline" className="text-[10px]">
									Client Perspective
								</Badge>
							</div>
							<CardDescription className="text-xs">
								Real-time preview of how the promo banner & cards appear to users.
							</CardDescription>
						</CardHeader>
						<CardContent className="p-4 space-y-4">
							{/* Status indicator */}
							<div className="p-3 rounded-xl border text-xs flex items-center justify-between bg-card/60">
								<span className="text-muted-foreground">Campaign Visibility:</span>
								{formData.is_active ? (
									formData.admin_only ? (
										<span className="text-amber-400 font-bold flex items-center gap-1.5">
											<Lock className="h-3.5 w-3.5" />
											Admin Only (Preview)
										</span>
									) : (
										<span className="text-emerald-400 font-bold flex items-center gap-1.5">
											<CheckCircle2 className="h-3.5 w-3.5" />
											Public (Live for All)
										</span>
									)
								) : (
									<span className="text-muted-foreground font-bold">Hidden / Disabled</span>
								)}
							</div>

							{/* Simulated Banner */}
							<div className="overflow-hidden rounded-xl border border-[#1DA2B4]/40 bg-gradient-to-r from-[#1DA2B4]/15 via-[#0F1923]/95 to-blue-500/10 p-3.5 shadow-md">
								<div className="flex items-center gap-3">
									<div className="h-10 w-10 shrink-0 rounded-lg border border-[#00F0FF]/40 bg-[#1DA2B4]/20 p-1">
										<BitgetLogoSvg className="h-full w-full" />
									</div>
									<div className="min-w-0 flex-1">
										<div className="flex items-center gap-1.5 flex-wrap">
											<h4 className="text-xs font-bold text-white truncate">
												{formData.campaign_name || "Bitget Launch Airdrop"}
											</h4>
											{formData.admin_only && (
												<span className="rounded border border-amber-500/40 bg-amber-500/15 px-1.5 py-0.2 text-[9px] font-bold text-amber-400">
													PREVIEW
												</span>
											)}
										</div>
										<p className="text-[10px] text-gray-300 mt-0.5">
											{totalQuestsSlots} slots • {(formData.total_pool / 1_000_000).toFixed(1)}M $DEPTH Pool
										</p>
									</div>
								</div>
							</div>

							{/* Simulated Quest Cards */}
							<div className="space-y-2.5">
								{/* Quest 1 */}
								<div className="p-3 rounded-xl border border-border/80 bg-card/40 space-y-2">
									<div className="flex justify-between items-center text-xs">
										<span className="font-bold text-white flex items-center gap-1.5">
											<Sparkles className="h-3.5 w-3.5 text-cyan-400" />
											Bitget API Pioneer
										</span>
										<span className="font-mono font-bold text-cyan-400">
											+{apiQuest.reward?.toLocaleString()} $DEPTH
										</span>
									</div>
									<p className="text-[11px] text-muted-foreground">
										Min volume: ${apiQuest.min_volume_usd?.toLocaleString()} • Slots: {apiQuest.total_slots}
									</p>
								</div>

								{/* Quest 2 */}
								<div className="p-3 rounded-xl border border-border/80 bg-card/40 space-y-2">
									<div className="flex justify-between items-center text-xs">
										<span className="font-bold text-white flex items-center gap-1.5">
											<Coins className="h-3.5 w-3.5 text-emerald-400" />
											Node Runner Veteran
										</span>
										<span className="font-mono font-bold text-emerald-400">
											+{nodeQuest.reward?.toLocaleString()} $DEPTH
										</span>
									</div>
									<p className="text-[11px] text-muted-foreground">
										Age: {nodeQuest.min_node_age_days}d+ • Window: {nodeQuest.trade_window_days}d • Slots: {nodeQuest.total_slots}
									</p>
								</div>
							</div>

							{/* Budget check */}
							<div className="p-3 rounded-xl bg-muted/40 border text-xs space-y-1.5">
								<div className="flex justify-between text-muted-foreground">
									<span>Total Budget Needed:</span>
									<span className="font-mono font-bold text-white">
										{totalMaxAllocated.toLocaleString()} $DEPTH
									</span>
								</div>
								<div className="flex justify-between text-muted-foreground">
									<span>Total Pool Defined:</span>
									<span className="font-mono font-bold text-primary">
										{Number(formData.total_pool).toLocaleString()} $DEPTH
									</span>
								</div>
								{totalMaxAllocated > Number(formData.total_pool) && (
									<p className="text-[10px] text-red-400 font-bold pt-1">
										⚠️ Warning: Quest allocations exceed the total pool limit!
									</p>
								)}
							</div>
						</CardContent>
					</Card>
				</div>
			</div>
		</div>
	);
};

export default AdminPromoPage;
