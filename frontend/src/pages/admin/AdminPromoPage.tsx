// frontend/src/pages/admin/AdminPromoPage.tsx
import React, { useState, useMemo } from "react";
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
	Check,
	Zap,
	Server,
	Download,
	Power,
	Palette,
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
	useGetHubMiningConfig,
} from "@/lib/api";
import type {
	PromoCampaignAdmin,
	PromoCampaignCreateOrUpdate,
	PromoCampaignQuestsConfig,
	PromoCampaignUpsertPayload,
} from "@/types/api";
import {
	COLOR_THEMES,
	getNftPassImageUrl,
	getQuestColorTheme,
} from "@/lib/nftAssets";
import {
	exchangeLabels,
	exchangeLogos,
	exchangeMeta,
	normalizeExchangeKey,
} from "@/lib/exchanges";

const TOKEN_PRESETS = {
	token0: {
		title: "DepthSight Genesis Pass",
		description:
			"Official DePIN Proof-of-Telemetry allocation voucher (ERC-1155 Token #0 on Arbitrum One). Redeemable at TGE 1:1.",
		reward: 10_000,
		total_slots: 1_000,
		min_volume_usd: 10_000,
		reward_type: "nft" as const,
		nft_contract_address: "0x29ce393672507c185a5E9Bc2e721E8009e3520C8",
		nft_chain_id: 42161,
		nft_token_id: 0,
		nft_name: "DepthSight Genesis Pass",
		nft_image_url: "/nft/genesis_pass_0.jpg",
		nft_multiplier: "1.0x",
		nft_nominal: 10_000,
		nft_max_supply: 1_000,
		nft_color_theme: "cyan",
	},
	token1: {
		title: "DepthSight Core Syndicate Pass",
		description:
			"Official Proof-of-Trade allocation voucher for DepthSight DePIN Network (ERC-1155 Token #1 on Arbitrum One).",
		reward: 25_000,
		total_slots: 300,
		min_volume_usd: 25_000,
		reward_type: "nft" as const,
		nft_contract_address: "0x29ce393672507c185a5E9Bc2e721E8009e3520C8",
		nft_chain_id: 42161,
		nft_token_id: 1,
		nft_name: "DepthSight Core Syndicate Pass",
		nft_image_url: "/nft/genesis_pass_1.jpg",
		nft_multiplier: "1.5x",
		nft_nominal: 25_000,
		nft_max_supply: 300,
		nft_color_theme: "gold",
	},
	token2: {
		title: "DepthSight Apex Syndicate Pass",
		description:
			"Elite algorithmic liquidity allocation voucher for DepthSight DePIN Network (ERC-1155 Token #2 on Arbitrum One).",
		reward: 50_000,
		total_slots: 50,
		min_volume_usd: 50_000,
		min_node_age_days: 14,
		trade_window_days: 7,
		reward_type: "nft" as const,
		nft_contract_address: "0x29ce393672507c185a5E9Bc2e721E8009e3520C8",
		nft_chain_id: 42161,
		nft_token_id: 2,
		nft_name: "DepthSight Apex Syndicate Pass",
		nft_image_url: "/nft/genesis_pass_2.jpg",
		nft_multiplier: "2.0x",
		nft_nominal: 50_000,
		nft_max_supply: 50,
		nft_color_theme: "purple",
	},
};

