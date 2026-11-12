// pwa/components/mining/PromoCampaignModal.tsx
import React, { useState } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "react-hot-toast";
import {
	X,
	ChevronLeft,
	Sparkles,
	Check,
	Lock,
	ShieldCheck,
	Clock,
	Loader2,
	Server,
	Globe,
} from "lucide-react";
import { api } from "../../services/api";
import { BitgetLogoSvg } from "./BitgetLogoSvg";
import { exchangeLabels, exchangeLogos, normalizeExchangeKey, getActiveExchangesList } from "../../lib/exchanges";
import { getNftPassImageUrl, getQuestColorTheme } from "../../lib/nftAssets";

interface PromoQuestRequirements {
	volumeThreshold?: number;
	totalVolume?: number;
	verifiedVolume?: number;
	isVolumeVerifying?: boolean;
	isVolumeVerified?: boolean;
	hasExchangeKey?: boolean;
	exchangeUid?: string;
	hasWallet?: boolean;
	isPhysicalNode?: boolean;
	nodeAgeDays?: number;
	minNodeAgeDays?: number;
	hasActiveMining?: boolean;
	[key: string]: unknown;
}

interface PromoQuest {
	questType: string;
	title: string;
	description?: string;
	reward: number;
	claimedSlots: number;
	totalSlots: number;
	remainingSlots: number;
	isClaimed?: boolean;
	allRequirementsMet?: boolean;
	requirements?: PromoQuestRequirements;
	rewardType?: "token" | "nft";
	reward_type?: "token" | "nft";
	nftContractAddress?: string;
	nft_contract_address?: string;
	nftChainId?: number;
	nft_chain_id?: number;
	nftTokenId?: number;
	nft_token_id?: number;
	nftName?: string;
	nft_name?: string;
	nftImageUrl?: string;
	nft_image_url?: string;
	nftMultiplier?: string;
	nft_multiplier?: string;
	nftNominal?: number;
	nft_nominal?: number;
	nftMaxSupply?: number;
	nft_max_supply?: number;
	[key: string]: unknown;
}

export interface PromoModalStatus {
	hasActiveCampaign?: boolean;
	campaignId?: string;
	campaignName?: string;
	description?: string;
	exchangeId?: string;
	isAdminPreview?: boolean;
	remainingPool?: number;
	totalPool?: number;
	quests?: PromoQuest[];
	[key: string]: unknown;
}

interface PromoClaimResult {
	message?: string;
	data?: PromoClaimResult;
	[key: string]: unknown;
}

type PromoClaimError = {
	message?: string;
	response?: {
		data?: {
			detail?: string;
		};
	};
};

interface PromoCampaignModalProps {
	isOpen: boolean;
	onClose: () => void;
	promoStatus: PromoModalStatus | null;
	onRefresh?: () => void;
	nodeUuid?: string;
	eligibleExchanges?: string[];
}

