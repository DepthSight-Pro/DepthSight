// frontend/src/components/mining/PromoQuestsTab.tsx
import React, { useState } from "react";
import { useTranslation } from "react-i18next";
import { Check, Clock, ShieldCheck, Sparkles, Server, Loader2, Globe, Trophy, TrendingUp } from "lucide-react";
import { Button } from "@/components/ui/button";
import { toast } from "@/components/ui/use-toast";
import { useClaimPromoQuest, useGetPromoLeaderboard } from "@/lib/api";
import type { PromoClaimResponse, PromoQuestProgress, PromoStatusResponse } from "@/types/api";
import { BitgetLogoSvg } from "./PromoBanner";
import { exchangeLabels, exchangeLogos, normalizeExchangeKey, getActiveExchangesList } from "@/lib/exchanges";
import { getNftPassImageUrl, getQuestColorTheme } from "@/lib/nftAssets";

const toNumber = (value: unknown, fallback = 0): number => {
	if (typeof value === "number" && Number.isFinite(value)) return value;
	if (typeof value === "string" && value.trim() !== "" && Number.isFinite(Number(value))) return Number(value);
	return fallback;
};

interface PromoQuestsTabProps {
	promoStatus: PromoStatusResponse;
	eligibleExchanges?: string[];
}

export const PromoQuestsTab: React.FC<PromoQuestsTabProps> = ({ promoStatus, eligibleExchanges }) => {
	const { t } = useTranslation(["mining", "common"]);
	const { mutate: claimQuest, isPending: isClaiming } = useClaimPromoQuest();
	const { data: leaderboardData, isLoading: isLoadingLeaderboard } = useGetPromoLeaderboard();
	const [activeSubTab, setActiveSubTab] = useState<"quests" | "leaderboard">("quests");
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
			: t("promoUniversalExchanges", "All Exchanges")
		: (targetExKey ? exchangeLabels[targetExKey] : null) || promoStatus.exchangeId || "Partner";

	const exchangesListStr = isMulti
		? parsedExchanges.map((e) => exchangeLabels[e] || e.toUpperCase()).join(", ")
		: getActiveExchangesList(eligibleExchanges);

	if (!promoStatus?.hasActiveCampaign) {
		return null;
	}

	const handleClaim = (quest: PromoQuestProgress) => {
		if (!promoStatus.campaignId || isClaiming || quest.isClaimed) return;

		claimQuest(
			{
				campaign_id: promoStatus.campaignId,
				quest_type: quest.questType,
			},
			{
				onSuccess: (res: PromoClaimResponse) => {
					const isNft = quest.rewardType === "nft";
					toast({
						title: isNft
							? t("questClaimSuccessTitleNft", "🎉 NFT Pass Voucher Reserved!")
							: t("questClaimSuccessTitle", "🎉 Reward Claimed Successfully!"),
						description:
							res?.message ||
							(isNft
								? t(
										"questClaimSuccessDescNft",
										"Successfully reserved {{name}} on Arbitrum One! Batch airdrop will be sent directly to your verified wallet.",
										{ name: quest.nftName || `NFT Pass #${quest.nftTokenId ?? 1}` }
								  )
								: t("questClaimSuccessDesc", "Successfully claimed {{amount}} $DEPTH to your node balance!", {
										amount: quest.reward.toLocaleString(),
								  })),
					});
				},
				onError: (err: Error) => {
					toast({
						title: t("questClaimFailedTitle", "Claim Failed"),
						description:
							err?.message ||
							t("questClaimFailedDesc", "Failed to claim reward. Please check all requirements."),
						variant: "destructive",
					});
				},
			}
		);
	};

	return (
		<div className="space-y-6">
			{/* Quests Header & Pool Counter */}
			<div className="glass relative flex flex-col sm:flex-row sm:items-center justify-between gap-4 rounded-2xl border border-white/10 shadow-xl overflow-hidden p-6">
				<div className="absolute -top-16 -right-16 w-48 h-48 rounded-full bg-cyan-500/10 blur-3xl pointer-events-none" />
				<div className="relative">
					<div className="flex items-center gap-2.5">
						<span className="text-xl">🎁</span>
						<h2 className="text-xl font-black text-white">
							{promoStatus.campaignName ||
								(isUniversal
									? t("promoQuestsTitle", "Promotional Airdrop Quests")
									: t("promoQuestsTitleWithEx", "{{exchange}} Launch Quests", { exchange: targetExLabel }))}
						</h2>
						{promoStatus.isAdminPreview && (
							<span className="rounded-full border border-amber-500/40 bg-amber-500/20 px-2.5 py-0.5 text-[10px] font-black uppercase tracking-wider text-amber-300">
								{t("adminPreviewBadge", "Admin Preview Mode")}
							</span>
						)}
					</div>
					<p className="mt-1 text-xs sm:text-sm text-white/60 max-w-xl">
						{(() => {
							const isLegacyCampaignDesc = Boolean(
								!promoStatus.description ||
								((isUniversal || targetExKey !== "bitget") && /bitget/i.test(promoStatus.description))
							);
							if (!isLegacyCampaignDesc && promoStatus.description) {
								return promoStatus.description;
							}
							return isUniversal
								? t(
										"promoQuestsDescriptionUniversal",
										"Выполняйте квесты, чтобы получить токены $DEPTH из промо-пула аирдропа на {{pool}}M. Награда за каждый квест выдается один раз на уникальный аккаунт поддерживаемой биржи ({{exchanges}}).",
										{
											pool: ((promoStatus.totalPool || 10_000_000) / 1_000_000).toFixed(0),
											exchanges: exchangesListStr,
										}
								  )
								: t(
										"promoQuestsDescriptionWithEx",
										"Выполняйте квесты, чтобы получить токены $DEPTH из промо-пула аирдропа на {{pool}}M. Каждый квест выдается один раз на уникальный мастер-UID аккаунта {{exchange}}.",
										{
											pool: ((promoStatus.totalPool || 10_000_000) / 1_000_000).toFixed(0),
											exchange: targetExLabel,
										}
								  );
						})()}
					</p>
				</div>

				<div className="relative rounded-xl border border-cyan-500/30 bg-cyan-500/10 px-5 py-3 text-left sm:text-right shadow-inner shrink-0 backdrop-blur-md">
					<div className="text-[10px] uppercase font-bold tracking-wider text-cyan-300/80">
						{t("promoPoolRemaining", "Airdrop Pool Remaining")}
					</div>
					<div className="text-2xl font-black font-mono bg-gradient-to-r from-[#00F0FF] via-[#1DA2B4] to-blue-400 bg-clip-text text-transparent">
						{(promoStatus.remainingPool || 0).toLocaleString()}
					</div>
					<div className="text-[11px] text-white/50">
						{t("promoOfTotalPool", "of {{total}} $DEPTH", {
							total: (promoStatus.totalPool || 10_000_000).toLocaleString(),
						})}
					</div>
				</div>
			</div>

			{/* Subtab Navigation Pills */}
			<div className="flex items-center gap-2 border-b border-white/10 pb-3">
				<button
					type="button"
					onClick={() => setActiveSubTab("quests")}
					className={`group relative flex items-center gap-2 rounded-xl px-4 py-2 text-xs sm:text-sm font-semibold transition-all ${
						activeSubTab === "quests"
							? "bg-gradient-to-r from-cyan-500/20 to-blue-500/20 text-[#00F0FF] border border-cyan-500/40 shadow-[0_0_15px_rgba(0,240,255,0.15)]"
							: "text-white/60 hover:text-white hover:bg-white/[0.04] border border-transparent"
					}`}
				>
					<Sparkles className={`h-4 w-4 transition-transform group-hover:scale-110 ${activeSubTab === "quests" ? "text-[#00F0FF]" : "text-white/50"}`} />
					<span>{t("promoSubtabNftQuests", "NFT-квесты")}</span>
					{promoStatus.quests && promoStatus.quests.length > 0 && (
						<span className={`ml-1 rounded-full px-2 py-0.5 text-[10px] font-bold ${
							activeSubTab === "quests"
								? "bg-cyan-400/20 text-cyan-300 border border-cyan-400/30"
								: "bg-white/10 text-white/60"
						}`}>
							{promoStatus.quests.length}
						</span>
					)}
				</button>

				<button
					type="button"
					onClick={() => setActiveSubTab("leaderboard")}
					className={`group relative flex items-center gap-2 rounded-xl px-4 py-2 text-xs sm:text-sm font-semibold transition-all ${
						activeSubTab === "leaderboard"
							? "bg-gradient-to-r from-amber-500/20 to-orange-500/20 text-amber-300 border border-amber-500/40 shadow-[0_0_15px_rgba(245,158,11,0.15)]"
							: "text-white/60 hover:text-white hover:bg-white/[0.04] border border-transparent"
					}`}
				>
					<Trophy className={`h-4 w-4 transition-transform group-hover:scale-110 ${activeSubTab === "leaderboard" ? "text-amber-400" : "text-white/50"}`} />
					<span>{t("promoSubtabLeaderboard", "Лидерборд")}</span>
					<span className="flex items-center gap-1 rounded-full border border-cyan-500/30 bg-cyan-500/10 px-2 py-0.5 text-[9px] font-black uppercase tracking-wider text-cyan-300">
						<span className="relative flex h-1.5 w-1.5">
							<span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-cyan-400 opacity-75" />
							<span className="relative inline-flex rounded-full h-1.5 w-1.5 bg-cyan-500" />
						</span>
						Live
					</span>
				</button>
			</div>

			{/* Quests Grid (Supports 1, 2, or 3 Quests - Sorted by Token #0 -> #1 -> #2) */}
			{activeSubTab === "quests" && (
				<div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-5">
				{(() => {
					const questsList = promoStatus.quests || [];
					const sortedQuests = [...questsList].sort((a, b) => {
						const getOrder = (q: PromoQuestProgress) => {
							if (q.nftTokenId !== undefined && q.nftTokenId !== null) return Number(q.nftTokenId);
							if (q.questType === "telemetry_pass") return 0;
							if (q.questType === "api_volume") return 1;
							if (q.questType === "node_runner") return 2;
							return q.reward || 0;
						};
						return getOrder(a) - getOrder(b);
					});

					return sortedQuests.map((quest) => {
						const isNode = quest.questType === "node_runner";
						const isApi = !isNode;
						const reqs = quest.requirements || {};
						const claimedPercent =
							quest.totalSlots > 0 ? Math.min(100, (quest.claimedSlots / quest.totalSlots) * 100) : 0;

				const nodeAgeDays = toNumber(reqs.nodeAgeDays, 0);
				const minNodeAgeDays = toNumber(reqs.minNodeAgeDays, 14);
				const tradeWindowDays = toNumber(reqs.tradeWindowDays ?? reqs.trade_window_days, 7);
				const isPhysicalNodeOldEnough = Boolean(reqs.isPhysicalNode) && nodeAgeDays >= minNodeAgeDays;
					const volumeThreshold = toNumber(reqs.volumeThreshold, 1000);
					const rawTotalVolume = toNumber(reqs.totalVolume ?? reqs.currentVolume ?? reqs.verifiedVolume, 0);
					const rawVerifiedVolume = toNumber(reqs.verifiedVolume, 0);
					const totalVolume = quest.isClaimed ? Math.min(rawTotalVolume, volumeThreshold) : rawTotalVolume;
					const verifiedVolume = quest.isClaimed ? Math.min(rawVerifiedVolume, volumeThreshold) : rawVerifiedVolume;
					const isVolumeVerifying = Boolean(
						reqs.isVolumeVerifying || (totalVolume >= volumeThreshold && verifiedVolume < volumeThreshold)
					);
					const isVolumeVerified = Boolean(
						reqs.isVolumeVerified || verifiedVolume >= volumeThreshold || quest.isClaimed
					);
					const volumePercent = Math.min(100, (totalVolume / volumeThreshold) * 100);

					return (
						<div
							key={quest.questType}
							className={`glass relative flex flex-col justify-between overflow-hidden rounded-2xl border p-6 shadow-xl transition-all duration-300 ${
								quest.isClaimed
									? "border-cyan-500/30 opacity-90"
									: quest.allRequirementsMet
									? "border-cyan-400/60 shadow-[0_0_25px_rgba(0,240,255,0.2)] ring-1 ring-cyan-400/30"
									: isVolumeVerifying
									? "border-amber-500/30 shadow-[0_0_20px_rgba(245,158,11,0.15)]"
									: "border-white/10 hover:border-cyan-500/40 hover:shadow-2xl"
							}`}
						>
							{/* Card Header */}
							<div>
								<div className="flex items-center justify-between gap-3 mb-4">
									<div
										className={`flex h-11 w-11 items-center justify-center rounded-xl border p-2 ${
											isApi
												? "border-[#00F0FF]/30 bg-[#1DA2B4]/15"
												: "border-blue-500/30 bg-blue-500/15 text-blue-400"
										}`}
									>
										{isApi ? (
											isUniversal ? (
												<Globe className="h-5 w-5 text-cyan-400" />
											) : targetExKey === "bitget" ? (
												<BitgetLogoSvg className="h-full w-full drop-shadow-[0_1px_4px_rgba(29,162,180,0.5)]" />
											) : targetExLogo ? (
												<img src={targetExLogo} alt={targetExLabel} className="h-full w-full object-contain" />
											) : (
												<BitgetLogoSvg className="h-full w-full drop-shadow-[0_1px_4px_rgba(29,162,180,0.5)]" />
											)
										) : (
											<Server className="h-5 w-5" />
										)}
									</div>

									<div
										className={`flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs font-semibold ${
											quest.isClaimed
												? "border-[#00F0FF]/40 bg-[#1DA2B4]/15 text-[#00F0FF]"
												: quest.allRequirementsMet
												? "border-[#00F0FF]/60 bg-[#00F0FF]/15 text-[#00F0FF] animate-pulse"
												: isVolumeVerifying
												? "border-amber-500/40 bg-amber-500/15 text-amber-400 animate-pulse"
												: "border-border/60 bg-muted/20 text-muted-foreground"
										}`}
									>
										<span
											className={`h-1.5 w-1.5 rounded-full ${
												quest.isClaimed
													? "bg-[#00F0FF]"
													: quest.allRequirementsMet
													? "bg-[#00F0FF]"
													: isVolumeVerifying
													? "bg-amber-400"
													: "bg-muted-foreground"
											}`}
										/>
										{quest.isClaimed
											? t("questClaimedBadge", "✓ Claimed")
											: quest.allRequirementsMet
											? t("questReadyToClaim", "Ready to Claim!")
											: isVolumeVerifying
											? t("questVolumeVerifyingBadge", "Verifying...")
											: t("questSlotsRemaining", "{{remaining}} / {{total}} slots remaining", {
													remaining: quest.remainingSlots.toLocaleString(),
													total: quest.totalSlots.toLocaleString(),
											  })}
									</div>
								</div>

								{/* Titles & Reward Pill */}
								<h3 className="text-lg font-bold text-white tracking-tight">
									{(() => {
										const isLegacyBitgetTitle =
											quest.title === "Bitget API Pioneer" ||
											quest.title === "bitget_api_pioneer";
										if (quest.title?.trim() && !isLegacyBitgetTitle) {
											return quest.title;
										}
										return isApi
											? (isUniversal
												? t("questApiPioneerTitle", "API Volume Pioneer")
												: t("questApiPioneerTitleWithEx", "{{exchange}} API Pioneer", { exchange: targetExLabel }))
											: (isUniversal
												? t("questNodeRunnerTitle", "Node Runner Veteran")
												: t("questNodeRunnerTitleWithEx", "{{exchange}} Node Runner Veteran", { exchange: targetExLabel }));
									})()}
								</h3>
								<p className="mt-0.5 text-xs text-muted-foreground">
									{(() => {
										const rawDesc = quest.description?.trim() || "";
										const isGeneratedDesc = Boolean(
											!rawDesc ||
											/^(connect (your|an|the)|rewards users|run an active node|запустите активную ноду|подключите)/i.test(rawDesc) ||
											((isUniversal || targetExKey !== "bitget") && /bitget/i.test(rawDesc)) ||
											rawDesc.includes("$5 000") ||
											rawDesc.includes("$1 000") ||
											rawDesc.includes("$5,000") ||
											rawDesc.includes("$1,000")
										);
										if (!isGeneratedDesc && rawDesc) {
											return rawDesc;
										}
										return isApi
											? (isUniversal
												? t("questApiPioneerDescUniversal", "Подключите API-ключ любой поддерживаемой биржи ({{exchanges}}) и совершите верифицированный объем торгов от ${{threshold}}.", {
														exchanges: exchangesListStr,
														threshold: volumeThreshold.toLocaleString(),
												  })
												: t("questApiPioneerDescWithEx", "Подключите ваш API-ключ {{exchange}} и совершите верифицированный объем торгов от ${{threshold}}.", {
														exchange: targetExLabel,
														threshold: volumeThreshold.toLocaleString(),
												  }))
											: (isUniversal
												? t("questNodeRunnerDescUniversal", "Запустите активную ноду от {{days}} дней с привязанным кошельком, торгуйте на поддерживаемых биржах ({{exchanges}}) и наберите объем от ${{threshold}} на своем сервере.", {
														days: minNodeAgeDays,
														exchanges: exchangesListStr,
														threshold: volumeThreshold.toLocaleString(),
												  })
												: t("questNodeRunnerDescWithEx", "Запустите активную ноду от {{days}} дней с привязанным кошельком, торгуйте на {{exchange}} и наберите объем от ${{threshold}} на своем сервере.", {
														days: minNodeAgeDays,
														exchange: targetExLabel,
														threshold: volumeThreshold.toLocaleString(),
												  }));
									})()}
								</p>

								{quest.rewardType === "nft" ? (
									(() => {
										const defaultTheme = quest.nftTokenId === 2 ? "purple" : quest.nftTokenId === 0 ? "cyan" : "gold";
										const qTheme = getQuestColorTheme(quest.nftColorTheme, defaultTheme);
										const passImgUrl = getNftPassImageUrl(quest.nftTokenId ?? (isApi ? 1 : 2), quest.nftImageUrl);
										const isNoBoost = quest.nftTokenId === 0 || quest.nftMultiplier === "1.0x" || quest.nftMultiplier === "1x" || quest.nftMultiplier === "None";

										return (
											<div className={`my-4 rounded-xl border p-3.5 shadow-lg relative overflow-hidden group transition-all duration-300 ${qTheme.borderClass} ${qTheme.glowClass} ${qTheme.bgGradientClass}`}>
												<div className="flex gap-3.5 items-center">
													<div className="relative h-24 w-16 shrink-0 rounded-lg overflow-hidden border shadow-md bg-black" style={{ borderColor: `${qTheme.color}80` }}>
														<img
															src={passImgUrl}
															alt={quest.nftName || "NFT Genesis Pass"}
															className="h-full w-full object-cover transition-transform duration-500 group-hover:scale-110"
															onError={(e) => {
																const target = e.currentTarget;
																const fallback = getNftPassImageUrl(quest.nftTokenId ?? (isApi ? 1 : 2));
																if (target.src !== fallback) target.src = fallback;
															}}
														/>
														<div className="absolute top-1 left-1 rounded bg-black/80 px-1 py-0.5 text-[8px] font-mono font-bold text-white border border-white/20">
															#{quest.nftTokenId ?? (isApi ? 1 : 2)}
														</div>
													</div>
													<div className="min-w-0 flex-1 space-y-1">
														<div className="flex items-center gap-1.5 flex-wrap">
															<span className={`rounded-full border px-2 py-0.5 text-[9px] font-mono font-bold ${qTheme.badgeClass}`}>
																ERC-1155 Pass
															</span>
															<span className="rounded-full border border-blue-500/40 bg-blue-500/20 px-2 py-0.5 text-[9px] font-bold text-blue-300">
																Arbitrum One
															</span>
															<span className={`rounded-full border px-2 py-0.5 text-[9px] font-black font-mono ${qTheme.badgeClass}`}>
																{isNoBoost ? "1:1 Voucher" : `${quest.nftMultiplier || (quest.nftTokenId === 2 ? "2.0x" : "1.5x")} Boost`}
															</span>
														</div>
														<h4 className="text-xs sm:text-sm font-black text-white truncate">
															{quest.nftName || (quest.nftTokenId === 2 ? "DepthSight Apex Syndicate Pass" : quest.nftTokenId === 0 ? "DepthSight Genesis Pass" : "DepthSight Core Syndicate Pass")}
														</h4>
														<div className="text-[11px] text-white/70 font-mono flex items-center gap-1.5 flex-wrap">
															<span className={`font-bold ${qTheme.accentTextClass}`}>
																{(quest.nftNominal || quest.reward).toLocaleString()} $DEPTH
															</span>
															<span className="text-white/40">• 1:1 at TGE</span>
															<span className="text-white/40">• Supply: {quest.nftMaxSupply || quest.totalSlots}</span>
														</div>
													</div>
												</div>
											</div>
										);
									})()
								) : (
									<div className="my-4 inline-flex items-center gap-2 rounded-lg border border-amber-500/30 bg-amber-500/10 px-3 py-1.5">
										<span className="text-base">💰</span>
										<span className="text-sm font-black text-amber-400 font-mono">
											{quest.reward.toLocaleString()} $DEPTH
										</span>
										<span className="text-[11px] text-muted-foreground">
											{quest.isClaimed ? t("questClaimedLabel", "claimed") : t("questRewardLabel", "reward")}
										</span>
									</div>
								)}

								{/* Slots Progress Bar */}
								<div className="mb-4 space-y-1.5">
									<div className="flex items-center justify-between text-xs text-muted-foreground font-mono">
										<span>{t("questSlotsClaimed", "Slots Claimed")}</span>
										<span className="text-white font-semibold">
											{quest.claimedSlots.toLocaleString()} / {quest.totalSlots.toLocaleString()}
										</span>
									</div>
									<div className="h-1.5 w-full overflow-hidden rounded-full bg-muted/20">
										<div
											className={`h-full rounded-full transition-all duration-500 ${
												quest.rewardType === "nft"
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
								<div className="space-y-2.5 rounded-xl border border-white/10 bg-white/[0.02] p-4 mb-5 text-xs backdrop-blur-sm">
									{/* Requirement 1: API Key / UID */}
									<div className="flex items-center justify-between gap-2">
										<div className="flex items-center gap-2 text-muted-foreground">
											<span
												className={`flex h-4 w-4 shrink-0 items-center justify-center rounded text-[10px] font-bold ${
													reqs.hasExchangeKey
														? "bg-[#1DA2B4]/25 text-[#00F0FF] border border-[#00F0FF]/40"
														: "bg-muted/20 text-muted-foreground border border-border/60"
												}`}
											>
												{reqs.hasExchangeKey ? "✓" : "○"}
											</span>
											<span>
												{isUniversal
													? t("questReqApiKeyUniversal", "Активный API-ключ биржи ({{exchanges}}) или кошелек подключен", {
															exchanges: exchangesListStr,
													  })
													: t("questReqApiKey", "API-ключ {{exchange}} подключен (Master UID)", {
															exchange: targetExLabel.toUpperCase(),
													  })}
											</span>
										</div>
										{reqs.exchangeUid ? (
											<span className="font-mono text-[11px] font-bold text-[#00F0FF]">
												{reqs.exchangeUid}
											</span>
										) : reqs.hasExchangeKey ? (
											<span className="text-[10px] text-emerald-400 font-semibold">
												{t("questStatusConnected", "Connected")}
											</span>
										) : (
											<span className="text-[10px] text-destructive">
												{t("questStatusNotConnected", "Not connected")}
											</span>
										)}
									</div>

									{/* Requirement 2: Wallet linked & verified (Both API quest and Node runner quest) */}
									<div className="flex items-center justify-between gap-2">
										<div className="flex items-center gap-2 text-muted-foreground">
											<span
												className={`flex h-4 w-4 shrink-0 items-center justify-center rounded text-[10px] font-bold ${
													reqs.hasWallet
														? "bg-[#1DA2B4]/25 text-[#00F0FF] border border-[#00F0FF]/40"
														: "bg-muted/20 text-muted-foreground border border-border/60"
												}`}
											>
												{reqs.hasWallet ? "✓" : "○"}
											</span>
											<span>{t("questReqWallet", "Wallet linked & verified")}</span>
										</div>
										<span className="font-mono text-[11px] text-white">
											{reqs.hasWallet
												? t("questStatusLinked", "Linked")
												: t("questStatusMissing", "Missing")}
										</span>
									</div>

									{/* Node Runner specific items */}
									{!isApi && (
										<>
											<div className="flex items-center justify-between gap-2">
												<div className="flex items-center gap-2 text-muted-foreground">
													<span
														className={`flex h-4 w-4 shrink-0 items-center justify-center rounded text-[10px] font-bold ${
															isPhysicalNodeOldEnough
																? "bg-[#1DA2B4]/25 text-[#00F0FF] border border-[#00F0FF]/40"
																: "bg-muted/20 text-muted-foreground border border-border/60"
														}`}
													>
														{isPhysicalNodeOldEnough ? "✓" : "○"}
													</span>
													<span>
														{t("questReqPhysicalNode", "Server online now, node registered ≥ {{days}} days ago", {
															days: minNodeAgeDays,
														})}
													</span>
												</div>
											<span className="font-mono text-[11px] text-white">
												{reqs.isPhysicalNode
													? t("questNodeAgeDays", "{{days}} days", { days: nodeAgeDays })
													: t("questStatusNotRunning", "Not running")}
											</span>
											</div>

											<div className="flex items-center justify-between gap-2">
												<div className="flex items-center gap-2 text-muted-foreground">
													<span
														className={`flex h-4 w-4 shrink-0 items-center justify-center rounded text-[10px] font-bold ${
															reqs.hasActiveMining
																? "bg-[#1DA2B4]/25 text-[#00F0FF] border border-[#00F0FF]/40"
																: "bg-muted/20 text-muted-foreground border border-border/60"
														}`}
													>
														{reqs.hasActiveMining ? "✓" : "○"}
													</span>
												<span>
													{t("questReqActiveMining", "Active mining (trade in last {{days}} days)", {
														days: tradeWindowDays,
													})}
												</span>
												</div>
												<span className="font-mono text-[11px] text-white">
													{reqs.hasActiveMining
														? t("questStatusActive", "Active")
														: t("questStatusNoTrades", "No recent trades")}
												</span>
											</div>
										</>
									)}

									{/* Requirement: Trading Volume */}
									<div className="space-y-1.5 pt-1">
										<div className="flex items-center justify-between text-muted-foreground">
											<div className="flex items-center gap-2">
												<span
													className={`flex h-4 w-4 shrink-0 items-center justify-center rounded text-[10px] font-bold ${
														isVolumeVerified
															? "bg-[#1DA2B4]/25 text-[#00F0FF] border border-[#00F0FF]/40"
															: isVolumeVerifying
															? "bg-amber-500/20 text-amber-400 border border-amber-500/40 animate-pulse"
															: "bg-muted/20 text-muted-foreground border border-border/60"
													}`}
												>
													{isVolumeVerified ? "✓" : isVolumeVerifying ? "⏳" : "○"}
												</span>
												<span>
													{isApi
														? t("questReqVolume", "Reach ${{threshold}} verified volume", {
																threshold: volumeThreshold.toLocaleString(),
														  })
														: t(
																"questReqVolumePhysical",
																"Reach ${{threshold}} verified volume on your server",
																{
																	threshold: volumeThreshold.toLocaleString(),
																}
														  )}
												</span>
											</div>
											<span className={`font-mono text-[11px] font-bold ${isVolumeVerified ? "text-[#00F0FF]" : isVolumeVerifying ? "text-amber-400" : "text-white"}`}>
												${totalVolume.toFixed(2)} / ${volumeThreshold.toLocaleString()}
											</span>
										</div>
										<div className="h-1.5 w-full overflow-hidden rounded-full bg-muted/20">
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
											<div className="flex items-center justify-between text-[10px] text-amber-400/90 pt-0.5 font-medium">
												<span className="flex items-center gap-1.5">
													<span className="inline-block h-1.5 w-1.5 rounded-full bg-amber-400 animate-ping" />
													{t("questVolumePendingVerification", "Volume reached • Awaiting broker verification")}
												</span>
												<span className="font-mono text-[10px] text-muted-foreground">
													(${verifiedVolume.toFixed(2)} {t("questVerifiedSuffix", "verified")})
												</span>
											</div>
										)}
									</div>
								</div>
							</div>

							{/* Action Button */}
							<div>
								{quest.isClaimed ? (
									<Button
										disabled
										variant="outline"
										className={`w-full cursor-default font-semibold ${
											quest.rewardType === "nft"
												? "border-purple-500/40 bg-purple-500/10 text-purple-300"
												: "border-[#1DA2B4]/40 bg-[#1DA2B4]/10 text-[#00F0FF]"
										}`}
									>
										<Check className="mr-2 h-4 w-4" />
										{quest.rewardType === "nft"
											? `✓ Pass #${quest.nftTokenId ?? (isApi ? 1 : 2)} Reserved (Thirdweb Airdrop Voucher)`
											: t("questRewardClaimedBtn", "Reward Claimed — {{amount}} $DEPTH Added", {
													amount: quest.reward.toLocaleString(),
											  })}
									</Button>
								) : quest.allRequirementsMet ? (
									<Button
										onClick={() => handleClaim(quest)}
										disabled={isClaiming}
										className={`w-full font-bold shadow-lg hover:opacity-95 animate-pulse ${
											quest.rewardType === "nft"
												? "bg-gradient-to-r from-purple-500 via-indigo-500 to-cyan-400 text-white shadow-[0_4px_20px_rgba(168,85,247,0.4)]"
												: "bg-gradient-to-r from-[#1DA2B4] to-[#00F0FF] text-slate-950 shadow-[0_4px_20px_rgba(0,240,255,0.4)] hover:shadow-[0_6px_25px_rgba(0,240,255,0.6)]"
										}`}
									>
										<Sparkles className="mr-2 h-4 w-4" />
										{isClaiming
											? t("questClaiming", "Processing...")
											: quest.rewardType === "nft"
											? `💎 Reserve Pass #${quest.nftTokenId ?? (isApi ? 1 : 2)} (${(quest.nftNominal || quest.reward).toLocaleString()} $DEPTH)`
											: t("questClaimBtn", "🎉 Claim {{amount}} $DEPTH", {
													amount: quest.reward.toLocaleString(),
											  })}
									</Button>
								) : isVolumeVerifying ? (
									<Button
										disabled
										variant="outline"
										className="w-full border-amber-500/40 bg-amber-500/10 text-amber-400 cursor-not-allowed font-semibold flex items-center justify-center gap-2 shadow-[0_0_15px_rgba(245,158,11,0.15)]"
									>
										<Loader2 className="h-4 w-4 animate-spin text-amber-400" />
										<span>{t("questVolumeVerifyingBtn", "Verifying Trading Volume...")}</span>
									</Button>
								) : (
									<Button
										disabled
										variant="outline"
										className="w-full bg-muted/10 text-muted-foreground cursor-not-allowed border-border/40 font-medium text-xs"
									>
										{t("questCompleteRequirements", "Complete all requirements to claim")}
									</Button>
								)}
							</div>
						</div>
					);
				});
			})()}
			</div>
			)}

			{/* ───────── LIVE LEADERBOARD (TOP 20) ───────── */}
			{activeSubTab === "leaderboard" && (
			<div className="glass relative rounded-2xl border border-white/10 shadow-xl overflow-hidden p-6 space-y-5">
				<div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
					<div>
						<div className="flex items-center gap-2.5">
							<Trophy className="h-5 w-5 text-amber-400" />
							<h3 className="text-lg font-black text-white">
								{t("promoLeaderboardTitle", "Лидерборд по объемам (Top 20)")}
							</h3>
							<span className="rounded-full border border-cyan-500/40 bg-cyan-500/10 px-2.5 py-0.5 text-[10px] font-black uppercase tracking-wider text-cyan-300">
								Live
							</span>
						</div>
						<p className="mt-1 text-xs text-white/60 max-w-xl">
							{t(
								"promoLeaderboardSub",
								"Топ-20 участников по объему фьючерсов (квалификация ≥ 1 000 USDT) делят разблокированный призовой фонд до 3 000 USDT. Рейтинг рассчитывается по привязанному кошельку Arbitrum One."
							)}
						</p>
					</div>

					<div className="flex items-center gap-3 shrink-0">
						<div className="rounded-xl border border-white/10 bg-black/40 px-3.5 py-2 text-right backdrop-blur-md">
							<div className="text-[10px] uppercase font-bold text-white/50">
								{t("promoLeaderboardUnlockedPool", "Разблокированный пул")}
							</div>
							<div className="text-sm font-black font-mono text-[#00F0FF]">
								${(leaderboardData?.unlockedPoolUsdt || 0).toLocaleString()} USDT
							</div>
						</div>
						<div className="rounded-xl border border-white/10 bg-black/40 px-3.5 py-2 text-right backdrop-blur-md">
							<div className="text-[10px] uppercase font-bold text-white/50">
								{t("promoLeaderboardTotalParticipants", "Участников")}
							</div>
							<div className="text-sm font-black font-mono text-white">
								{leaderboardData?.totalParticipants || (leaderboardData?.top?.length ?? 0)}
							</div>
						</div>
					</div>
				</div>

				{/* Table / List */}
				<div className="overflow-x-auto rounded-xl border border-white/10 bg-black/25">
					<table className="w-full text-left text-xs">
						<thead>
							<tr className="border-b border-white/10 bg-white/[0.02] text-[11px] font-semibold text-white/50">
								<th className="py-3 px-4 w-16">#</th>
								<th className="py-3 px-4">{t("promoColWallet", "Кошелек (Arbitrum)")}</th>
								<th className="py-3 px-4 text-right">{t("promoColVolume", "Объем фьючерсов")}</th>
								<th className="py-3 px-4 text-right">{t("promoColShare", "Доля пула")}</th>
								<th className="py-3 px-4 text-right">{t("promoColReward", "Расчетная награда")}</th>
							</tr>
						</thead>
						<tbody className="divide-y divide-white/5">
							{isLoadingLeaderboard ? (
								<tr>
									<td colSpan={5} className="py-8 text-center text-white/50">
										<div className="flex items-center justify-center gap-2">
											<Loader2 className="h-4 w-4 animate-spin text-cyan-400" />
											<span>{t("promoLeaderboardLoading", "Загрузка лидерборда...")}</span>
										</div>
									</td>
								</tr>
							) : !leaderboardData?.top || leaderboardData.top.length === 0 ? (
								<tr>
									<td colSpan={5} className="py-8 text-center text-white/50">
										{t("promoLeaderboardEmpty", "Лидерборд формируется. Совершите сделки на фьючерсах от $1 000, чтобы занять 1-е место!")}
									</td>
								</tr>
							) : (
								<>
									{leaderboardData.top.map((entry) => {
										const isTop1 = entry.rank === 1;
										const isTop2 = entry.rank === 2;
										const isTop3 = entry.rank === 3;
										const isMe = Boolean(entry.isCurrentUser);

										return (
											<tr
												key={entry.rank}
												className={`transition-colors ${
													isMe
														? "bg-cyan-500/15 text-white font-semibold shadow-[inset_0_0_12px_rgba(0,240,255,0.15)]"
														: isTop1
														? "bg-amber-500/[0.08]"
														: isTop2
														? "bg-slate-400/[0.06]"
														: isTop3
														? "bg-amber-700/[0.06]"
														: "hover:bg-white/[0.02]"
												}`}
											>
												<td className="py-3 px-4 font-mono font-bold whitespace-nowrap">
													{isTop1 ? (
														<span className="inline-flex items-center gap-1.5 whitespace-nowrap rounded-md bg-amber-500/20 px-2 py-0.5 text-amber-300 border border-amber-500/30">
															<span className="leading-none">🥇</span>
															<span className="leading-none">1</span>
														</span>
													) : isTop2 ? (
														<span className="inline-flex items-center gap-1.5 whitespace-nowrap rounded-md bg-slate-400/20 px-2 py-0.5 text-slate-200 border border-slate-400/30">
															<span className="leading-none">🥈</span>
															<span className="leading-none">2</span>
														</span>
													) : isTop3 ? (
														<span className="inline-flex items-center gap-1.5 whitespace-nowrap rounded-md bg-amber-700/20 px-2 py-0.5 text-amber-400 border border-amber-700/30">
															<span className="leading-none">🥉</span>
															<span className="leading-none">3</span>
														</span>
													) : (
														<span className="text-white/60">#{entry.rank}</span>
													)}
												</td>
												<td className="py-3 px-4 font-mono">
													<div className="flex items-center gap-2">
														<span className={isMe ? "text-[#00F0FF] font-bold" : "text-white/90"}>
															{entry.walletAddress}
														</span>
														{isMe && (
															<span className="rounded bg-cyan-400/20 px-1.5 py-0.5 text-[9px] font-bold uppercase text-cyan-300 border border-cyan-400/40">
																{t("promoYouBadge", "Вы")}
															</span>
														)}
													</div>
												</td>
												<td className="py-3 px-4 text-right font-mono font-semibold text-white">
													${entry.volumeUsdt.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
												</td>
												<td className="py-3 px-4 text-right font-mono text-white/60">
													{entry.volumeUsdt >= 1000 ? `${entry.rewardSharePct}%` : "—"}
												</td>
												<td className="py-3 px-4 text-right font-mono font-bold text-[#00F0FF]">
													{entry.volumeUsdt >= 1000 && entry.estimatedRewardUsdt > 0 ? (
														leaderboardData.unlockedPoolUsdt > 0 ? (
															`${entry.estimatedRewardUsdt.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })} USDT`
														) : (
															<div className="flex flex-col items-end leading-tight">
																<span className="text-[#00F0FF]">
																	~{entry.estimatedRewardUsdt.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })} USDT*
																</span>
																<span className="text-[10px] text-white/50 font-normal">
																	{t("promoLeaderboardTier1Unlock", "при открытии Тир-1 (15M)")}
																</span>
															</div>
														)
													) : (
														<span className="text-white/40">0 USDT</span>
													)}
												</td>
											</tr>
										);
									})}

									{/* Current user sticky bottom row if rank > 20 */}
									{leaderboardData.myEntry && leaderboardData.myEntry.rank > 20 && (
										<>
											<tr>
												<td colSpan={5} className="py-2 text-center text-white/20 text-xs tracking-widest font-mono">
													• • •
												</td>
											</tr>
											<tr className="bg-cyan-500/20 border-t-2 border-cyan-500/50 text-white font-semibold shadow-[0_0_20px_rgba(0,240,255,0.2)]">
												<td className="py-3 px-4 font-mono font-bold text-cyan-300">
													#{leaderboardData.myEntry.rank}
												</td>
												<td className="py-3 px-4 font-mono">
													<div className="flex items-center gap-2">
														<span className="text-[#00F0FF] font-bold">
															{leaderboardData.myEntry.walletAddress}
														</span>
														<span className="rounded bg-cyan-400/30 px-1.5 py-0.5 text-[9px] font-bold uppercase text-cyan-200 border border-cyan-400/50">
															{t("promoYouBadge", "Вы")}
														</span>
													</div>
												</td>
												<td className="py-3 px-4 text-right font-mono font-bold text-white">
													${leaderboardData.myEntry.volumeUsdt.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
												</td>
												<td className="py-3 px-4 text-right font-mono text-white/60">
													—
												</td>
												<td className="py-3 px-4 text-right font-mono font-bold text-white/60">
													0 USDT
												</td>
											</tr>
										</>
									)}
								</>
							)}
						</tbody>
					</table>
				</div>

				{/* Asterisk explanation footnote when pool is not yet unlocked */}
				{leaderboardData && leaderboardData.unlockedPoolUsdt === 0 && (
					<p className="text-[11px] text-white/40 italic px-1">
						{t(
							"promoLeaderboardAsteriskNote",
							"* Награды рассчитываются от фонда 1-го уровня ($500) и активируются после достижения рубежа в 15 млн USDT совокупного объёма."
						)}
					</p>
				)}

				{/* Distance to Top 20 callout */}
				{leaderboardData?.volumeToTop20 !== undefined && leaderboardData?.volumeToTop20 !== null && leaderboardData.volumeToTop20 > 0 && (
					<div className="flex items-center justify-between rounded-xl border border-cyan-500/30 bg-cyan-500/10 px-4 py-3 text-xs text-cyan-300 shadow-inner">
						<div className="flex items-center gap-2">
							<TrendingUp className="h-4 w-4 text-cyan-400 shrink-0" />
							<span>
								{t(
									"promoVolumeToTop20Notice",
									"До попадания в Top 20 осталось набрать ${{volume}} объёма на фьючерсах",
									{ volume: leaderboardData.volumeToTop20.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 }) }
								)}
							</span>
						</div>
						<span className="font-mono font-bold text-cyan-400 text-[11px] shrink-0 ml-2">
							{t("promoTargetTop20", "Цель: Топ 20")}
						</span>
					</div>
				)}
			</div>
			)}

			{/* Footer Security Notes */}
			<div className="glass flex flex-wrap items-center justify-center gap-6 sm:gap-8 rounded-2xl border border-white/10 px-6 py-4 text-xs text-white/60 text-center">
				<div className="flex items-center gap-2">
					<ShieldCheck className="h-4 w-4 text-[#00F0FF]" />
					<span>
						{isUniversal
							? t("questFootnoteUidUniversal", "Один клейм на уникальный аккаунт поддерживаемой биржи ({{exchanges}})", {
									exchanges: exchangesListStr,
							  })
							: t("questFootnoteUid", "One claim per unique {{exchange}} master UID", {
									exchange: targetExLabel.toUpperCase(),
							  })}
					</span>
				</div>
				<div className="flex items-center gap-2">
					<Clock className="h-4 w-4 text-[#00F0FF]" />
					<span>{t("questFootnoteDuration", "Campaign runs until all slots are claimed")}</span>
				</div>
				<div className="flex items-center gap-2">
					<Check className="h-4 w-4 text-[#00F0FF]" />
					<span>{t("questFootnoteVerification", "Only broker-verified trading volume counts")}</span>
				</div>
			</div>
		</div>
	);
};
