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
} from "lucide-react";
import { api } from "../../services/api";
import { BitgetLogoSvg } from "./BitgetLogoSvg";

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
	reward: number;
	claimedSlots: number;
	totalSlots: number;
	remainingSlots: number;
	isClaimed?: boolean;
	allRequirementsMet?: boolean;
	requirements?: PromoQuestRequirements;
	[key: string]: unknown;
}

interface PromoModalStatus {
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
}

export const PromoCampaignModal: React.FC<PromoCampaignModalProps> = ({
	isOpen,
	onClose,
	promoStatus,
	onRefresh,
	nodeUuid,
}) => {
	const { t } = useTranslation("pwa-common");
	const [claimingType, setClaimingType] = useState<string | null>(null);

	if (!isOpen || !promoStatus?.hasActiveCampaign) {
		return null;
	}

	const handleClaim = async (quest: PromoQuest) => {
		if (!promoStatus?.campaignId || claimingType) return;

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

	const exchangeName = (promoStatus.exchangeId || "bitget").toUpperCase();

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
							<BitgetLogoSvg className="h-full w-full drop-shadow-[0_2px_8px_rgba(29,162,180,0.4)]" />
						</div>
						<div className="min-w-0">
							<h2 className="text-base font-black text-foreground dark:text-white leading-tight">
								{promoStatus.campaignName ||
									t("mining.promoQuestsTitle", "Bitget Launch Quests")}
							</h2>
							<p className="mt-1 text-xs text-muted-foreground leading-snug">
								{promoStatus.description ||
									t(
										"mining.promoQuestsDescription",
										"Complete quests to earn $DEPTH tokens from the promotional pool.",
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

				{/* Quests List */}
				<div className="space-y-4">
					{promoStatus?.quests?.map((quest: PromoQuest) => {
						const isApi = quest.questType === "api_volume";
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
													<BitgetLogoSvg className="h-full w-full" />
												) : (
													<Server className="h-5 w-5" />
												)}
											</div>
											<div>
												<h3 className="text-sm font-bold text-card-foreground tracking-tight">
													{isApi
														? t("mining.questApiPioneerTitle", quest.title)
														: t("mining.questNodeRunnerTitle", quest.title)}
												</h3>
												<div className="text-[10px] text-muted-foreground font-mono">
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

									{/* Reward Banner */}
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

									{/* Slots Progress Bar */}
									<div className="mb-3 space-y-1">
										<div className="h-1.5 w-full overflow-hidden rounded-full bg-muted dark:bg-white/10">
											<div
												className={`h-full rounded-full transition-all duration-500 ${
													isApi
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
													{t("mining.questReqApiKey", "{{exchange}} API Key connected (Master UID)", {
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
															{t("mining.questReqActiveMining", "Active mining (trade in last 7 days)")}
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
								<div>
									{quest.isClaimed ? (
										<button
											type="button"
											disabled
											className="w-full flex items-center justify-center gap-2 rounded-xl border border-cyan-500/40 bg-cyan-500/10 py-2.5 text-xs font-bold text-cyan-600 dark:text-[#00F0FF] cursor-default opacity-85"
										>
											<Check className="h-4 w-4" />
											{t("mining.questRewardClaimedBtn", "Reward Claimed — {{amount}} $DEPTH Added", {
												amount: quest.reward.toLocaleString(),
											})}
										</button>
									) : quest.allRequirementsMet ? (
										<button
											type="button"
											onClick={() => handleClaim(quest)}
											disabled={isThisClaiming}
											className="w-full flex items-center justify-center gap-2 rounded-xl bg-gradient-to-r from-[#1DA2B4] to-[#00F0FF] py-2.5 text-xs font-black text-slate-950 shadow-[0_4px_20px_rgba(0,240,255,0.4)] transition-all active:scale-[0.98] hover:opacity-95"
										>
											{isThisClaiming ? (
												<Loader2 className="h-4 w-4 animate-spin" />
											) : (
												<Sparkles className="h-4 w-4" />
											)}
											{isThisClaiming
												? t("mining.questClaiming", "Processing...")
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
							</div>
						);
					})}
				</div>

				{/* Footer Security Notes */}
				<div className="space-y-2 rounded-xl border border-border bg-card p-3 text-[11px] text-muted-foreground">
					<div className="flex items-center gap-2">
						<ShieldCheck className="h-4 w-4 text-cyan-600 dark:text-[#00F0FF] shrink-0" />
						<span>
							{t(
								"mining.questFootnoteUid",
								"One claim per unique Bitget master account UID",
							)}
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
