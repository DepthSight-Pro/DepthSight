// pwa/components/mining/PromoBannerPwa.tsx
import React from "react";
import { useTranslation } from "react-i18next";
import { ArrowRight, Lock, Gift, Globe } from "lucide-react";
import { BitgetLogoSvg } from "./BitgetLogoSvg";
import { exchangeLabels, exchangeLogos, normalizeExchangeKey } from "../../lib/exchanges";

interface PromoQuestSlots {
	totalSlots?: number;
	claimedSlots?: number;
	[key: string]: unknown;
}

export interface PromoBannerStatus {
	hasActiveCampaign?: boolean;
	quests?: PromoQuestSlots[];
	distributed?: number;
	totalPool?: number;
	remainingPool?: number;
	campaignName?: string;
	description?: string;
	exchangeId?: string;
	isAdminPreview?: boolean;
	isPenalty?: boolean;
	rebateMultiplier?: number;
	[key: string]: unknown;
}

export interface PromoBannerPwaProps {
	promoStatus: PromoBannerStatus | null;
	onOpenQuests: () => void;
	isPenalty?: boolean;
}

export const PromoBannerPwa: React.FC<PromoBannerPwaProps> = ({
	promoStatus,
	onOpenQuests,
	isPenalty = false,
}) => {
	const { t } = useTranslation("pwa-common");

	const isPenaltyMode = Boolean(
		isPenalty ||
		promoStatus?.isPenalty ||
		(typeof promoStatus?.rebateMultiplier === "number" && promoStatus.rebateMultiplier < 0)
	);

	if (!promoStatus?.hasActiveCampaign && !isPenaltyMode) {
		return null;
	}

	if (isPenaltyMode) {
		return (
			<div
				onClick={onOpenQuests}
				role="button"
				tabIndex={0}
				className="group relative cursor-pointer overflow-hidden rounded-2xl border border-white/10 dark:border-white/10 bg-[#0c1017]/90 dark:bg-[#0c1017]/90 p-3.5 sm:p-4 transition-all duration-300 active:scale-[0.98] hover:border-white/20 shadow-md"
			>
				<div className="relative flex items-center justify-between gap-3">
					{/* Left: Icon & Text */}
					<div className="flex items-center gap-3 min-w-0">
						<div className="relative flex h-10 w-10 sm:h-11 sm:w-11 shrink-0 items-center justify-center rounded-xl border border-white/10 bg-white/[0.04] p-1.5 shadow-sm">
							<BitgetLogoSvg isMuted className="h-full w-full" />
						</div>

						<div className="min-w-0">
							<div className="flex flex-wrap items-center gap-1.5">
								<h3 className="text-xs sm:text-sm font-bold text-white tracking-tight leading-snug">
									{promoStatus?.campaignName || t("mining.promoBannerRevokedTitle", "Bitget Launch Airdrop")}
								</h3>
								<span className="text-[11px] sm:text-xs font-bold text-rose-500 tracking-wide flex items-center gap-1">
									• {t("mining.promoBannerRevokedStatus", "PARTNERSHIP REVOKED")}
								</span>
								<span className="rounded-full border border-white/15 bg-white/[0.06] px-2 py-0.5 text-[8.5px] sm:text-[9.5px] font-mono font-bold uppercase tracking-wider text-zinc-300">
									{t("mining.promoBannerRevokedBadge", "REVOKED / SLA BREACH")}
								</span>
							</div>
							<p className="mt-1 text-[11px] text-zinc-400 leading-snug line-clamp-2">
								{t(
									"mining.promoBannerRevokedSubtitle",
									"This event has been permanently suspended due to unilateral partner SLA failure. All promotional rewards for Bitget API volume have been cancelled."
								)}
							</p>
						</div>
					</div>

					{/* Right: Circular Arrow Action */}
					<div className="shrink-0 pl-1">
						<div className="flex h-8 w-8 sm:h-9 sm:w-9 items-center justify-center rounded-full border border-white/15 bg-white/[0.04] text-zinc-400 transition-all group-hover:bg-white/[0.08] group-hover:text-white">
							<ArrowRight className="h-4 w-4" />
						</div>
					</div>
				</div>
			</div>
		);
	}

	const totalSlots =
		promoStatus?.quests?.reduce(
			(acc: number, q: PromoQuestSlots) => acc + (q.totalSlots ?? 0),
			0,
		) ?? 0;
	const claimedSlots =
		promoStatus?.quests?.reduce(
			(acc: number, q: PromoQuestSlots) => acc + (q.claimedSlots ?? 0),
			0,
		) ?? 0;
	const slotsLeft = Math.max(0, totalSlots - claimedSlots);

	return (
		<div
			onClick={onOpenQuests}
			role="button"
			tabIndex={0}
			className="group relative cursor-pointer overflow-hidden rounded-2xl border border-[#1DA2B4]/30 dark:border-[#1DA2B4]/40 bg-gradient-to-r from-[#1DA2B4]/15 via-sky-400/5 to-cyan-500/10 dark:from-[#1DA2B4]/20 dark:via-[#0F1923]/95 dark:to-blue-500/10 bg-card p-4 transition-all duration-300 active:scale-[0.98] hover:border-[#1DA2B4]/60 dark:hover:border-[#00F0FF]/70 shadow-sm hover:shadow-md dark:shadow-none dark:hover:shadow-[0_8px_30px_rgba(29,162,180,0.25)]"
		>
			{/* Ambient background glow */}
			<div className="pointer-events-none absolute -right-10 -top-10 h-48 w-48 rounded-full bg-[radial-gradient(circle,rgba(0,240,255,0.12)_0%,rgba(29,162,180,0.04)_50%,transparent_70%)]" />

			{/* Top Header: Logo + Title + Status Badge */}
			{(() => {
				const isUniversal = promoStatus.exchangeId === "all";
				const targetExKey = isUniversal ? "all" : normalizeExchangeKey(promoStatus.exchangeId as string | undefined);
				const targetExLogo = targetExKey && targetExKey !== "all" ? exchangeLogos[targetExKey] : null;
				const targetExLabel = isUniversal
					? "All Supported Exchanges"
					: (targetExKey ? exchangeLabels[targetExKey] : null) || (promoStatus.exchangeId as string) || "Partner";

				return (
					<div className="flex items-start gap-3">
						<div className="relative flex h-11 w-11 shrink-0 items-center justify-center rounded-xl border border-[#1DA2B4]/30 dark:border-[#00F0FF]/40 bg-[#1DA2B4]/15 dark:bg-[#1DA2B4]/20 p-2 shadow-sm dark:shadow-[0_0_15px_rgba(0,240,255,0.35)]">
							{isUniversal ? (
								<Globe className="h-5 w-5 text-cyan-400" />
							) : targetExKey === "bitget" ? (
								<BitgetLogoSvg className="h-full w-full drop-shadow-[0_2px_8px_rgba(0,240,255,0.4)]" />
							) : targetExLogo ? (
								<img src={targetExLogo} alt={targetExLabel} className="h-full w-full object-contain" />
							) : (
								<Gift className="h-5 w-5 text-cyan-400" />
							)}
						</div>

						<div className="min-w-0 flex-1">
							<div className="flex flex-wrap items-center gap-1.5">
								<h3 className="text-sm font-bold text-foreground dark:text-white tracking-tight leading-snug">
									{promoStatus.campaignName || `${targetExLabel} Launch Airdrop`}
								</h3>
								{promoStatus.isAdminPreview ? (
									<span className="inline-flex items-center gap-1 rounded-full border border-amber-500/40 bg-amber-500/15 px-2 py-0.5 text-[9px] font-black uppercase tracking-wider text-amber-500 dark:text-amber-400">
										<Lock className="h-2 w-2" />
										{t("mining.adminPreviewBadge", "ADMIN PREVIEW")}
									</span>
								) : (
									<span className="inline-flex items-center gap-1 rounded-full border border-[#00F0FF]/40 bg-[#1DA2B4]/15 px-2 py-0.5 text-[9px] font-extrabold uppercase tracking-widest text-cyan-600 dark:text-[#00F0FF] shadow-[0_0_10px_rgba(0,240,255,0.3)] animate-pulse">
										<span className="h-1.5 w-1.5 rounded-full bg-cyan-600 dark:bg-[#00F0FF]" />
										{t("mining.liveBadge", "LIVE")}
									</span>
								)}
							</div>
							<p className="mt-1 text-[11px] text-muted-foreground leading-tight line-clamp-2">
								{promoStatus.description ||
									(isUniversal
										? "Connect any supported exchange API key & trade to earn exclusive Genesis NFT Passes and $DEPTH rewards."
										: `Connect ${targetExLabel} API keys & trade to earn up to 25,000 $DEPTH per quest.`)}
							</p>
						</div>
					</div>
				);
			})()}

			{/* Bottom Metrics Bar (Variant 2: Slots · Pool · Claimed) */}
			<div className="mt-3.5 pt-3 border-t border-border/60 dark:border-white/10 flex items-center justify-between gap-2">
				<div className="flex items-center gap-3 sm:gap-4">
					<div>
						<div className="text-xs sm:text-sm font-black text-foreground dark:text-white font-mono leading-none">
							{slotsLeft.toLocaleString()}
						</div>
						<div className="text-[9px] uppercase tracking-wider text-muted-foreground mt-1">
							{t("mining.promoSlotsLeft", "Slots left")}
						</div>
					</div>

					<div className="border-l border-border/60 dark:border-white/10 pl-2.5 sm:pl-3">
						<div className="text-xs sm:text-sm font-black font-mono bg-gradient-to-r from-cyan-600 via-[#1DA2B4] to-blue-500 dark:from-[#00F0FF] dark:via-[#1DA2B4] dark:to-blue-400 bg-clip-text text-transparent leading-none">
							{((promoStatus?.totalPool as number) || 10_000_000).toLocaleString()}
						</div>
						<div className="text-[9px] uppercase tracking-wider text-cyan-700 dark:text-cyan-300/80 font-medium mt-1">
							{t("mining.promoAirdropPool", "Airdrop pool")}
						</div>
					</div>

					<div className="border-l border-border/60 dark:border-white/10 pl-2.5 sm:pl-3">
						<div className="text-xs sm:text-sm font-black text-foreground/90 dark:text-white/90 font-mono leading-none">
							{(promoStatus?.distributed || 0).toLocaleString()}
						</div>
						<div className="text-[9px] uppercase tracking-wider text-muted-foreground mt-1">
							{t("mining.promoClaimedShort", "Claimed")}
						</div>
					</div>
				</div>

				<div className="flex items-center gap-1.5 text-xs font-bold text-cyan-600 dark:text-[#00F0FF] bg-cyan-500/10 dark:bg-[#1DA2B4]/20 border border-cyan-500/30 dark:border-[#00F0FF]/30 rounded-xl px-2.5 py-1.5 transition-all group-hover:bg-cyan-500 group-hover:text-white dark:group-hover:bg-[#00F0FF] dark:group-hover:text-black shrink-0">
					<span>{t("mining.subtabQuests", "Quests")}</span>
					<ArrowRight className="h-3.5 w-3.5" />
				</div>
			</div>
		</div>
	);
};