export const PromoCampaignModal: React.FC<PromoCampaignModalProps> = ({
	isOpen,
	onClose,
	promoStatus,
	onRefresh,
	nodeUuid,
	eligibleExchanges,
}) => {
	const { t } = useTranslation("pwa-common");
	const [claimingType, setClaimingType] = useState<string | null>(null);

	if (!isOpen || !promoStatus?.hasActiveCampaign) {
		return null;
	}

	const handleClaim = async (quest: PromoQuest) => {
		if (!promoStatus?.campaignId || claimingType || quest.isClaimed) return;

		setClaimingType(quest.questType);
		try {
			const res = await api.claimPromoQuest(
				promoStatus.campaignId,
				quest.questType,
				nodeUuid,
			);
			const data = (res as PromoClaimResult)?.data ?? (res as PromoClaimResult);
			toast.success(
				data?.message ??
					t("mining.questClaimSuccessDesc", "🎉 Successfully claimed {{amount}} $DEPTH!", {
						amount: quest.reward.toLocaleString(),
					}),
				{ duration: 4000 },
			);
			if (onRefresh) {
				onRefresh();
			}
		} catch (err) {
			const claimErr = err as PromoClaimError;
			const msg =
				claimErr?.message ??
				claimErr?.response?.data?.detail ??
				t("mining.questClaimFailedDesc", "Failed to claim reward. Please check all requirements.");
			toast.error(msg, { duration: 4000 });
		} finally {
			setClaimingType(null);
		}
	};

	const rawExchangeId = (promoStatus.exchangeId || "").trim().toLowerCase();
	const parsedExchanges =
		!rawExchangeId || rawExchangeId === "all"
			? []
			: rawExchangeId
					.split(",")
					.map((s) => normalizeExchangeKey(s) || s.trim().toLowerCase())
					.filter(Boolean);

	const isMulti = parsedExchanges.length > 1;
	const isUniversal = rawExchangeId === "all" || isMulti;
	const targetExKey = isUniversal ? (isMulti ? null : "all") : normalizeExchangeKey(rawExchangeId);
	const targetExLogo = targetExKey && targetExKey !== "all" ? exchangeLogos[targetExKey] : null;
	const targetExLabel = isUniversal
		? isMulti
			? parsedExchanges.map((e) => exchangeLabels[e] || e.toUpperCase()).join(", ")
			: t("mining.promoUniversalExchanges", "All Supported Exchanges")
		: (targetExKey ? exchangeLabels[targetExKey] : null) || promoStatus.exchangeId || "Partner";
	const exchangeName = targetExLabel.toUpperCase();
	const exchangesListStr = isMulti
		? parsedExchanges.map((e) => exchangeLabels[e] || e.toUpperCase()).join(", ")
		: getActiveExchangesList(eligibleExchanges);
	const isLegacyCampaignDesc = Boolean(
		!promoStatus.description ||
		((isUniversal || targetExKey !== "bitget") && /bitget/i.test(promoStatus.description))
	);

	return (
		<div className="fixed inset-0 z-50 bg-background text-foreground flex flex-col animate-in fade-in duration-200">
			{/* Sticky Navigation Bar */}
			<div className="sticky top-0 z-20 flex items-center justify-between border-b border-border bg-card/95 backdrop-blur-md px-4 py-3 shadow-sm">
				<button
					type="button"
					onClick={onClose}
					className="flex items-center gap-1.5 text-xs font-semibold text-muted-foreground transition hover:text-foreground active:scale-95"
				>
					<ChevronLeft className="h-5 w-5 text-cyan-600 dark:text-[#00F0FF]" />
					<span>{t("mining.backToMining", "Back")}</span>
				</button>

				<div className="flex items-center gap-2">
					<span className="text-sm font-bold text-foreground tracking-tight truncate max-w-[170px]">
						{promoStatus.campaignName || t("mining.promoQuestsTitle", "Bitget Launch Quests")}
					</span>
					{promoStatus.isAdminPreview ? (
						<span className="inline-flex items-center rounded-full border border-amber-500/40 bg-amber-500/15 px-2 py-0.5 text-[9px] font-black uppercase text-amber-600 dark:text-amber-300">
							<Lock className="h-2 w-2 mr-1" />
							{t("mining.adminPreviewBadge", "ADMIN PREVIEW")}
						</span>
					) : (
						<span className="rounded-full border border-cyan-500/40 dark:border-[#00F0FF]/40 bg-cyan-500/15 dark:bg-[#1DA2B4]/20 px-2 py-0.5 text-[9px] font-black uppercase text-cyan-600 dark:text-[#00F0FF]">
							{t("mining.liveBadge", "LIVE")}
						</span>
					)}
				</div>

				<button
					type="button"
					onClick={onClose}
					className="flex h-8 w-8 items-center justify-center rounded-full bg-muted/80 text-muted-foreground transition hover:bg-muted hover:text-foreground"
					aria-label="Close"
				>
					<X className="h-4 w-4" />
				</button>
			</div>

			{/* Scrollable Body */}
			<div className="flex-1 overflow-y-auto p-4 space-y-4 pb-12">
				{/* Top Hero / Pool Stats Card */}
				<div className="relative overflow-hidden rounded-2xl border border-[#1DA2B4]/30 dark:border-[#1DA2B4]/40 bg-gradient-to-br from-[#1DA2B4]/15 via-sky-400/5 to-cyan-500/10 dark:from-[#1DA2B4]/15 dark:via-[#0F1923]/95 dark:to-blue-500/10 bg-card p-4 shadow-sm dark:shadow-lg">
					<div className="pointer-events-none absolute -right-8 -top-8 h-40 w-40 rounded-full bg-[radial-gradient(circle,rgba(0,240,255,0.15)_0%,transparent_70%)]" />

					<div className="relative flex items-start gap-3 mb-3">
						<div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl border border-[#1DA2B4]/30 dark:border-[#00F0FF]/40 bg-[#1DA2B4]/15 dark:bg-[#1DA2B4]/20 p-1.5 shadow-sm dark:shadow-[0_0_15px_rgba(29,162,180,0.35)]">
							{targetExKey === "bitget" ? (
								<BitgetLogoSvg className="h-full w-full drop-shadow-[0_2px_8px_rgba(29,162,180,0.4)]" />
							) : targetExLogo ? (
								<img src={targetExLogo} alt={targetExLabel} className="h-full w-full object-contain" />
							) : (
								<BitgetLogoSvg className="h-full w-full drop-shadow-[0_2px_8px_rgba(29,162,180,0.4)]" />
							)}
						</div>
						<div className="min-w-0">
							<h2 className="text-base font-black text-foreground dark:text-white leading-tight">
								{promoStatus.campaignName ||
									(isUniversal
										? t("mining.promoQuestsTitle", "Promotional Airdrop Quests")
										: t("mining.promoQuestsTitleWithEx", "{{exchange}} Launch Quests", { exchange: targetExLabel }))}
							</h2>
							<p className="mt-1 text-xs text-muted-foreground leading-snug">
								{!isLegacyCampaignDesc && promoStatus.description
									? promoStatus.description
									: isUniversal
									? t(
											"mining.promoQuestsDescriptionUniversal",
											"Выполняйте квесты, чтобы получить токены $DEPTH из промо-пула аирдропа на {{pool}}M. Награда за каждый квест выдается один раз на уникальный аккаунт поддерживаемой биржи ({{exchanges}}).",
											{
												pool: ((promoStatus.totalPool || 10_000_000) / 1_000_000).toFixed(0),
												exchanges: exchangesListStr,
											}
									  )
									: t(
											"mining.promoQuestsDescriptionWithEx",
											"Выполняйте квесты, чтобы получить токены $DEPTH из промо-пула аирдропа на {{pool}}M. Каждый квест выдается один раз на уникальный мастер-UID аккаунта {{exchange}}.",
											{
												pool: ((promoStatus.totalPool || 10_000_000) / 1_000_000).toFixed(0),
												exchange: targetExLabel,
											}
									  )}
							</p>
						</div>
					</div>

					{/* Pool Remaining Metric */}
					<div className="rounded-xl border border-cyan-500/30 dark:border-[#1DA2B4]/40 bg-cyan-500/5 dark:bg-[#1DA2B4]/10 p-3 shadow-inner">
						<div className="text-[10px] uppercase font-bold tracking-wider text-muted-foreground">
							{t("mining.promoPoolRemaining", "Airdrop Pool Remaining")}
						</div>
						<div className="text-2xl font-black font-mono bg-gradient-to-r from-cyan-600 via-[#1DA2B4] to-blue-500 dark:from-[#00F0FF] dark:via-[#1DA2B4] dark:to-blue-400 bg-clip-text text-transparent">
							{(promoStatus.remainingPool || 0).toLocaleString()} $DEPTH
						</div>
						<div className="text-[10px] text-muted-foreground">
							{t("mining.promoOfTotalPool", "of {{total}} $DEPTH", {
								total: (promoStatus.totalPool || 10_000_000).toLocaleString(),
							})}
						</div>
					</div>
				</div>

				{/* Quests List - Sorted by Token #0 -> #1 -> #2 */}
				<div className="space-y-4">
					{(() => {
						const questsList = promoStatus?.quests || [];
						const sortedQuests = [...questsList].sort((a: PromoQuest, b: PromoQuest) => {
							const getOrder = (q: PromoQuest) => {
								const tid = q.nftTokenId ?? q.nft_token_id;
								if (tid !== undefined && tid !== null) return Number(tid);
								if (q.questType === "telemetry_pass") return 0;
								if (q.questType === "api_volume") return 1;
								if (q.questType === "node_runner") return 2;
								return q.reward || 0;
							};
							return getOrder(a) - getOrder(b);
						});

						return sortedQuests.map((quest: PromoQuest) => {
							const isNode = quest.questType === "node_runner";
							const isApi = !isNode;
							const reqs = quest.requirements || {};
							const claimedPercent =
								quest.totalSlots > 0
									? Math.min(
											100,
											(quest.claimedSlots / quest.totalSlots) * 100,
										)
									: 0;

						const volumeThreshold = reqs.volumeThreshold || 1000;
						// Total reported volume vs verified volume
						const totalVolume = reqs.totalVolume ?? reqs.verifiedVolume ?? 0;
						const verifiedVolume = reqs.verifiedVolume ?? 0;
						const isVolumeVerifying = Boolean(reqs.isVolumeVerifying);
						const isVolumeVerified = Boolean(
							reqs.isVolumeVerified ?? (verifiedVolume >= volumeThreshold),
						);
						// Scale fills immediately with all reported trades (including pending verification)
						const volumePercent = Math.min(
							100,
							(totalVolume / volumeThreshold) * 100,
						);
						const isThisClaiming = claimingType === quest.questType;
						const minNodeAgeDays = reqs.minNodeAgeDays ?? 14;

						const isLegacyBitgetTitle =
							quest.title === "Bitget API Pioneer" ||
							quest.title === "bitget_api_pioneer";
						const displayTitle =
							quest.title?.trim() && !isLegacyBitgetTitle
								? quest.title
								: isApi
								? (isUniversal
									? t("mining.questApiPioneerTitle", "API Volume Pioneer")
									: t("mining.questApiPioneerTitleWithEx", "{{exchange}} API Pioneer", { exchange: targetExLabel }))
								: (isUniversal
									? t("mining.questNodeRunnerTitle", "Node Runner Veteran")
									: t("mining.questNodeRunnerTitleWithEx", "{{exchange}} Node Runner Veteran", { exchange: targetExLabel }));

						const questDesc = (typeof quest.description === "string" ? quest.description : "").trim();
						const isGeneratedDesc = Boolean(
							!questDesc ||
							/^(connect (your|an|the)|rewards users|run an active node|запустите активную ноду|подключите)/i.test(questDesc) ||
							((isUniversal || targetExKey !== "bitget") && /bitget/i.test(questDesc)) ||
							questDesc.includes("$5 000") ||
							questDesc.includes("$1 000") ||
							questDesc.includes("$5,000") ||
							questDesc.includes("$1,000")
						);
						const displayDescription: string = !isGeneratedDesc && questDesc
							? questDesc
							: isApi
							? (isUniversal
								? t("mining.questApiPioneerDescUniversal", "Подключите API-ключ любой поддерживаемой биржи ({{exchanges}}) и совершите верифицированный объем торгов от ${{threshold}}.", {
										exchanges: exchangesListStr,
										threshold: volumeThreshold.toLocaleString(),
								  })
								: t("mining.questApiPioneerDescWithEx", "Подключите ваш API-ключ {{exchange}} и совершите верифицированный объем торгов от ${{threshold}}.", {
										exchange: targetExLabel,
										threshold: volumeThreshold.toLocaleString(),
								  }))
							: (isUniversal
								? t("mining.questNodeRunnerDescUniversal", "Запустите активную ноду от {{days}} дней с привязанным кошельком, торгуйте на поддерживаемых биржах ({{exchanges}}) и наберите объем от ${{threshold}} на своем сервере.", {
										days: minNodeAgeDays,
										exchanges: exchangesListStr,
										threshold: volumeThreshold.toLocaleString(),
								  })
								: t("mining.questNodeRunnerDescWithEx", "Запустите активную ноду от {{days}} дней с привязанным кошельком, торгуйте на {{exchange}} и наберите объем от ${{threshold}} на своем сервере.", {
										days: minNodeAgeDays,
										exchange: targetExLabel,
										threshold: volumeThreshold.toLocaleString(),
								  }));

						return (
							<div
								key={quest.questType}
								className={`relative flex flex-col justify-between overflow-hidden rounded-2xl border bg-card p-4 transition-all duration-300 shadow-sm ${
									quest.isClaimed
										? "border-cyan-500/30 dark:border-[#1DA2B4]/30 opacity-90"
										: quest.allRequirementsMet
											? "border-cyan-500/60 dark:border-[#00F0FF]/60 shadow-[0_0_20px_rgba(29,162,180,0.25)] ring-1 ring-cyan-500/30"
											: "border-border"
								}`}
							>
								{/* Quest Card Top */}
								<div>
									<div className="flex items-center justify-between gap-2 mb-3">
										<div className="flex items-center gap-2.5">
											<div
												className={`flex h-9 w-9 items-center justify-center rounded-xl border p-1.5 ${
													isApi
														? "border-cyan-500/30 bg-cyan-500/10"
														: "border-blue-500/30 bg-blue-500/10 text-blue-600 dark:text-blue-400"
												}`}
											>
												{isApi ? (
													isUniversal ? (
														<Globe className="h-5 w-5 text-cyan-500" />
													) : targetExKey === "bitget" ? (
														<BitgetLogoSvg className="h-full w-full" />
													) : targetExLogo ? (
														<img src={targetExLogo} alt={targetExLabel} className="h-full w-full object-contain" />
													) : (
														<BitgetLogoSvg className="h-full w-full" />
													)
												) : (
													<Server className="h-5 w-5" />
												)}
											</div>
											<div>
												<h3 className="text-sm font-bold text-card-foreground tracking-tight">
													{displayTitle}
												</h3>
												<p className="mt-0.5 text-[10px] text-muted-foreground leading-snug line-clamp-2 max-w-[220px]">
													{displayDescription}
												</p>
												<div className="text-[10px] text-muted-foreground font-mono mt-0.5">
													{quest.claimedSlots.toLocaleString()} /{" "}
													{quest.totalSlots.toLocaleString()}{" "}
													{t("mining.questSlotsClaimed", "slots claimed").toLowerCase()}
												</div>
											</div>
										</div>

										<div
											className={`inline-flex items-center gap-1 rounded-full border px-2.5 py-1 text-[10px] font-bold ${
												quest.isClaimed
													? "border-cyan-500/40 bg-cyan-500/15 text-cyan-600 dark:text-[#00F0FF]"
													: quest.allRequirementsMet
														? "border-cyan-500/60 bg-cyan-500/20 text-cyan-600 dark:text-[#00F0FF] animate-pulse"
														: isVolumeVerifying
															? "border-amber-500/40 bg-amber-500/15 text-amber-600 dark:text-amber-400 animate-pulse"
															: "border-border bg-muted/60 text-muted-foreground"
											}`}
										>
											{quest.isClaimed
												? t("mining.questClaimedBadge", "✓ Claimed")
												: quest.allRequirementsMet
													? t("mining.questReadyToClaim", "Ready!")
													: isVolumeVerifying
														? `⏳ ${t("mining.questVolumeVerifyingBadge", "Verifying...")}`
														: t("mining.questSlotsRemaining", "{{remaining}} left", {
																remaining: quest.remainingSlots.toLocaleString(),
														  })}
										</div>
									</div>

									{/* Reward Section (NFT or Token) */}
									{(quest.rewardType || quest.reward_type) === "nft" ? (
										(() => {
											const tokenId = (quest.nftTokenId || quest.nft_token_id) ?? (isApi ? 1 : 2);
											const defaultTheme = tokenId === 2 ? "purple" : tokenId === 0 ? "cyan" : "gold";
											const customTheme = (quest.nftColorTheme || quest.nft_color_theme) as string | undefined;
											const qTheme = getQuestColorTheme(customTheme, defaultTheme);
											const passImgUrl = getNftPassImageUrl(
												tokenId,
												(quest.nftImageUrl as string) || (quest.nft_image_url as string)
											);
											const multStr = (quest.nftMultiplier as string) || (quest.nft_multiplier as string);
											const isNoBoost = tokenId === 0 || multStr === "1.0x" || multStr === "1x" || multStr === "None";

											return (
												<div className={`my-2.5 rounded-xl border p-2.5 shadow-sm transition-all duration-300 ${qTheme.borderClass} ${qTheme.glowClass} ${qTheme.bgGradientClass}`}>
													<div className="flex gap-2.5 items-center">
														<div className="relative h-20 w-14 shrink-0 rounded-lg overflow-hidden border shadow-sm bg-black" style={{ borderColor: `${qTheme.color}80` }}>
															<img
																src={passImgUrl}
																alt="NFT Genesis Pass"
																className="h-full w-full object-cover"
																onError={(e) => {
																	const target = e.currentTarget;
																	const fallback = getNftPassImageUrl(tokenId);
																	if (target.src !== fallback) target.src = fallback;
																}}
															/>
															<div className="absolute top-0.5 left-0.5 rounded bg-black/80 px-1 py-0.5 text-[7px] font-mono font-bold text-white border border-white/20">
																#{tokenId}
															</div>
														</div>
														<div className="min-w-0 flex-1 space-y-0.5">
															<div className="flex items-center gap-1 flex-wrap">
																<span className={`rounded-full border px-1.5 py-0.5 text-[8.5px] font-mono font-bold ${qTheme.badgeClass}`}>
																	ERC-1155
																</span>
																<span className={`rounded-full border px-1.5 py-0.5 text-[8.5px] font-black font-mono ${qTheme.badgeClass}`}>
																	{isNoBoost ? "1:1 Voucher" : `${multStr || (tokenId === 2 ? "2.0x" : "1.5x")} Boost`}
																</span>
															</div>
															<h4 className="text-xs font-bold text-white truncate">
																{(quest.nftName as string) || (quest.nft_name as string) || (tokenId === 2 ? "DepthSight Apex Syndicate Pass" : tokenId === 0 ? "DepthSight Genesis Pass" : "DepthSight Core Syndicate Pass")}
															</h4>
															<div className="text-[10px] text-muted-foreground font-mono flex items-center gap-1 flex-wrap">
																<span className={`font-bold ${qTheme.accentTextClass}`}>
																	{Number((quest.nftNominal || quest.nft_nominal || quest.reward)).toLocaleString()} $DEPTH
																</span>
																<span>• 1:1 at TGE</span>
															</div>
														</div>
													</div>
												</div>
											);
										})()
									) : (
										<div className="my-2.5 inline-flex items-center gap-2 rounded-lg border border-amber-500/30 bg-amber-500/10 px-3 py-1.5">
											<span className="text-sm">💰</span>
											<span className="text-xs font-black text-amber-600 dark:text-amber-400 font-mono">
												{quest.reward.toLocaleString()} $DEPTH
											</span>
											<span className="text-[10px] text-muted-foreground">
												{quest.isClaimed
													? t("mining.questClaimedLabel", "claimed")
													: t("mining.questRewardLabel", "reward")}
											</span>
										</div>
									)}

									{/* Slots Progress Bar */}
									<div className="mb-3 space-y-1">
										<div className="h-1.5 w-full overflow-hidden rounded-full bg-muted dark:bg-white/10">
											<div
												className={`h-full rounded-full transition-all duration-500 ${
													(quest.rewardType || quest.reward_type) === "nft"
														? "bg-gradient-to-r from-purple-500 via-indigo-500 to-cyan-400"
														: isApi
														? "bg-gradient-to-r from-[#1DA2B4] to-[#00F0FF]"
														: "bg-gradient-to-r from-blue-500 to-cyan-400"
												}`}
												style={{ width: `${claimedPercent}%` }}
											/>
										</div>
									</div>

									{/* Requirements Checklist */}
									<div className="space-y-2 rounded-xl border border-border bg-muted/40 dark:bg-black/30 p-3 mb-4 text-xs">
										{/* Req 1: API Key / UID */}
										<div className="flex items-center justify-between gap-2">
											<div className="flex items-center gap-2 text-muted-foreground">
												<span
													className={`flex h-4 w-4 shrink-0 items-center justify-center rounded text-[10px] font-bold ${
														reqs.hasExchangeKey
															? "bg-cyan-500/20 text-cyan-600 dark:text-[#00F0FF] border border-cyan-500/40"
															: "bg-muted text-muted-foreground border border-border"
													}`}
												>
													{reqs.hasExchangeKey ? "✓" : "○"}
												</span>
												<span>
													{isUniversal
														? t("mining.questReqApiKeyUniversal", "Активный API-ключ биржи ({{exchanges}}) или кошелек подключен", {
																exchanges: exchangesListStr,
														  })
														: t("mining.questReqApiKey", "API-ключ {{exchange}} подключен (Master UID)", {
																exchange: exchangeName,
														  })}
												</span>
											</div>
											{reqs.exchangeUid ? (
												<span className="font-mono text-[11px] font-bold text-cyan-600 dark:text-[#00F0FF]">
													{reqs.exchangeUid}
												</span>
											) : reqs.hasExchangeKey ? (
												<span className="text-[10px] text-emerald-600 dark:text-emerald-400 font-semibold">
													{t("mining.questStatusConnected", "Connected")}
												</span>
											) : (
												<span className="text-[10px] text-rose-600 dark:text-rose-400 font-semibold">
													{t("mining.questStatusNotConnected", "Not connected")}
												</span>
											)}
										</div>

										{/* Req 2: Wallet linked & verified (Both API quest and Node runner) */}
										<div className="flex items-center justify-between gap-2">
											<div className="flex items-center gap-2 text-muted-foreground">
												<span
													className={`flex h-4 w-4 shrink-0 items-center justify-center rounded text-[10px] font-bold ${
														reqs.hasWallet
															? "bg-cyan-500/20 text-cyan-600 dark:text-[#00F0FF] border border-cyan-500/40"
															: "bg-muted text-muted-foreground border border-border"
													}`}
												>
													{reqs.hasWallet ? "✓" : "○"}
												</span>
												<span>{t("mining.questReqWallet", "Wallet linked & verified")}</span>
											</div>
											<span className="font-mono text-[11px] text-foreground dark:text-white">
												{reqs.hasWallet
													? t("mining.questStatusLinked", "Linked")
													: t("mining.questStatusMissing", "Missing")}
											</span>
										</div>

										{/* Node Runner specific items */}
										{!isApi && (
											<>
												<div className="flex items-center justify-between gap-2">
													<div className="flex items-center gap-2 text-muted-foreground">
														<span
															className={`flex h-4 w-4 shrink-0 items-center justify-center rounded text-[10px] font-bold ${
																reqs.isPhysicalNode &&
																(reqs.nodeAgeDays || 0) >=
																	(reqs.minNodeAgeDays || 14)
																	? "bg-cyan-500/20 text-cyan-600 dark:text-[#00F0FF] border border-cyan-500/40"
																	: "bg-muted text-muted-foreground border border-border"
															}`}
														>
															{reqs.isPhysicalNode &&
															(reqs.nodeAgeDays || 0) >=
																(reqs.minNodeAgeDays || 14)
																? "✓"
																: "○"}
														</span>
														<span>
															{t("mining.questReqPhysicalNode", "Server online now, node registered ≥ {{days}} days ago", {
																days: reqs.minNodeAgeDays || 14,
															})}
														</span>
													</div>
												<span className="font-mono text-[11px] text-foreground dark:text-white">
													{reqs.isPhysicalNode
														? t("mining.questNodeAgeDays", "{{days}} days", { days: reqs.nodeAgeDays || 0 })
														: t("mining.questStatusNotRunning", "Not running")}
												</span>
												</div>

												<div className="flex items-center justify-between gap-2">
													<div className="flex items-center gap-2 text-muted-foreground">
														<span
															className={`flex h-4 w-4 shrink-0 items-center justify-center rounded text-[10px] font-bold ${
																reqs.hasActiveMining
																	? "bg-cyan-500/20 text-cyan-600 dark:text-[#00F0FF] border border-cyan-500/40"
																	: "bg-muted text-muted-foreground border border-border"
															}`}
														>
															{reqs.hasActiveMining ? "✓" : "○"}
														</span>
													<span>
														{t("mining.questReqActiveMining", "Active mining (trade in last {{days}} days)", {
															days: (reqs.tradeWindowDays as number) || 7,
														})}
													</span>
													</div>
													<span className="font-mono text-[11px] text-foreground dark:text-white">
														{reqs.hasActiveMining
															? t("mining.questStatusActive", "Active")
															: t("mining.questStatusNoTrades", "No recent trades")}
													</span>
												</div>
											</>
										)}

										{/* Volume Checklist */}
										<div className="space-y-1.5 pt-1">
											<div className="flex items-center justify-between text-muted-foreground">
												<div className="flex items-center gap-2">
													<span
														className={`flex h-4 w-4 shrink-0 items-center justify-center rounded text-[10px] font-bold ${
															isVolumeVerified
																? "bg-cyan-500/20 text-cyan-600 dark:text-[#00F0FF] border border-cyan-500/40"
																: isVolumeVerifying
																	? "bg-amber-500/20 text-amber-600 dark:text-amber-400 border border-amber-500/40 animate-pulse"
																	: "bg-muted text-muted-foreground border border-border"
														}`}
													>
														{isVolumeVerified ? "✓" : isVolumeVerifying ? "⏳" : "○"}
													</span>
													<span>
														{isApi
															? t("mining.questReqVolume", "Reach ${{threshold}} verified volume", {
																	threshold: volumeThreshold.toLocaleString(),
															  })
															: t(
																	"mining.questReqVolumePhysical",
																	"Reach ${{threshold}} verified volume on your server",
																	{
																		threshold: volumeThreshold.toLocaleString(),
																	}
															  )}
													</span>
												</div>
												<span className={`font-mono text-[11px] font-bold ${isVolumeVerified ? "text-cyan-600 dark:text-[#00F0FF]" : isVolumeVerifying ? "text-amber-600 dark:text-amber-400" : "text-foreground dark:text-white"}`}>
													${totalVolume.toFixed(2)} / ${volumeThreshold.toLocaleString()}
												</span>
											</div>
											<div className="h-1.5 w-full overflow-hidden rounded-full bg-muted dark:bg-white/10">
												<div
													className={`h-full rounded-full transition-all duration-500 ${
														isVolumeVerified
															? "bg-gradient-to-r from-[#1DA2B4] to-[#00F0FF]"
															: isVolumeVerifying
																? "bg-gradient-to-r from-amber-500 to-cyan-400 animate-pulse"
																: "bg-gradient-to-r from-[#1DA2B4] to-[#00F0FF]"
													}`}
													style={{ width: `${volumePercent}%` }}
												/>
											</div>
											{isVolumeVerifying && (
												<div className="flex items-center justify-between text-[10px] text-amber-600 dark:text-amber-400/90 pt-0.5 font-medium">
													<span className="flex items-center gap-1.5">
														<span className="inline-block h-1.5 w-1.5 rounded-full bg-amber-500 animate-ping" />
														{t("mining.questVolumePendingVerification", "Volume reached • Awaiting broker verification")}
													</span>
													<span className="font-mono text-[10px] text-muted-foreground">
														(${verifiedVolume.toFixed(2)} {t("mining.questVerifiedSuffix", "verified")})
													</span>
												</div>
											)}
										</div>
									</div>
								</div>

								{/* Card Action Button */}
								{(() => {
									const isQuestNft = (quest.rewardType || quest.reward_type) === "nft";
									const nftTokenId = (quest.nftTokenId || quest.nft_token_id) ?? (isApi ? 1 : 2);
									const nftNominal = Number(quest.nftNominal || quest.nft_nominal || quest.reward);

									return (
										<div>
											{quest.isClaimed ? (
												<button
													type="button"
													disabled
													className={`w-full flex items-center justify-center gap-2 rounded-xl border py-2.5 text-xs font-bold cursor-default opacity-85 ${
														isQuestNft
															? "border-purple-500/40 bg-purple-500/15 text-purple-300"
															: "border-cyan-500/40 bg-cyan-500/10 text-cyan-600 dark:text-[#00F0FF]"
													}`}
												>
													<Check className="h-4 w-4" />
													{isQuestNft
														? `✓ Pass #${nftTokenId} Reserved (Thirdweb Airdrop Voucher)`
														: t("mining.questRewardClaimedBtn", "Reward Claimed — {{amount}} $DEPTH Added", {
																amount: quest.reward.toLocaleString(),
														  })}
												</button>
											) : quest.allRequirementsMet ? (
												<button
													type="button"
													onClick={() => handleClaim(quest)}
													disabled={isThisClaiming}
													className={`w-full flex items-center justify-center gap-2 rounded-xl py-2.5 text-xs font-black shadow-lg transition-all active:scale-[0.98] hover:opacity-95 ${
														isQuestNft
															? "bg-gradient-to-r from-purple-500 via-indigo-500 to-cyan-400 text-white shadow-[0_4px_20px_rgba(168,85,247,0.4)]"
															: "bg-gradient-to-r from-[#1DA2B4] to-[#00F0FF] text-slate-950 shadow-[0_4px_20px_rgba(0,240,255,0.4)]"
													}`}
												>
													{isThisClaiming ? (
														<Loader2 className="h-4 w-4 animate-spin" />
													) : (
														<Sparkles className="h-4 w-4" />
													)}
													{isThisClaiming
														? t("mining.questClaiming", "Processing...")
														: isQuestNft
														? `💎 Reserve Pass #${nftTokenId} (${nftNominal.toLocaleString()} $DEPTH)`
														: t("mining.questClaimBtn", "🎉 Claim {{amount}} $DEPTH", {
																amount: quest.reward.toLocaleString(),
														  })}
												</button>
											) : isVolumeVerifying ? (
												<button
													type="button"
													disabled
													className="w-full flex items-center justify-center gap-2 rounded-xl border border-amber-500/40 bg-amber-500/10 py-2.5 text-xs font-semibold text-amber-600 dark:text-amber-400 cursor-not-allowed shadow-[0_0_15px_rgba(245,158,11,0.15)]"
												>
													<Loader2 className="h-4 w-4 animate-spin text-amber-500" />
													<span>{t("mining.questVolumeVerifyingBtn", "Verifying Trading Volume...")}</span>
												</button>
											) : (
												<button
													type="button"
													disabled
													className="w-full rounded-xl border border-border bg-muted/60 py-2.5 text-xs font-medium text-muted-foreground cursor-not-allowed opacity-75"
												>
													{t(
														"mining.questCompleteRequirements",
														"Complete all requirements to claim",
													)}
												</button>
											)}
										</div>
									);
								})()}
							</div>
						);
					});
				})()}
				</div>

				{/* Footer Security Notes */}
				<div className="space-y-2 rounded-xl border border-border bg-card p-3 text-[11px] text-muted-foreground">
					<div className="flex items-center gap-2">
						<ShieldCheck className="h-4 w-4 text-cyan-600 dark:text-[#00F0FF] shrink-0" />
						<span>
							{isUniversal
								? t(
										"mining.questFootnoteUidUniversal",
										"Один клейм на уникальный аккаунт поддерживаемой биржи ({{exchanges}})",
										{ exchanges: exchangesListStr }
								  )
								: t("mining.questFootnoteUid", "One claim per unique {{exchange}} master account UID", {
										exchange: exchangeName,
								  })}
						</span>
					</div>
					<div className="flex items-center gap-2">
						<Clock className="h-4 w-4 text-cyan-600 dark:text-[#00F0FF] shrink-0" />
						<span>
							{t(
								"mining.questFootnoteDuration",
								"Campaign runs until all slots are claimed",
							)}
						</span>
					</div>
					<div className="flex items-center gap-2">
						<Check className="h-4 w-4 text-cyan-600 dark:text-[#00F0FF] shrink-0" />
						<span>
							{t(
								"mining.questFootnoteVerification",
								"Only broker-verified trading volume counts",
							)}
						</span>
					</div>
				</div>
			</div>
		</div>
	);
};