const DEFAULT_CAMPAIGN_FORM: PromoCampaignCreateOrUpdate = {
	campaign_id: "universal_genesis_2026",
	campaign_name: "DepthSight Genesis Pass Airdrop",
	target_exchange: "all",
	total_pool: 20_000_000,
	is_active: false,
	admin_only: true,
	start_date: null,
	end_date: null,
	config: {
		quests: {
			telemetry_pass: {
				enabled: true,
				...TOKEN_PRESETS.token0,
			},
			api_pioneer: {
				enabled: true,
				...TOKEN_PRESETS.token1,
			},
			node_runner: {
				enabled: true,
				...TOKEN_PRESETS.token2,
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
	const { data: hubConfig } = useGetHubMiningConfig(isCentralHub);

	// Extract active mining exchanges from Hub config
	const activeMiningExchanges = useMemo(() => {
		const raw = hubConfig?.eligibleExchanges || [];
		const unique = new Set<string>();
		for (const item of raw) {
			const norm = normalizeExchangeKey(item) || item.toLowerCase().replace(/_(futures|spot|swap|linear)$/, "");
			if (norm) unique.add(norm);
		}
		return Array.from(unique);
	}, [hubConfig]);

	// Standard exchanges that can be configured, starting with Universal ("all")
	const supportedExchanges = useMemo(() => {
		const baseList = ["all", "bybit", "okx", "weex", "bitget", "hyperliquid", "binance", "gate", "bingx"];
		for (const ex of activeMiningExchanges) {
			if (!baseList.includes(ex)) baseList.push(ex);
		}
		return baseList;
	}, [activeMiningExchanges]);

	const [formData, setFormData] = useState<PromoCampaignCreateOrUpdate>(DEFAULT_CAMPAIGN_FORM);
	const [selectedCampaignId, setSelectedCampaignId] = useState<string>("universal_genesis_2026");

	// Helper: convert backend quests list to form config dict
	const questsListToConfig = (
		quests: PromoCampaignAdmin["quests"],
	): NonNullable<PromoCampaignCreateOrUpdate["config"]> => {
		const questsCfg: PromoCampaignQuestsConfig = {};
		const cfg: NonNullable<PromoCampaignCreateOrUpdate["config"]> = { quests: questsCfg };
		for (const q of quests || []) {
			const commonNft = {
				reward_type: (q.reward_type as "token" | "nft") || "token",
				nft_contract_address: (q.nft_contract_address as string) || undefined,
				nft_chain_id: (q.nft_chain_id as number) || 42161,
				nft_token_id: q.nft_token_id !== undefined ? Number(q.nft_token_id) : undefined,
				nft_name: (q.nft_name as string) || undefined,
				nft_image_url: (q.nft_image_url as string) || undefined,
				nft_multiplier: (q.nft_multiplier as string) || undefined,
				nft_nominal: q.nft_nominal !== undefined ? Number(q.nft_nominal) : undefined,
				nft_max_supply: q.nft_max_supply !== undefined ? Number(q.nft_max_supply) : undefined,
				nft_color_theme: (q.nft_color_theme as string) || (q.nft_token_id === 2 ? "purple" : q.nft_token_id === 0 ? "cyan" : "gold"),
			};

			if (q.quest_type === "api_volume") {
				questsCfg.api_pioneer = {
					enabled: true,
					title: q.title,
					description: q.description || undefined,
					reward: q.reward,
					total_slots: q.total_slots,
					min_volume_usd: q.volume_threshold || 1000,
					...commonNft,
				};
			} else if (q.quest_type === "node_runner") {
				questsCfg.node_runner = {
					enabled: true,
					title: q.title,
					description: q.description || undefined,
					reward: q.reward,
					total_slots: q.total_slots,
					min_volume_usd: q.volume_threshold || 1000,
					min_node_age_days: q.min_node_age_days || 14,
					trade_window_days: q.trade_window_days || 7,
					...commonNft,
				};
			} else if (q.quest_type === "telemetry_pass" || q.nft_token_id === 0) {
				questsCfg.telemetry_pass = {
					enabled: true,
					title: q.title,
					description: q.description || undefined,
					reward: q.reward,
					total_slots: q.total_slots,
					min_volume_usd: q.volume_threshold || 10000,
					...commonNft,
				};
			} else {
				questsCfg.telemetry_pass = {
					enabled: true,
					title: q.title,
					description: q.description || undefined,
					reward: q.reward,
					total_slots: q.total_slots,
					min_volume_usd: q.volume_threshold || 10000,
					...commonNft,
				};
			}
		}
		return cfg;
	};

	const applyTokenPresetToQuest = (
		questKey: "api_pioneer" | "node_runner" | "telemetry_pass",
		presetKey: "token0" | "token1" | "token2",
	) => {
		const preset = TOKEN_PRESETS[presetKey];
		const currentQuest = formData.config?.quests?.[questKey] || {};
		setFormData({
			...formData,
			config: {
				...formData.config,
				quests: {
					...formData.config?.quests,
					[questKey]: {
						...currentQuest,
						enabled: true,
						title: preset.title,
						description: preset.description,
						reward: preset.reward,
						total_slots: preset.total_slots,
						min_volume_usd: preset.min_volume_usd,
						reward_type: "nft",
						nft_contract_address: preset.nft_contract_address,
						nft_chain_id: preset.nft_chain_id,
						nft_token_id: preset.nft_token_id,
						nft_name: preset.nft_name,
						nft_image_url: preset.nft_image_url,
						nft_multiplier: preset.nft_multiplier,
						nft_nominal: preset.nft_nominal,
						nft_max_supply: preset.nft_max_supply,
						nft_color_theme: preset.nft_color_theme,
					},
				},
			},
		});
	};

	// Sync form when the campaigns list is fetched / refetched or selection changes
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

	const [isExporting, setIsExporting] = useState(false);
	const handleExportThirdwebCsv = async (questType?: string) => {
		try {
			setIsExporting(true);
			const token = localStorage.getItem("token") || "";
			const url = `/api/hub/promo/admin/claims/export?campaign_id=${encodeURIComponent(formData.campaign_id)}${questType ? `&quest_type=${encodeURIComponent(questType)}` : ""}&format=thirdweb`;
			const res = await fetch(url, {
				headers: {
					Authorization: `Bearer ${token}`,
				},
			});
			if (!res.ok) {
				const err = await res.json().catch(() => ({}));
				throw new Error(err.detail || "Export failed");
			}
			const blob = await res.blob();
			const downloadUrl = window.URL.createObjectURL(blob);
			const a = document.createElement("a");
			a.href = downloadUrl;
			a.download = `thirdweb_airdrop_${formData.campaign_id}_${questType || "all"}.csv`;
			document.body.appendChild(a);
			a.click();
			a.remove();
			window.URL.revokeObjectURL(downloadUrl);
			toast({
				title: "CSV Exported Successfully",
				description: `Downloaded Thirdweb Airdrop CSV for campaign ${formData.campaign_id}. Ready to upload at thirdweb.com!`,
			});
		} catch (err: unknown) {
			toast({
				title: "Export Failed",
				description: (err as Error)?.message || "Failed to export claims CSV.",
				variant: "destructive",
			});
		} finally {
			setIsExporting(false);
		}
	};

	const handleSelectTargetExchange = (exKey: string) => {
		if (exKey === "all") {
			const isDefaultName =
				!formData.campaign_name ||
				formData.campaign_name.endsWith("Launch Airdrop") ||
				formData.campaign_name.endsWith("Airdrop");
			const isDefaultId =
				!formData.campaign_id ||
				formData.campaign_id.endsWith("_launch_2026") ||
				formData.campaign_id.endsWith("_genesis_2026");

			setFormData({
				...formData,
				target_exchange: "all",
				campaign_name: isDefaultName ? "DepthSight Genesis Pass Airdrop" : formData.campaign_name,
				campaign_id: isDefaultId ? "universal_genesis_2026" : formData.campaign_id,
			});
			return;
		}

		const norm = normalizeExchangeKey(exKey) || exKey.toLowerCase();
		const label = exchangeLabels[norm] || norm.toUpperCase();

		const isDefaultName =
			!formData.campaign_name ||
			formData.campaign_name === "Trade Mining Launch Airdrop" ||
			formData.campaign_name.endsWith("Launch Airdrop") ||
			formData.campaign_name.endsWith("Airdrop");
		const isDefaultId =
			!formData.campaign_id ||
			formData.campaign_id === "promo_launch_2026" ||
			formData.campaign_id.endsWith("_launch_2026") ||
			formData.campaign_id.endsWith("_genesis_2026");

		const newName = isDefaultName ? `${label} Launch Airdrop` : formData.campaign_name;
		const newId = isDefaultId ? `${norm}_launch_2026` : formData.campaign_id;

		setFormData({
			...formData,
			target_exchange: norm,
			campaign_name: newName,
			campaign_id: newId,
		});
	};

	const handleToggleCampaignActive = (camp: PromoCampaignAdmin, e: React.MouseEvent) => {
		e.stopPropagation();
		const newActive = !camp.isActive;
		saveCampaign(
			{
				id: camp.id,
				name: camp.name,
				exchange_id: camp.exchangeId,
				total_pool: camp.totalPool,
				admin_only: camp.adminOnly,
				is_active: newActive,
				quests: camp.quests as unknown as PromoCampaignUpsertPayload["quests"],
				ui_config: (camp.uiConfig as Record<string, unknown>) || null,
			},
			{
				onSuccess: () => {
					toast({
						title: newActive ? "Campaign Activated" : "Campaign Deactivated",
						description: `Campaign "${camp.name}" is now ${newActive ? "ACTIVE (LIVE)" : "DISABLED (Inactive)"}.`,
					});
					refetchCampaigns();
					if (formData.campaign_id === camp.id) {
						setFormData((prev) => ({ ...prev, is_active: newActive }));
					}
				},
				onError: (err: Error) => {
					toast({
						title: "Failed to update campaign",
						description: err?.message || "Error updating campaign state",
						variant: "destructive",
					});
				},
			}
		);
	};

	const handleCreateNew = () => {
		setSelectedCampaignId("new_universal_genesis");
		setFormData({
			...DEFAULT_CAMPAIGN_FORM,
			campaign_id: `genesis_airdrop_${Date.now().toString().slice(-4)}`,
			campaign_name: "DepthSight Genesis Pass Airdrop",
			target_exchange: "all",
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

		const isUniv = formData.target_exchange === "all";
		const targetExKey = isUniv
			? "all"
			: normalizeExchangeKey(formData.target_exchange) || formData.target_exchange?.toLowerCase() || "exchange";
		const targetExLabel = isUniv
			? "Universal (All Exchanges)"
			: exchangeLabels[targetExKey] || formData.target_exchange || "Exchange";

		// Transform form data to match backend PromoCampaignCreateOrUpdate schema
		// Quests list order: 10k Genesis Pass (#0) -> 25k Core Syndicate Pass (#1) -> 50k Apex Syndicate Pass (#2)
		const questsCfg: PromoCampaignQuestsConfig = formData.config?.quests || {};
		const questsList: PromoCampaignUpsertPayload["quests"] = [];

		if (questsCfg.telemetry_pass && questsCfg.telemetry_pass.enabled !== false) {
			const q = questsCfg.telemetry_pass;
			const isGeneratedTelemDesc = Boolean(
				!q.description ||
				/^(connect|rewards|подключите|official depin|run an active node|запустите активную ноду)/i.test(q.description.trim()) ||
				((isUniv || targetExKey !== "bitget") && /bitget/i.test(q.description))
			);
			const telemDesc = isGeneratedTelemDesc
				? (isUniv
					? `Connect any supported exchange and achieve $${(q.min_volume_usd || 10000).toLocaleString()} verified trading volume.`
					: `Connect your ${targetExLabel} and achieve $${(q.min_volume_usd || 10000).toLocaleString()} verified trading volume.`)
				: q.description;

			questsList.push({
				quest_type: "telemetry_pass",
				title: q.title || "DepthSight Genesis Pass",
				description: telemDesc,
				reward: q.reward || 10000,
				total_slots: q.total_slots || 1000,
				volume_threshold: q.min_volume_usd || 10000,
				reward_type: q.reward_type || "nft",
				nft_contract_address: q.nft_contract_address || "0x29ce393672507c185a5E9Bc2e721E8009e3520C8",
				nft_chain_id: q.nft_chain_id || 42161,
				nft_token_id: q.nft_token_id ?? 0,
				nft_name: q.nft_name || "DepthSight Genesis Pass",
				nft_image_url: q.nft_image_url || "/nft/genesis_pass_0.jpg",
				nft_multiplier: q.nft_multiplier || "1.0x",
				nft_nominal: q.nft_nominal || 10000,
				nft_max_supply: q.nft_max_supply || 1000,
				nft_color_theme: q.nft_color_theme || "cyan",
			});
		}

		if (questsCfg.api_pioneer && questsCfg.api_pioneer.enabled !== false) {
			const q = questsCfg.api_pioneer;
			const isGeneratedApiDesc = Boolean(
				!q.description ||
				/^(connect (your|an|the)|rewards users|подключите)/i.test(q.description.trim()) ||
				q.description.includes("$5 000") ||
				q.description.includes("$1 000") ||
				((isUniv || targetExKey !== "bitget") && /bitget/i.test(q.description))
			);
			const apiDesc = isGeneratedApiDesc
				? (isUniv
					? `Connect an API key of any supported exchange and achieve $${(q.min_volume_usd || 1000).toLocaleString()} verified trading volume.`
					: `Connect your ${targetExLabel} API key and achieve $${(q.min_volume_usd || 1000).toLocaleString()} verified trading volume.`)
				: q.description;

			questsList.push({
				quest_type: "api_volume",
				title: q.title || (isUniv ? "DepthSight Core Syndicate Pass" : `${targetExLabel} API Pioneer`),
				description: apiDesc,
				reward: q.reward || 5000,
				total_slots: q.total_slots || 1000,
				volume_threshold: q.min_volume_usd || 1000,
				reward_type: q.reward_type || "token",
				nft_contract_address: q.nft_contract_address,
				nft_chain_id: q.nft_chain_id || 42161,
				nft_token_id: q.nft_token_id,
				nft_name: q.nft_name,
				nft_image_url: q.nft_image_url,
				nft_multiplier: q.nft_multiplier,
				nft_nominal: q.nft_nominal,
				nft_max_supply: q.nft_max_supply,
				nft_color_theme: q.nft_color_theme || "gold",
			});
		}

		if (questsCfg.node_runner && questsCfg.node_runner.enabled !== false) {
			const q = questsCfg.node_runner;
			const isGeneratedNodeDesc = Boolean(
				!q.description ||
				/^(run an active node|запустите активную ноду)/i.test(q.description.trim()) ||
				((isUniv || targetExKey !== "bitget") && /bitget/i.test(q.description))
			);
			const nodeDesc = isGeneratedNodeDesc
				? (isUniv
					? `Run an active node for ${q.min_node_age_days || 14}+ days with wallet linked and live trades across supported exchanges.`
					: `Run an active node for ${q.min_node_age_days || 14}+ days with wallet linked and live trades on ${targetExLabel}.`)
				: q.description;

			questsList.push({
				quest_type: "node_runner",
				title: q.title || (isUniv ? "DepthSight Apex Syndicate Pass" : "Node Runner Veteran"),
				description: nodeDesc,
				reward: q.reward || 25000,
				total_slots: q.total_slots || 200,
				volume_threshold: q.min_volume_usd || 1000,
				min_node_age_days: q.min_node_age_days || 14,
				trade_window_days: q.trade_window_days || 7,
				reward_type: q.reward_type || "token",
				nft_contract_address: q.nft_contract_address,
				nft_chain_id: q.nft_chain_id || 42161,
				nft_token_id: q.nft_token_id,
				nft_name: q.nft_name,
				nft_image_url: q.nft_image_url,
				nft_multiplier: q.nft_multiplier,
				nft_nominal: q.nft_nominal,
				nft_max_supply: q.nft_max_supply,
				nft_color_theme: q.nft_color_theme || "purple",
			});
		}

		const apiPayload: PromoCampaignUpsertPayload = {
			id: formData.campaign_id,
			name: formData.campaign_name,
			exchange_id: targetExKey,
			total_pool: formData.total_pool,
			admin_only: formData.admin_only,
			is_active: formData.is_active,
			quests: questsList,
			ui_config: null,
		};

		// Guard against accidental quest wipes
		if (questsList.length === 0) {
			toast({
				title: "Validation Error",
				description:
					"At least one quest must be enabled. Both quest sections are empty — refusing to wipe the campaign.",
				variant: "destructive",
			});
			return;
		}

		saveCampaign(apiPayload, {
			onSuccess: () => {
				toast({
					title: "Campaign Saved Successfully",
					description: `Campaign "${formData.campaign_name}" (${targetExLabel}) has been updated. Status: ${
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
		enabled: true,
		...TOKEN_PRESETS.token1,
	};
	const nodeQuest = formData.config?.quests?.node_runner || {
		enabled: true,
		...TOKEN_PRESETS.token2,
	};
	const telemQuest = formData.config?.quests?.telemetry_pass || {
		enabled: true,
		...TOKEN_PRESETS.token0,
	};

	const totalQuestsSlots =
		(apiQuest.enabled !== false ? apiQuest.total_slots || 0 : 0) +
		(nodeQuest.enabled !== false ? nodeQuest.total_slots || 0 : 0) +
		(telemQuest.enabled !== false ? telemQuest.total_slots || 0 : 0);

	const totalMaxAllocated =
		(apiQuest.enabled !== false ? (apiQuest.reward || 0) * (apiQuest.total_slots || 0) : 0) +
		(nodeQuest.enabled !== false ? (nodeQuest.reward || 0) * (nodeQuest.total_slots || 0) : 0) +
		(telemQuest.enabled !== false ? (telemQuest.reward || 0) * (telemQuest.total_slots || 0) : 0);

	const isUniversal = formData.target_exchange === "all";
	const currentExKey = isUniversal
		? "all"
		: normalizeExchangeKey(formData.target_exchange) || formData.target_exchange?.toLowerCase();
	const currentExLogo = isUniversal ? null : currentExKey ? exchangeLogos[currentExKey] : null;
	const currentExLabel = isUniversal
		? "Universal (All Exchanges)"
		: (currentExKey ? exchangeLabels[currentExKey] : null) || formData.target_exchange || "Exchange";
	const currentBrandColor = isUniversal
		? "#00F0FF"
		: currentExKey && exchangeMeta[currentExKey]
		? exchangeMeta[currentExKey].color
		: "#00F0FF";

	const apiTheme = getQuestColorTheme(apiQuest.nft_color_theme, "gold");
	const nodeTheme = getQuestColorTheme(nodeQuest.nft_color_theme, "purple");
	const telemTheme = getQuestColorTheme(telemQuest.nft_color_theme, "cyan");

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

				<div className="flex items-center gap-2 flex-wrap">
					<Button
						variant="outline"
						size="sm"
						onClick={() => handleExportThirdwebCsv()}
						disabled={isExporting}
						className="flex items-center gap-2 border-amber-500/40 text-amber-300 hover:bg-amber-500/10 font-bold"
						title="Export claimed wallet addresses in Thirdweb Edition Airdrop format (address,tokenId,quantity)"
					>
						<Download className={`h-4 w-4 ${isExporting ? "animate-bounce" : ""}`} />
						{isExporting ? "Exporting..." : "Thirdweb CSV"}
					</Button>
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
							campaigns.map((c) => {
								const exKey = normalizeExchangeKey(c.exchangeId) || c.exchangeId?.toLowerCase();
								const logo = exKey ? exchangeLogos[exKey] : null;
								const exLabel = (exKey ? exchangeLabels[exKey] : null) || c.exchangeId || "Exchange";

								return (
									<button
										key={c.id}
										onClick={() => handleSelectCampaign(c)}
										className={`flex items-center gap-2.5 px-3 py-2 rounded-xl text-xs font-bold border transition-all text-left ${
											selectedCampaignId === c.id
												? "border-primary bg-primary/10 text-primary shadow-sm"
												: "border-border/60 bg-muted/30 hover:border-primary/40 text-muted-foreground"
										}`}
									>
										<div className="h-5 w-5 rounded-md bg-muted/40 border border-border/50 p-0.5 flex items-center justify-center shrink-0">
											{logo ? (
												<img src={logo} alt={exLabel} className="h-full w-full object-contain" />
											) : (
												<Gift className="h-3.5 w-3.5 text-primary" />
											)}
										</div>
										<div>
											<div className="text-white font-bold">{c.name}</div>
											<div className="text-[10px] text-muted-foreground flex items-center gap-1.5 mt-0.5">
												<span className="uppercase font-mono text-[9px] text-cyan-400">{exLabel}</span>
												<span>•</span>
												<span>ID: {c.id}</span>
												<span>•</span>
												<span>{(c.totalPool / 1_000_000).toFixed(1)}M $DEPTH</span>
											</div>
										</div>
										<div className="ml-2 flex items-center gap-1.5">
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
											<Button
												type="button"
												size="sm"
												variant="ghost"
												onClick={(e) => handleToggleCampaignActive(c, e)}
												className={`h-6 px-1.5 text-[10px] font-bold ${
													c.isActive
														? "text-red-400 hover:text-red-300 hover:bg-red-500/20"
														: "text-emerald-400 hover:text-emerald-300 hover:bg-emerald-500/20"
												}`}
												title={c.isActive ? "Deactivate old campaign" : "Activate campaign"}
											>
												<Power className="h-3 w-3 mr-1" />
												{c.isActive ? "Deactivate" : "Activate"}
											</Button>
										</div>
									</button>
								);
							})
						) : (
							<div className="text-xs text-muted-foreground py-2 px-3">
								No campaigns configured yet. Click "New Campaign" or select an active exchange below to create one.
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
								Configure campaign identifiers, target trading exchange, and preview visibility.
							</CardDescription>
						</CardHeader>
						<CardContent className="space-y-4">
							{/* Target Exchange Selector with Active Mining Highlights */}
							<div className="space-y-2.5">
								<div className="flex items-center justify-between">
									<Label className="text-xs font-bold uppercase tracking-wider text-muted-foreground flex items-center gap-1.5">
										<Zap className="h-3.5 w-3.5 text-primary" />
										Target Mining Exchange
									</Label>
									<span className="text-[11px] text-muted-foreground">
										Currently active in Trade Mining:{" "}
										<span className="font-bold text-emerald-400 font-mono">
											{activeMiningExchanges.length > 0 ? activeMiningExchanges.join(", ") : "weex, bybit, okx"}
										</span>
									</span>
								</div>

								{/* Selectable Exchange Cards */}
								<div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
									{supportedExchanges.map((ex) => {
										const isAll = ex === "all";
										const norm = isAll ? "all" : normalizeExchangeKey(ex) || ex;
										const isMiningActive = isAll ? true : activeMiningExchanges.includes(norm);
										const isSelected = isAll
											? formData.target_exchange === "all"
											: (normalizeExchangeKey(formData.target_exchange) || formData.target_exchange?.toLowerCase()) === norm;
										const logo = isAll ? null : exchangeLogos[norm];
										const label = isAll ? "Universal (All)" : exchangeLabels[norm] || ex.toUpperCase();

										return (
											<button
												key={ex}
												type="button"
												onClick={() => handleSelectTargetExchange(norm)}
												className={`p-2.5 rounded-xl border text-left transition-all flex items-center gap-2.5 relative overflow-hidden ${
													isSelected
														? "border-primary bg-primary/15 text-primary ring-1 ring-primary shadow-sm"
														: "border-border/60 bg-muted/20 hover:border-primary/40 text-muted-foreground hover:text-foreground"
												}`}
											>
												<div className="h-7 w-7 rounded-lg bg-card/80 border border-border/60 p-1 flex items-center justify-center shrink-0">
													{logo ? (
														<img src={logo} alt={label} className="h-full w-full object-contain" />
													) : (
														<Globe className="h-4 w-4 text-cyan-400" />
													)}
												</div>
												<div className="min-w-0 flex-1">
													<div className="text-xs font-bold truncate text-white">{label}</div>
													<div className="text-[9px] flex items-center gap-1 mt-0.5">
														{isAll ? (
															<span className="text-cyan-400 font-semibold flex items-center gap-0.5">
																<span className="h-1.5 w-1.5 rounded-full bg-cyan-400" />
																Multi-Exchange
															</span>
														) : isMiningActive ? (
															<span className="text-emerald-400 font-semibold flex items-center gap-0.5">
																<span className="h-1.5 w-1.5 rounded-full bg-emerald-400" />
																Active
															</span>
														) : (
															<span className="text-muted-foreground">Off</span>
														)}
													</div>
												</div>
												{isSelected && (
													<Check className="h-3.5 w-3.5 text-primary shrink-0" />
												)}
											</button>
										);
									})}
								</div>

								{/* Direct raw exchange input */}
								<div className="space-y-1 pt-1">
									<div className="flex items-center justify-between text-[11px] text-muted-foreground">
										<span>Custom / Raw Target Exchange ID:</span>
										<span className="font-mono text-cyan-400 font-bold">{formData.target_exchange || "none"}</span>
									</div>
									<Input
										value={formData.target_exchange}
										onChange={(e) => setFormData({ ...formData, target_exchange: e.target.value.toLowerCase().trim() })}
										placeholder="e.g. bybit, okx, weex, hyperliquid"
										className="font-mono text-sm"
									/>
								</div>
							</div>

							<div className="grid grid-cols-1 sm:grid-cols-2 gap-4 pt-1">
								<div className="space-y-1.5">
									<Label className="text-xs font-bold uppercase tracking-wider text-muted-foreground">
										Campaign ID
									</Label>
									<Input
										value={formData.campaign_id}
										onChange={(e) => setFormData({ ...formData, campaign_id: e.target.value })}
										placeholder="e.g. bybit_launch_2026"
										className="font-mono text-sm"
									/>
									<span className="text-[10px] text-muted-foreground">Unique database identifier</span>
								</div>

								<div className="space-y-1.5">
									<Label className="text-xs font-bold uppercase tracking-wider text-muted-foreground">
										Campaign Display Name
									</Label>
									<Input
										value={formData.campaign_name}
										onChange={(e) => setFormData({ ...formData, campaign_name: e.target.value })}
										placeholder="e.g. Bybit Launch Airdrop"
									/>
									<span className="text-[10px] text-muted-foreground">User-facing campaign headline</span>
								</div>
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

								{/* Admin-Only Preview Switch */}
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

					{/* Quest 1 Config: Telemetry Genesis Pass (#0) */}
					<Card className={`border shadow-md transition-all ${telemQuest.enabled !== false ? "border-border/80" : "border-border/40 opacity-70"}`}>
						<CardHeader className="pb-3">
							<div className="flex items-center justify-between">
								<CardTitle className="text-base font-bold flex items-center gap-2">
									<Sparkles className="h-4 w-4 text-cyan-400" />
									Quest 1: DepthSight Genesis Pass (#0)
								</CardTitle>
								<div className="flex items-center gap-2">
									<button
										type="button"
										onClick={() =>
											setFormData({
												...formData,
												config: {
													...formData.config,
													quests: {
														...formData.config?.quests,
														telemetry_pass: {
															...telemQuest,
															enabled: telemQuest.enabled === false ? true : false,
														},
													},
												},
											})
										}
										className={`text-[10px] font-bold px-2 py-0.5 rounded border transition-all ${
											telemQuest.enabled !== false
												? "border-emerald-500/40 bg-emerald-500/15 text-emerald-400"
												: "border-zinc-700 bg-zinc-800 text-zinc-500"
										}`}
									>
										{telemQuest.enabled !== false ? "Active" : "Disabled"}
									</button>
									{telemQuest.reward_type === "nft" && (
										<Badge variant="outline" className={`border-cyan-500/40 bg-cyan-500/10 ${telemTheme.accentTextClass} font-mono text-[10px]`}>
											ERC-1155 Pass #{telemQuest.nft_token_id ?? 0}
										</Badge>
									)}
									<Badge variant="outline" className="border-cyan-500/40 text-cyan-400 font-mono">
										telemetry_pass
									</Badge>
								</div>
							</div>
							<CardDescription>
								Rewards network telemetry & verified trading volume with DePIN Genesis allocation.
							</CardDescription>
						</CardHeader>
						<CardContent className="space-y-4">
							{/* Reward Mode & Presets Selection */}
							<div className="space-y-2 p-3 rounded-xl border border-border/60 bg-muted/20">
								<div className="flex items-center justify-between flex-wrap gap-2">
									<Label className="text-xs text-muted-foreground font-semibold">Reward Type</Label>
									<div className="flex items-center gap-1.5 flex-wrap">
										<span className="text-[10px] text-muted-foreground font-mono">Fill Preset:</span>
										<Button
											type="button"
											variant="ghost"
											size="sm"
											className="h-6 px-1.5 text-[10px] text-cyan-400 hover:text-cyan-300 font-bold border border-cyan-500/20 bg-cyan-500/5"
											onClick={() => applyTokenPresetToQuest("telemetry_pass", "token0")}
										>
											💎 #0 (10k)
										</Button>
										<Button
											type="button"
											variant="ghost"
											size="sm"
											className="h-6 px-1.5 text-[10px] text-amber-400 hover:text-amber-300 font-bold border border-amber-500/20 bg-amber-500/5"
											onClick={() => applyTokenPresetToQuest("telemetry_pass", "token1")}
										>
											✨ #1 (25k)
										</Button>
										<Button
											type="button"
											variant="ghost"
											size="sm"
											className="h-6 px-1.5 text-[10px] text-purple-400 hover:text-purple-300 font-bold border border-purple-500/20 bg-purple-500/5"
											onClick={() => applyTokenPresetToQuest("telemetry_pass", "token2")}
										>
											👑 #2 (50k)
										</Button>
									</div>
								</div>
								<div className="grid grid-cols-2 gap-2">
									<button
										type="button"
										onClick={() =>
											setFormData({
												...formData,
												config: {
													...formData.config,
													quests: {
														...formData.config?.quests,
														telemetry_pass: {
															...telemQuest,
															reward_type: "token",
														},
													},
												},
											})
										}
										className={`px-3 py-2 rounded-lg text-xs font-bold border text-left transition-all flex items-center justify-between ${
											telemQuest.reward_type !== "nft"
												? "border-cyan-500 bg-cyan-500/15 text-cyan-300 shadow-sm"
												: "border-border/60 bg-muted/40 text-muted-foreground hover:border-border"
										}`}
									>
										<span>🪙 $DEPTH Token (Direct)</span>
										{telemQuest.reward_type !== "nft" && <Check className="h-3.5 w-3.5 text-cyan-400" />}
									</button>
									<button
										type="button"
										onClick={() =>
											setFormData({
												...formData,
												config: {
													...formData.config,
													quests: {
														...formData.config?.quests,
														telemetry_pass: {
															...telemQuest,
															reward_type: "nft",
															nft_contract_address: telemQuest.nft_contract_address || "0x29ce393672507c185a5E9Bc2e721E8009e3520C8",
															nft_chain_id: telemQuest.nft_chain_id || 42161,
															nft_token_id: telemQuest.nft_token_id ?? 0,
															nft_name: telemQuest.nft_name || "DepthSight Genesis Pass",
															nft_image_url: telemQuest.nft_image_url || "/nft/genesis_pass_0.jpg",
															nft_multiplier: telemQuest.nft_multiplier || "1.0x",
															nft_nominal: telemQuest.nft_nominal || 10_000,
															nft_max_supply: telemQuest.nft_max_supply || 1000,
															nft_color_theme: telemQuest.nft_color_theme || "cyan",
														},
													},
												},
											})
										}
										className={`px-3 py-2 rounded-lg text-xs font-bold border text-left transition-all flex items-center justify-between ${
											telemQuest.reward_type === "nft"
												? "border-cyan-500 bg-cyan-500/20 text-cyan-300 shadow-sm"
												: "border-border/60 bg-muted/40 text-muted-foreground hover:border-border"
										}`}
									>
										<span>💎 ERC-1155 NFT Pass</span>
										{telemQuest.reward_type === "nft" && <Check className="h-3.5 w-3.5 text-cyan-400" />}
									</button>
								</div>
							</div>

							<div className="space-y-1.5">
								<Label className="text-xs text-muted-foreground font-semibold">Quest Display Title</Label>
								<Input
									value={telemQuest.title || "DepthSight Genesis Pass"}
									onChange={(e) =>
										setFormData({
											...formData,
											config: {
												...formData.config,
												quests: {
													...formData.config?.quests,
													telemetry_pass: {
														...telemQuest,
														title: e.target.value,
													},
												},
											},
										})
									}
									placeholder="DepthSight Genesis Pass"
								/>
							</div>

							<div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
								<div className="space-y-1">
									<Label className="text-xs text-muted-foreground font-semibold">
										{telemQuest.reward_type === "nft" ? "Nominal ($DEPTH)" : "Reward ($DEPTH)"}
									</Label>
									<Input
										type="number"
										value={telemQuest.reward}
										onChange={(e) => {
											const val = Number(e.target.value);
											setFormData({
												...formData,
												config: {
													...formData.config,
													quests: {
														...formData.config?.quests,
														telemetry_pass: {
															...telemQuest,
															reward: val,
															nft_nominal: telemQuest.reward_type === "nft" ? val : telemQuest.nft_nominal,
														},
													},
												},
											});
										}}
										className="font-mono font-bold"
									/>
								</div>
								<div className="space-y-1">
									<Label className="text-xs text-muted-foreground font-semibold">Total Slots (Supply)</Label>
									<Input
										type="number"
										value={telemQuest.total_slots}
										onChange={(e) => {
											const val = Number(e.target.value);
											setFormData({
												...formData,
												config: {
													...formData.config,
													quests: {
														...formData.config?.quests,
														telemetry_pass: {
															...telemQuest,
															total_slots: val,
															nft_max_supply: telemQuest.reward_type === "nft" ? val : telemQuest.nft_max_supply,
														},
													},
												},
											});
										}}
										className="font-mono font-bold"
									/>
								</div>
								<div className="space-y-1">
									<Label className="text-xs text-muted-foreground font-semibold">Min Volume ($)</Label>
									<Input
										type="number"
										value={telemQuest.min_volume_usd}
										onChange={(e) =>
											setFormData({
												...formData,
												config: {
													...formData.config,
													quests: {
														...formData.config?.quests,
														telemetry_pass: {
															...telemQuest,
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

							{/* NFT Specific Configuration Fields */}
							{telemQuest.reward_type === "nft" && (
								<div className={`p-3.5 rounded-xl border space-y-3 transition-all ${telemTheme.borderClass} ${telemTheme.bgGradientClass}`}>
									<div className="flex items-center justify-between">
										<span className={`text-xs font-bold flex items-center gap-1.5 ${telemTheme.accentTextClass}`}>
											<Sparkles className="h-3.5 w-3.5" />
											Thirdweb Edition NFT Voucher Properties (Token #{telemQuest.nft_token_id ?? 0})
										</span>
										<Badge variant="outline" className={`text-[10px] ${telemTheme.badgeClass}`}>
											Arbitrum One (Chain 42161)
										</Badge>
									</div>

									{/* Card Holographic Theme Selector */}
									<div className="space-y-1.5 p-2 rounded-lg bg-black/40 border border-white/5">
										<div className="flex items-center justify-between">
											<Label className="text-[11px] font-semibold text-muted-foreground flex items-center gap-1">
												<Palette className="h-3 w-3 text-primary" />
												Card Holographic Theme
											</Label>
											<span className={`font-mono text-[10px] font-bold ${telemTheme.accentTextClass}`}>
												{telemTheme.label}
											</span>
										</div>
										<div className="flex items-center gap-1.5 flex-wrap">
											{Object.values(COLOR_THEMES).map((th) => {
												const isSel = (telemQuest.nft_color_theme || "cyan") === th.id;
												return (
													<button
														key={th.id}
														type="button"
														onClick={() =>
															setFormData({
																...formData,
																config: {
																	...formData.config,
																	quests: {
																		...formData.config?.quests,
																		telemetry_pass: {
																			...telemQuest,
																			nft_color_theme: th.id,
																		},
																	},
																},
															})
														}
														className={`flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-xs font-semibold border transition-all ${
															isSel
																? `${th.borderClass} ${th.badgeClass} shadow-sm font-bold ring-1 ring-white/20`
																: "border-border/60 bg-muted/40 text-muted-foreground hover:border-border"
														}`}
													>
														<span className="h-2.5 w-2.5 rounded-full" style={{ backgroundColor: th.color }} />
														<span>{th.label}</span>
													</button>
												);
											})}
										</div>
									</div>

									<div className="flex gap-3 items-center p-2 rounded-lg bg-muted/40 border">
										<div className={`h-16 w-11 rounded overflow-hidden border shrink-0 shadow-sm bg-black`} style={{ borderColor: `${telemTheme.color}80` }}>
											<img
												src={getNftPassImageUrl(telemQuest.nft_token_id ?? 0, telemQuest.nft_image_url)}
												alt=""
												className="h-full w-full object-cover"
												onError={(e) => {
													const target = e.currentTarget;
													const fallback = getNftPassImageUrl(telemQuest.nft_token_id ?? 0);
													if (target.src !== fallback) target.src = fallback;
												}}
											/>
										</div>
										<div className="grid grid-cols-1 sm:grid-cols-2 gap-2 flex-1">
											<div className="space-y-1">
												<Label className="text-[11px] text-muted-foreground">NFT Name</Label>
												<Input
													value={telemQuest.nft_name || "DepthSight Genesis Pass"}
													onChange={(e) =>
														setFormData({
															...formData,
															config: {
																...formData.config,
																quests: {
																	...formData.config?.quests,
																	telemetry_pass: {
																		...telemQuest,
																		nft_name: e.target.value,
																	},
																},
															},
														})
													}
													className="h-8 text-xs font-semibold"
												/>
											</div>
											<div className="space-y-1">
												<Label className="text-[11px] text-muted-foreground">Mining Multiplier (Boost)</Label>
												<Input
													value={telemQuest.nft_multiplier || "1.0x"}
													onChange={(e) =>
														setFormData({
															...formData,
															config: {
																...formData.config,
																quests: {
																	...formData.config?.quests,
																	telemetry_pass: {
																		...telemQuest,
																		nft_multiplier: e.target.value,
																	},
																},
															},
														})
													}
													className={`h-8 text-xs font-bold font-mono ${telemTheme.accentTextClass}`}
												/>
											</div>
										</div>
									</div>

									<div className="grid grid-cols-1 sm:grid-cols-3 gap-2">
										<div className="sm:col-span-2 space-y-1">
											<Label className="text-[11px] text-muted-foreground">Contract Address (ERC-1155)</Label>
											<Input
												value={telemQuest.nft_contract_address || "0x29ce393672507c185a5E9Bc2e721E8009e3520C8"}
												onChange={(e) =>
													setFormData({
														...formData,
														config: {
															...formData.config,
															quests: {
																...formData.config?.quests,
																telemetry_pass: {
																	...telemQuest,
																	nft_contract_address: e.target.value,
																},
															},
														},
													})
												}
												className="h-8 text-xs font-mono"
											/>
										</div>
										<div className="space-y-1">
											<Label className="text-[11px] text-muted-foreground">Token ID</Label>
											<Input
												type="number"
												value={telemQuest.nft_token_id ?? 0}
												onChange={(e) =>
													setFormData({
														...formData,
														config: {
															...formData.config,
															quests: {
																...formData.config?.quests,
																telemetry_pass: {
																	...telemQuest,
																	nft_token_id: Number(e.target.value),
																},
															},
														},
													})
												}
												className="h-8 text-xs font-mono font-bold"
											/>
										</div>
									</div>

									<div className="space-y-1">
										<Label className="text-[11px] text-muted-foreground flex items-center justify-between">
											<span>Image Path / URL (optional)</span>
											<span className="text-[10px] text-muted-foreground font-mono">default: /nft/genesis_pass_0.jpg</span>
										</Label>
										<Input
											value={telemQuest.nft_image_url || "/nft/genesis_pass_0.jpg"}
											onChange={(e) =>
												setFormData({
													...formData,
													config: {
														...formData.config,
														quests: {
															...formData.config?.quests,
															telemetry_pass: {
																...telemQuest,
																nft_image_url: e.target.value,
															},
														},
													},
												})
											}
											placeholder="/nft/genesis_pass_0.jpg or https://..."
											className="h-8 text-xs font-mono"
										/>
									</div>
								</div>
							)}

							<div className="p-2.5 rounded-lg bg-muted/30 text-xs text-muted-foreground flex justify-between">
								<span>Subtotal Budget:</span>
								<span className="font-bold text-white font-mono">
									{((telemQuest.reward || 0) * (telemQuest.total_slots || 0)).toLocaleString()} $DEPTH
								</span>
							</div>
						</CardContent>
					</Card>

					{/* Quest 2 Config: API Pioneer */}
					<Card className="border border-border/80 shadow-md">
						<CardHeader className="pb-3">
							<div className="flex items-center justify-between">
								<CardTitle className="text-base font-bold flex items-center gap-2">
									<Sparkles className="h-4 w-4 text-amber-400" />
									Quest 2: DepthSight Core Syndicate Pass (#1)
								</CardTitle>
								<div className="flex items-center gap-2">
									<button
										type="button"
										onClick={() =>
											setFormData({
												...formData,
												config: {
													...formData.config,
													quests: {
														...formData.config?.quests,
														api_pioneer: {
															...apiQuest,
															enabled: apiQuest.enabled === false ? true : false,
														},
													},
												},
											})
										}
										className={`text-[10px] font-bold px-2 py-0.5 rounded border transition-all ${
											apiQuest.enabled !== false
												? "border-emerald-500/40 bg-emerald-500/15 text-emerald-400"
												: "border-zinc-700 bg-zinc-800 text-zinc-500"
										}`}
									>
										{apiQuest.enabled !== false ? "Active" : "Disabled"}
									</button>
									{apiQuest.reward_type === "nft" && (
										<Badge variant="outline" className={`border-purple-500/40 bg-purple-500/10 ${apiTheme.accentTextClass} font-mono text-[10px]`}>
											ERC-1155 Pass #{apiQuest.nft_token_id ?? 1}
										</Badge>
									)}
									<Badge variant="outline" className="border-cyan-500/40 text-cyan-400 font-mono">
										api_volume
									</Badge>
								</div>
							</div>
							<CardDescription>
								Rewards users for connecting target exchange API key & achieving trading volume.
							</CardDescription>
						</CardHeader>
						<CardContent className="space-y-4">
							{/* Reward Mode & Presets Selection */}
							<div className="space-y-2 p-3 rounded-xl border border-border/60 bg-muted/20">
								<div className="flex items-center justify-between flex-wrap gap-2">
									<Label className="text-xs text-muted-foreground font-semibold">Reward Type</Label>
									<div className="flex items-center gap-1.5 flex-wrap">
										<span className="text-[10px] text-muted-foreground font-mono">Fill Preset:</span>
										<Button
											type="button"
											variant="ghost"
											size="sm"
											className="h-6 px-1.5 text-[10px] text-cyan-400 hover:text-cyan-300 font-bold border border-cyan-500/20 bg-cyan-500/5"
											onClick={() => applyTokenPresetToQuest("api_pioneer", "token0")}
										>
											💎 #0 (10k)
										</Button>
										<Button
											type="button"
											variant="ghost"
											size="sm"
											className="h-6 px-1.5 text-[10px] text-amber-400 hover:text-amber-300 font-bold border border-amber-500/20 bg-amber-500/5"
											onClick={() => applyTokenPresetToQuest("api_pioneer", "token1")}
										>
											✨ #1 (25k)
										</Button>
										<Button
											type="button"
											variant="ghost"
											size="sm"
											className="h-6 px-1.5 text-[10px] text-purple-400 hover:text-purple-300 font-bold border border-purple-500/20 bg-purple-500/5"
											onClick={() => applyTokenPresetToQuest("api_pioneer", "token2")}
										>
											👑 #2 (50k)
										</Button>
									</div>
								</div>
								<div className="grid grid-cols-2 gap-2">
									<button
										type="button"
										onClick={() =>
											setFormData({
												...formData,
												config: {
													...formData.config,
													quests: {
														...formData.config?.quests,
														api_pioneer: {
															...apiQuest,
															reward_type: "token",
														},
													},
												},
											})
										}
										className={`px-3 py-2 rounded-lg text-xs font-bold border text-left transition-all flex items-center justify-between ${
											apiQuest.reward_type !== "nft"
												? "border-cyan-500 bg-cyan-500/15 text-cyan-300 shadow-sm"
												: "border-border/60 bg-muted/40 text-muted-foreground hover:border-border"
										}`}
									>
										<span>🪙 $DEPTH Token (Direct)</span>
										{apiQuest.reward_type !== "nft" && <Check className="h-3.5 w-3.5 text-cyan-400" />}
									</button>
									<button
										type="button"
										onClick={() =>
											setFormData({
												...formData,
												config: {
													...formData.config,
													quests: {
														...formData.config?.quests,
														api_pioneer: {
															...apiQuest,
															reward_type: "nft",
															nft_contract_address: apiQuest.nft_contract_address || "0x29ce393672507c185a5E9Bc2e721E8009e3520C8",
															nft_chain_id: apiQuest.nft_chain_id || 42161,
															nft_token_id: apiQuest.nft_token_id ?? 1,
															nft_name: apiQuest.nft_name || "DepthSight Core Syndicate Pass",
															nft_image_url: apiQuest.nft_image_url || "/nft/genesis_pass_1.jpg",
															nft_multiplier: apiQuest.nft_multiplier || "1.5x",
															nft_nominal: apiQuest.nft_nominal || 25_000,
															nft_max_supply: apiQuest.nft_max_supply || 300,
														},
													},
												},
											})
										}
										className={`px-3 py-2 rounded-lg text-xs font-bold border text-left transition-all flex items-center justify-between ${
											apiQuest.reward_type === "nft"
												? "border-purple-500 bg-purple-500/20 text-purple-300 shadow-sm"
												: "border-border/60 bg-muted/40 text-muted-foreground hover:border-border"
										}`}
									>
										<span>💎 ERC-1155 NFT Pass</span>
										{apiQuest.reward_type === "nft" && <Check className="h-3.5 w-3.5 text-purple-400" />}
									</button>
								</div>
							</div>

							<div className="space-y-1.5">
								<Label className="text-xs text-muted-foreground font-semibold">Quest Display Title</Label>
								<Input
									value={apiQuest.title || `${currentExLabel} API Pioneer`}
									onChange={(e) =>
										setFormData({
											...formData,
											config: {
												...formData.config,
												quests: {
													...formData.config?.quests,
													api_pioneer: {
														...apiQuest,
														title: e.target.value,
													},
												},
											},
										})
									}
									placeholder={`${currentExLabel} API Pioneer`}
								/>
							</div>

							<div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
								<div className="space-y-1">
									<Label className="text-xs text-muted-foreground font-semibold">
										{apiQuest.reward_type === "nft" ? "Nominal ($DEPTH)" : "Reward ($DEPTH)"}
									</Label>
									<Input
										type="number"
										value={apiQuest.reward}
										onChange={(e) => {
											const val = Number(e.target.value);
											setFormData({
												...formData,
												config: {
													...formData.config,
													quests: {
														...formData.config?.quests,
														api_pioneer: {
															...apiQuest,
															reward: val,
															nft_nominal: apiQuest.reward_type === "nft" ? val : apiQuest.nft_nominal,
														},
													},
												},
											});
										}}
										className="font-mono font-bold"
									/>
								</div>
								<div className="space-y-1">
									<Label className="text-xs text-muted-foreground font-semibold">Total Slots (Supply)</Label>
									<Input
										type="number"
										value={apiQuest.total_slots}
										onChange={(e) => {
											const val = Number(e.target.value);
											setFormData({
												...formData,
												config: {
													...formData.config,
													quests: {
														...formData.config?.quests,
														api_pioneer: {
															...apiQuest,
															total_slots: val,
															nft_max_supply: apiQuest.reward_type === "nft" ? val : apiQuest.nft_max_supply,
														},
													},
												},
											});
										}}
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

							{/* NFT Specific Configuration Fields */}
							{apiQuest.reward_type === "nft" && (
								<div className={`p-3.5 rounded-xl border space-y-3 transition-all ${apiTheme.borderClass} ${apiTheme.bgGradientClass}`}>
									<div className="flex items-center justify-between">
										<span className={`text-xs font-bold flex items-center gap-1.5 ${apiTheme.accentTextClass}`}>
											<Sparkles className="h-3.5 w-3.5" />
											Thirdweb Edition NFT Voucher Properties (Token #{apiQuest.nft_token_id ?? 1})
										</span>
										<Badge variant="outline" className={`text-[10px] ${apiTheme.badgeClass}`}>
											Arbitrum One (Chain 42161)
										</Badge>
									</div>

									{/* Card Holographic Theme Selector */}
									<div className="space-y-1.5 p-2 rounded-lg bg-black/40 border border-white/5">
										<div className="flex items-center justify-between">
											<Label className="text-[11px] font-semibold text-muted-foreground flex items-center gap-1">
												<Palette className="h-3 w-3 text-primary" />
												Card Holographic Theme
											</Label>
											<span className={`font-mono text-[10px] font-bold ${apiTheme.accentTextClass}`}>
												{apiTheme.label}
											</span>
										</div>
										<div className="flex items-center gap-1.5 flex-wrap">
											{Object.values(COLOR_THEMES).map((th) => {
												const isSel = (apiQuest.nft_color_theme || "gold") === th.id;
												return (
													<button
														key={th.id}
														type="button"
														onClick={() =>
															setFormData({
																...formData,
																config: {
																	...formData.config,
																	quests: {
																		...formData.config?.quests,
																		api_pioneer: {
																			...apiQuest,
																			nft_color_theme: th.id,
																		},
																	},
																},
															})
														}
														className={`flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-xs font-semibold border transition-all ${
															isSel
																? `${th.borderClass} ${th.badgeClass} shadow-sm font-bold ring-1 ring-white/20`
																: "border-border/60 bg-muted/40 text-muted-foreground hover:border-border"
														}`}
													>
														<span className="h-2.5 w-2.5 rounded-full" style={{ backgroundColor: th.color }} />
														<span>{th.label}</span>
													</button>
												);
											})}
										</div>
									</div>

									<div className="flex gap-3 items-center">
										<div className="h-20 w-14 rounded-lg border overflow-hidden bg-black/60 shrink-0 shadow-md relative" style={{ borderColor: `${apiTheme.color}80` }}>
											<img
												src={getNftPassImageUrl(apiQuest.nft_token_id ?? 1, apiQuest.nft_image_url)}
												alt="NFT Preview"
												className="h-full w-full object-cover"
												onError={(e) => {
													const target = e.currentTarget;
													const fallback = getNftPassImageUrl(apiQuest.nft_token_id ?? 1);
													if (target.src !== fallback) target.src = fallback;
												}}
											/>
										</div>
										<div className="grid grid-cols-1 sm:grid-cols-2 gap-2 flex-1">
											<div className="space-y-1">
												<Label className="text-[11px] text-muted-foreground">NFT Name</Label>
												<Input
													value={apiQuest.nft_name || "DepthSight Core Syndicate Pass"}
													onChange={(e) =>
														setFormData({
															...formData,
															config: {
																...formData.config,
																quests: {
																	...formData.config?.quests,
																	api_pioneer: {
																		...apiQuest,
																		nft_name: e.target.value,
																	},
																},
															},
														})
													}
													className="h-8 text-xs font-semibold"
												/>
											</div>
											<div className="space-y-1">
												<Label className="text-[11px] text-muted-foreground">Mining Multiplier</Label>
												<Input
													value={apiQuest.nft_multiplier || "1.5x"}
													onChange={(e) =>
														setFormData({
															...formData,
															config: {
																...formData.config,
																quests: {
																	...formData.config?.quests,
																	api_pioneer: {
																		...apiQuest,
																		nft_multiplier: e.target.value,
																	},
																},
															},
														})
													}
													className={`h-8 text-xs font-bold font-mono ${apiTheme.accentTextClass}`}
												/>
											</div>
										</div>
									</div>

									<div className="grid grid-cols-1 sm:grid-cols-3 gap-2">
										<div className="sm:col-span-2 space-y-1">
											<Label className="text-[11px] text-muted-foreground">Contract Address (ERC-1155)</Label>
											<Input
												value={apiQuest.nft_contract_address || "0x29ce393672507c185a5E9Bc2e721E8009e3520C8"}
												onChange={(e) =>
													setFormData({
														...formData,
														config: {
															...formData.config,
															quests: {
																...formData.config?.quests,
																api_pioneer: {
																	...apiQuest,
																	nft_contract_address: e.target.value,
																},
															},
														},
													})
												}
												className="h-8 text-xs font-mono"
											/>
										</div>
										<div className="space-y-1">
											<Label className="text-[11px] text-muted-foreground">Token ID</Label>
											<Input
												type="number"
												value={apiQuest.nft_token_id ?? 1}
												onChange={(e) =>
													setFormData({
														...formData,
														config: {
															...formData.config,
															quests: {
																...formData.config?.quests,
																api_pioneer: {
																	...apiQuest,
																	nft_token_id: Number(e.target.value),
																},
															},
														},
													})
												}
												className="h-8 text-xs font-mono font-bold"
											/>
										</div>
									</div>

									<div className="space-y-1">
										<Label className="text-[11px] text-muted-foreground flex items-center justify-between">
											<span>Image Path / URL (optional)</span>
											<span className="text-[10px] text-muted-foreground font-mono">default: /nft/genesis_pass_1.jpg</span>
										</Label>
										<Input
											value={apiQuest.nft_image_url || "/nft/genesis_pass_1.jpg"}
											onChange={(e) =>
												setFormData({
													...formData,
													config: {
														...formData.config,
														quests: {
															...formData.config?.quests,
															api_pioneer: {
																...apiQuest,
																nft_image_url: e.target.value,
															},
														},
													},
												})
											}
											placeholder="/nft/genesis_pass_1.jpg or https://..."
											className="h-8 text-xs font-mono"
										/>
									</div>
								</div>
							)}

							<div className="p-2.5 rounded-lg bg-muted/30 text-xs text-muted-foreground flex justify-between">
								<span>Subtotal Budget:</span>
								<span className="font-bold text-white font-mono">
									{((apiQuest.reward || 0) * (apiQuest.total_slots || 0)).toLocaleString()} $DEPTH
								</span>
							</div>
						</CardContent>
					</Card>

					{/* Quest 3 Config: Node Runner */}
					<Card className="border border-border/80 shadow-md">
						<CardHeader className="pb-3">
							<div className="flex items-center justify-between">
								<CardTitle className="text-base font-bold flex items-center gap-2">
									<Coins className="h-4 w-4 text-purple-400" />
									Quest 3: DepthSight Apex Syndicate Pass (#2)
								</CardTitle>
								<div className="flex items-center gap-2">
									<button
										type="button"
										onClick={() =>
											setFormData({
												...formData,
												config: {
													...formData.config,
													quests: {
														...formData.config?.quests,
														node_runner: {
															...nodeQuest,
															enabled: nodeQuest.enabled === false ? true : false,
														},
													},
												},
											})
										}
										className={`text-[10px] font-bold px-2 py-0.5 rounded border transition-all ${
											nodeQuest.enabled !== false
												? "border-emerald-500/40 bg-emerald-500/15 text-emerald-400"
												: "border-zinc-700 bg-zinc-800 text-zinc-500"
										}`}
									>
										{nodeQuest.enabled !== false ? "Active" : "Disabled"}
									</button>
									{nodeQuest.reward_type === "nft" && (
										<Badge variant="outline" className={`border-purple-500/40 bg-purple-500/10 ${nodeTheme.accentTextClass} font-mono text-[10px]`}>
											ERC-1155 Pass #{nodeQuest.nft_token_id ?? 2}
										</Badge>
									)}
									<Badge variant="outline" className="border-emerald-500/40 text-emerald-400 font-mono">
										node_runner
									</Badge>
								</div>
							</div>
							<CardDescription>
								Rewards active nodes with longevity, wallet binding, and live {currentExLabel} trades.
							</CardDescription>
						</CardHeader>
						<CardContent className="space-y-4">
							{/* Reward Mode & Presets Selection */}
							<div className="space-y-2 p-3 rounded-xl border border-border/60 bg-muted/20">
								<div className="flex items-center justify-between flex-wrap gap-2">
									<Label className="text-xs text-muted-foreground font-semibold">Reward Type</Label>
									<div className="flex items-center gap-1.5 flex-wrap">
										<span className="text-[10px] text-muted-foreground font-mono">Fill Preset:</span>
										<Button
											type="button"
											variant="ghost"
											size="sm"
											className="h-6 px-1.5 text-[10px] text-cyan-400 hover:text-cyan-300 font-bold border border-cyan-500/20 bg-cyan-500/5"
											onClick={() => applyTokenPresetToQuest("node_runner", "token0")}
										>
											💎 #0 (10k)
										</Button>
										<Button
											type="button"
											variant="ghost"
											size="sm"
											className="h-6 px-1.5 text-[10px] text-amber-400 hover:text-amber-300 font-bold border border-amber-500/20 bg-amber-500/5"
											onClick={() => applyTokenPresetToQuest("node_runner", "token1")}
										>
											✨ #1 (25k)
										</Button>
										<Button
											type="button"
											variant="ghost"
											size="sm"
											className="h-6 px-1.5 text-[10px] text-purple-400 hover:text-purple-300 font-bold border border-purple-500/20 bg-purple-500/5"
											onClick={() => applyTokenPresetToQuest("node_runner", "token2")}
										>
											👑 #2 (50k)
										</Button>
									</div>
								</div>
								<div className="grid grid-cols-2 gap-2">
									<button
										type="button"
										onClick={() =>
											setFormData({
												...formData,
												config: {
													...formData.config,
													quests: {
														...formData.config?.quests,
														node_runner: {
															...nodeQuest,
															reward_type: "token",
														},
													},
												},
											})
										}
										className={`px-3 py-2 rounded-lg text-xs font-bold border text-left transition-all flex items-center justify-between ${
											nodeQuest.reward_type !== "nft"
												? "border-emerald-500 bg-emerald-500/15 text-emerald-300 shadow-sm"
												: "border-border/60 bg-muted/40 text-muted-foreground hover:border-border"
										}`}
									>
										<span>🪙 $DEPTH Token (Direct)</span>
										{nodeQuest.reward_type !== "nft" && <Check className="h-3.5 w-3.5 text-emerald-400" />}
									</button>
									<button
										type="button"
										onClick={() =>
											setFormData({
												...formData,
												config: {
													...formData.config,
													quests: {
														...formData.config?.quests,
														node_runner: {
															...nodeQuest,
															reward_type: "nft",
															nft_contract_address: nodeQuest.nft_contract_address || "0x29ce393672507c185a5E9Bc2e721E8009e3520C8",
															nft_chain_id: nodeQuest.nft_chain_id || 42161,
															nft_token_id: nodeQuest.nft_token_id ?? 2,
															nft_name: nodeQuest.nft_name || "DepthSight Apex Syndicate Pass",
															nft_image_url: nodeQuest.nft_image_url || "/nft/genesis_pass_2.jpg",
															nft_multiplier: nodeQuest.nft_multiplier || "2.0x",
															nft_nominal: nodeQuest.nft_nominal || 50_000,
															nft_max_supply: nodeQuest.nft_max_supply || 50,
														},
													},
												},
											})
										}
										className={`px-3 py-2 rounded-lg text-xs font-bold border text-left transition-all flex items-center justify-between ${
											nodeQuest.reward_type === "nft"
												? "border-purple-500 bg-purple-500/20 text-purple-300 shadow-sm"
												: "border-border/60 bg-muted/40 text-muted-foreground hover:border-border"
										}`}
									>
										<span>👑 ERC-1155 NFT Pass</span>
										{nodeQuest.reward_type === "nft" && <Check className="h-3.5 w-3.5 text-purple-400" />}
									</button>
								</div>
							</div>

							<div className="space-y-1.5">
								<Label className="text-xs text-muted-foreground font-semibold">Quest Display Title</Label>
								<Input
									value={nodeQuest.title || "Node Runner Veteran"}
									onChange={(e) =>
										setFormData({
											...formData,
											config: {
												...formData.config,
												quests: {
													...formData.config?.quests,
													node_runner: {
														...nodeQuest,
														title: e.target.value,
													},
												},
											},
										})
									}
									placeholder="Node Runner Veteran"
								/>
							</div>

							<div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
								<div className="space-y-1">
									<Label className="text-xs text-muted-foreground font-semibold">
										{nodeQuest.reward_type === "nft" ? "Nominal ($DEPTH)" : "Reward ($DEPTH)"}
									</Label>
									<Input
										type="number"
										value={nodeQuest.reward}
										onChange={(e) => {
											const val = Number(e.target.value);
											setFormData({
												...formData,
												config: {
													...formData.config,
													quests: {
														...formData.config?.quests,
														node_runner: {
															...nodeQuest,
															reward: val,
															nft_nominal: nodeQuest.reward_type === "nft" ? val : nodeQuest.nft_nominal,
														},
													},
												},
											});
										}}
										className="font-mono font-bold"
									/>
								</div>
								<div className="space-y-1">
									<Label className="text-xs text-muted-foreground font-semibold">Total Slots (Supply)</Label>
									<Input
										type="number"
										value={nodeQuest.total_slots}
										onChange={(e) => {
											const val = Number(e.target.value);
											setFormData({
												...formData,
												config: {
													...formData.config,
													quests: {
														...formData.config?.quests,
														node_runner: {
															...nodeQuest,
															total_slots: val,
															nft_max_supply: nodeQuest.reward_type === "nft" ? val : nodeQuest.nft_max_supply,
														},
													},
												},
											});
										}}
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

							{/* NFT Specific Configuration Fields for Quest 2 */}
							{nodeQuest.reward_type === "nft" && (
								<div className={`p-3.5 rounded-xl border space-y-3 transition-all ${nodeTheme.borderClass} ${nodeTheme.bgGradientClass}`}>
									<div className="flex items-center justify-between">
										<span className={`text-xs font-bold flex items-center gap-1.5 ${nodeTheme.accentTextClass}`}>
											<Sparkles className="h-3.5 w-3.5" />
											Thirdweb Edition NFT Voucher Properties (Token #{nodeQuest.nft_token_id ?? 2})
										</span>
										<Badge variant="outline" className={`text-[10px] ${nodeTheme.badgeClass}`}>
											Arbitrum One (Chain 42161)
										</Badge>
									</div>

									{/* Card Holographic Theme Selector */}
									<div className="space-y-1.5 p-2 rounded-lg bg-black/40 border border-white/5">
										<div className="flex items-center justify-between">
											<Label className="text-[11px] font-semibold text-muted-foreground flex items-center gap-1">
												<Palette className="h-3 w-3 text-primary" />
												Card Holographic Theme
											</Label>
											<span className={`font-mono text-[10px] font-bold ${nodeTheme.accentTextClass}`}>
												{nodeTheme.label}
											</span>
										</div>
										<div className="flex items-center gap-1.5 flex-wrap">
											{Object.values(COLOR_THEMES).map((th) => {
												const isSel = (nodeQuest.nft_color_theme || "purple") === th.id;
												return (
													<button
														key={th.id}
														type="button"
														onClick={() =>
															setFormData({
																...formData,
																config: {
																	...formData.config,
																	quests: {
																		...formData.config?.quests,
																		node_runner: {
																			...nodeQuest,
																			nft_color_theme: th.id,
																		},
																	},
																},
															})
														}
														className={`flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-xs font-semibold border transition-all ${
															isSel
																? `${th.borderClass} ${th.badgeClass} shadow-sm font-bold ring-1 ring-white/20`
																: "border-border/60 bg-muted/40 text-muted-foreground hover:border-border"
														}`}
													>
														<span className="h-2.5 w-2.5 rounded-full" style={{ backgroundColor: th.color }} />
														<span>{th.label}</span>
													</button>
												);
											})}
										</div>
									</div>

									<div className="flex gap-3 items-center">
										<div className="h-20 w-14 rounded-lg border overflow-hidden bg-black/60 shrink-0 shadow-md relative" style={{ borderColor: `${nodeTheme.color}80` }}>
											<img
												src={getNftPassImageUrl(nodeQuest.nft_token_id ?? 2, nodeQuest.nft_image_url)}
												alt="NFT Preview"
												className="h-full w-full object-cover"
												onError={(e) => {
													const target = e.currentTarget;
													const fallback = getNftPassImageUrl(nodeQuest.nft_token_id ?? 2);
													if (target.src !== fallback) target.src = fallback;
												}}
											/>
										</div>
										<div className="grid grid-cols-1 sm:grid-cols-2 gap-2 flex-1">
											<div className="space-y-1">
												<Label className="text-[11px] text-muted-foreground">NFT Name</Label>
												<Input
													value={nodeQuest.nft_name || "DepthSight Apex Syndicate Pass"}
													onChange={(e) =>
														setFormData({
															...formData,
															config: {
																...formData.config,
																quests: {
																	...formData.config?.quests,
																	node_runner: {
																		...nodeQuest,
																		nft_name: e.target.value,
																	},
																},
															},
														})
													}
													className="h-8 text-xs font-semibold"
												/>
											</div>
											<div className="space-y-1">
												<Label className="text-[11px] text-muted-foreground">Mining Multiplier</Label>
												<Input
													value={nodeQuest.nft_multiplier || "2.0x"}
													onChange={(e) =>
														setFormData({
															...formData,
															config: {
																...formData.config,
																quests: {
																	...formData.config?.quests,
																	node_runner: {
																		...nodeQuest,
																		nft_multiplier: e.target.value,
																	},
																},
															},
														})
													}
													className={`h-8 text-xs font-bold font-mono ${nodeTheme.accentTextClass}`}
												/>
											</div>
										</div>
									</div>

									<div className="grid grid-cols-1 sm:grid-cols-3 gap-2">
										<div className="sm:col-span-2 space-y-1">
											<Label className="text-[11px] text-muted-foreground">Contract Address (ERC-1155)</Label>
											<Input
												value={nodeQuest.nft_contract_address || "0x29ce393672507c185a5E9Bc2e721E8009e3520C8"}
												onChange={(e) =>
													setFormData({
														...formData,
														config: {
															...formData.config,
															quests: {
																...formData.config?.quests,
																node_runner: {
																	...nodeQuest,
																	nft_contract_address: e.target.value,
																},
															},
														},
													})
												}
												className="h-8 text-xs font-mono"
											/>
										</div>
										<div className="space-y-1">
											<Label className="text-[11px] text-muted-foreground">Token ID</Label>
											<Input
												type="number"
												value={nodeQuest.nft_token_id ?? 2}
												onChange={(e) =>
													setFormData({
														...formData,
														config: {
															...formData.config,
															quests: {
																...formData.config?.quests,
																node_runner: {
																	...nodeQuest,
																	nft_token_id: Number(e.target.value),
																},
															},
														},
													})
												}
												className="h-8 text-xs font-mono font-bold"
											/>
										</div>
									</div>

									<div className="space-y-1">
										<Label className="text-[11px] text-muted-foreground flex items-center justify-between">
											<span>Image Path / URL (optional)</span>
											<span className="text-[10px] text-muted-foreground font-mono">default: /nft/genesis_pass_2.jpg</span>
										</Label>
										<Input
											value={nodeQuest.nft_image_url || "/nft/genesis_pass_2.jpg"}
											onChange={(e) =>
												setFormData({
													...formData,
													config: {
														...formData.config,
														quests: {
															...formData.config?.quests,
															node_runner: {
																...nodeQuest,
																nft_image_url: e.target.value,
															},
														},
													},
												})
											}
											placeholder="/nft/genesis_pass_2.jpg or https://..."
											className="h-8 text-xs font-mono"
										/>
									</div>
								</div>
							)}

							<div className="p-2.5 rounded-lg bg-muted/30 text-xs text-muted-foreground flex justify-between">
								<span>Subtotal Budget:</span>
								<span className="font-bold text-white font-mono">
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

							{/* Simulated Banner with Dynamic Exchange Theme */}
							<div
								className="overflow-hidden rounded-xl border p-3.5 shadow-md transition-all relative"
								style={{
									borderColor: `${currentBrandColor}40`,
									background: `linear-gradient(135deg, ${currentBrandColor}18 0%, rgba(15, 23, 42, 0.95) 55%, ${currentBrandColor}08 100%)`,
								}}
							>
								<div className="flex items-center gap-3">
									<div
										className="h-11 w-11 shrink-0 rounded-xl border p-1.5 flex items-center justify-center bg-card/90 shadow-sm"
										style={{ borderColor: `${currentBrandColor}60` }}
									>
										{currentExLogo ? (
											<img src={currentExLogo} alt={currentExLabel} className="h-full w-full object-contain" />
										) : (
											<Gift className="h-6 w-6 text-primary" />
										)}
									</div>
									<div className="min-w-0 flex-1">
										<div className="flex items-center gap-1.5 flex-wrap">
											<h4 className="text-xs sm:text-sm font-bold text-white truncate">
												{formData.campaign_name || `${currentExLabel} Launch Airdrop`}
											</h4>
											{formData.admin_only ? (
												<span className="rounded border border-amber-500/40 bg-amber-500/15 px-1.5 py-0.5 text-[9px] font-bold text-amber-400">
													PREVIEW
												</span>
											) : (
												<span className="rounded border border-emerald-500/40 bg-emerald-500/15 px-1.5 py-0.5 text-[9px] font-bold text-emerald-400">
													LIVE
												</span>
											)}
										</div>
										<p className="text-[10px] text-zinc-300 mt-0.5">
											{totalQuestsSlots} slots • {(formData.total_pool / 1_000_000).toFixed(1)}M $DEPTH Pool
										</p>
									</div>
								</div>
							</div>

							{/* Simulated Quest Cards (Order: #0 -> #1 -> #2) */}
							<div className="space-y-2.5">
								{/* Quest 1: Genesis Pass (#0) */}
								{telemQuest.enabled !== false && (
									<div className={`p-3 rounded-xl border bg-card/40 space-y-2 transition-all ${
										telemQuest.reward_type === "nft"
											? `${telemTheme.borderClass} ${telemTheme.glowClass} ${telemTheme.bgGradientClass}`
											: "border-border/80"
									}`}>
										<div className="flex justify-between items-center text-xs">
											<span className="font-bold text-white flex items-center gap-2">
												{telemQuest.reward_type === "nft" ? (
													<div className="h-8 w-5 rounded overflow-hidden border shrink-0 shadow-sm" style={{ borderColor: `${telemTheme.color}80` }}>
														<img
															src={getNftPassImageUrl(telemQuest.nft_token_id ?? 0, telemQuest.nft_image_url)}
															alt=""
															className="h-full w-full object-cover"
															onError={(e) => {
																const target = e.currentTarget;
																const fallback = getNftPassImageUrl(telemQuest.nft_token_id ?? 0);
																if (target.src !== fallback) target.src = fallback;
															}}
														/>
													</div>
												) : (
													<Sparkles className="h-3.5 w-3.5 text-cyan-400 shrink-0" />
												)}
												<span className="truncate max-w-[180px]">
													{telemQuest.title || "DepthSight Genesis Pass"}
												</span>
											</span>
											{telemQuest.reward_type === "nft" ? (
												<div className="flex items-center gap-1.5 shrink-0">
													<span className={`rounded font-mono font-bold text-[10px] px-1.5 py-0.5 border ${telemTheme.badgeClass}`}>
														{telemQuest.nft_token_id === 0 || telemQuest.nft_multiplier === "1.0x" ? "1:1 Voucher" : telemQuest.nft_multiplier || "1.0x"}
													</span>
													<span className={`font-mono font-bold text-xs ${telemTheme.accentTextClass}`}>
														Pass #{telemQuest.nft_token_id ?? 0}
													</span>
												</div>
											) : (
												<span className="font-mono font-bold text-cyan-400">
													+{telemQuest.reward?.toLocaleString()} $DEPTH
												</span>
											)}
										</div>
										<div className="flex items-center justify-between text-[11px] text-muted-foreground">
											<span>Min volume: ${telemQuest.min_volume_usd?.toLocaleString()} • Slots: {telemQuest.total_slots}</span>
											{telemQuest.reward_type === "nft" && (
												<span className={`text-[10px] font-mono font-bold ${telemTheme.accentTextClass}`}>
													{telemQuest.reward?.toLocaleString()} $DEPTH at TGE
												</span>
											)}
										</div>
									</div>
								)}

								{/* Quest 2: Core Syndicate Pass (#1) */}
								{apiQuest.enabled !== false && (
									<div className={`p-3 rounded-xl border bg-card/40 space-y-2 transition-all ${
										apiQuest.reward_type === "nft"
											? `${apiTheme.borderClass} ${apiTheme.glowClass} ${apiTheme.bgGradientClass}`
											: "border-border/80"
									}`}>
										<div className="flex justify-between items-center text-xs">
											<span className="font-bold text-white flex items-center gap-2">
												{apiQuest.reward_type === "nft" ? (
													<div className="h-8 w-5 rounded overflow-hidden border shrink-0 shadow-sm" style={{ borderColor: `${apiTheme.color}80` }}>
														<img
															src={getNftPassImageUrl(apiQuest.nft_token_id ?? 1, apiQuest.nft_image_url)}
															alt=""
															className="h-full w-full object-cover"
															onError={(e) => {
																const target = e.currentTarget;
																const fallback = getNftPassImageUrl(apiQuest.nft_token_id ?? 1);
																if (target.src !== fallback) target.src = fallback;
															}}
														/>
													</div>
												) : (
													<div className="h-4 w-4 rounded flex items-center justify-center shrink-0">
														{currentExLogo ? (
															<img src={currentExLogo} alt="" className="h-3.5 w-3.5 object-contain" />
														) : (
															<Sparkles className="h-3.5 w-3.5 text-cyan-400" />
														)}
													</div>
												)}
												<span className="truncate max-w-[180px]">
													{apiQuest.title || `${currentExLabel} API Pioneer`}
												</span>
											</span>
											{apiQuest.reward_type === "nft" ? (
												<div className="flex items-center gap-1.5 shrink-0">
													<span className={`rounded font-mono font-bold text-[10px] px-1.5 py-0.5 border ${apiTheme.badgeClass}`}>
														{apiQuest.nft_token_id === 0 || apiQuest.nft_multiplier === "1.0x" ? "1:1 Voucher" : apiQuest.nft_multiplier || "1.5x"}
													</span>
													<span className={`font-mono font-bold text-xs ${apiTheme.accentTextClass}`}>
														Pass #{apiQuest.nft_token_id ?? 1}
													</span>
												</div>
											) : (
												<span className="font-mono font-bold text-cyan-400">
													+{apiQuest.reward?.toLocaleString()} $DEPTH
												</span>
											)}
										</div>
										<div className="flex items-center justify-between text-[11px] text-muted-foreground">
											<span>Min volume: ${apiQuest.min_volume_usd?.toLocaleString()} • Slots: {apiQuest.total_slots}</span>
											{apiQuest.reward_type === "nft" && (
												<span className={`text-[10px] font-mono font-bold ${apiTheme.accentTextClass}`}>
													{apiQuest.reward?.toLocaleString()} $DEPTH at TGE
												</span>
											)}
										</div>
									</div>
								)}

								{/* Quest 3: Apex Syndicate Pass (#2) */}
								{nodeQuest.enabled !== false && (
									<div className={`p-3 rounded-xl border bg-card/40 space-y-2 transition-all ${
										nodeQuest.reward_type === "nft"
											? `${nodeTheme.borderClass} ${nodeTheme.glowClass} ${nodeTheme.bgGradientClass}`
											: "border-border/80"
									}`}>
										<div className="flex justify-between items-center text-xs">
											<span className="font-bold text-white flex items-center gap-2">
												{nodeQuest.reward_type === "nft" ? (
													<div className="h-8 w-5 rounded overflow-hidden border shrink-0 shadow-sm" style={{ borderColor: `${nodeTheme.color}80` }}>
														<img
															src={getNftPassImageUrl(nodeQuest.nft_token_id ?? 2, nodeQuest.nft_image_url)}
															alt=""
															className="h-full w-full object-cover"
															onError={(e) => {
																const target = e.currentTarget;
																const fallback = getNftPassImageUrl(nodeQuest.nft_token_id ?? 2);
																if (target.src !== fallback) target.src = fallback;
															}}
														/>
													</div>
												) : (
													<Server className="h-3.5 w-3.5 text-emerald-400 shrink-0" />
												)}
												<span className="truncate max-w-[180px]">
													{nodeQuest.title || "Node Runner Veteran"}
												</span>
											</span>
											{nodeQuest.reward_type === "nft" ? (
												<div className="flex items-center gap-1.5 shrink-0">
													<span className={`rounded font-mono font-bold text-[10px] px-1.5 py-0.5 border ${nodeTheme.badgeClass}`}>
														{nodeQuest.nft_token_id === 0 || nodeQuest.nft_multiplier === "1.0x" ? "1:1 Voucher" : nodeQuest.nft_multiplier || "2.0x"}
													</span>
													<span className={`font-mono font-bold text-xs ${nodeTheme.accentTextClass}`}>
														Pass #{nodeQuest.nft_token_id ?? 2}
													</span>
												</div>
											) : (
												<span className="font-mono font-bold text-emerald-400">
													+{nodeQuest.reward?.toLocaleString()} $DEPTH
												</span>
											)}
										</div>
										<div className="flex items-center justify-between text-[11px] text-muted-foreground">
											<span>Age: {nodeQuest.min_node_age_days}d+ • Vol: ${nodeQuest.min_volume_usd?.toLocaleString()}</span>
											{nodeQuest.reward_type === "nft" && (
												<span className={`text-[10px] font-mono font-bold ${nodeTheme.accentTextClass}`}>
													{nodeQuest.reward?.toLocaleString()} $DEPTH at TGE
												</span>
											)}
										</div>
									</div>
								)}
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
