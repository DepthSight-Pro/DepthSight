// frontend/src/components/mining/PromoQuestsTab.tsx
import React from "react";
import { useTranslation } from "react-i18next";
import { Check, Clock, ShieldCheck, Sparkles, Server, Loader2, Globe } from "lucide-react";
import { Button } from "@/components/ui/button";
import { toast } from "@/components/ui/use-toast";
import { useClaimPromoQuest } from "@/lib/api";
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

			{/* Quests Grid (Supports 1, 2, or 3 Quests - Sorted by Token #0 -> #1 -> #2) */}
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
					const totalVolume = toNumber(reqs.totalVolume ?? reqs.currentVolume ?? reqs.verifiedVolume, 0);
					const verifiedVolume = toNumber(reqs.verifiedVolume, 0);
					const isVolumeVerifying = Boolean(
						reqs.isVolumeVerifying || (totalVolume >= volumeThreshold && verifiedVolume < volumeThreshold)
					);
					const isVolumeVerified = Boolean(
						reqs.isVolumeVerified || verifiedVolume >= volumeThreshold
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
