// frontend/src/components/mining/PromoBanner.tsx
import React from "react";
import { useTranslation } from "react-i18next";
import { ArrowRight, Lock, Gift, Globe } from "lucide-react";
import type { PromoStatusResponse } from "@/types/api";
import { exchangeLabels, exchangeLogos, normalizeExchangeKey } from "@/lib/exchanges";

interface PromoBannerProps {
	promoStatus: PromoStatusResponse;
	onOpenQuests: () => void;
	isPenalty?: boolean;
}

export const BitgetLogoSvg: React.FC<{ className?: string; isMuted?: boolean }> = ({
	className = "w-full h-full",
	isMuted = false,
}) => (
	<svg viewBox="0 0 200 200" fill="none" xmlns="http://www.w3.org/2000/svg" className={className}>
		<g clipPath="url(#clip0_bitget_logo_banner)">
			<circle cx="100" cy="100" r="100" fill={isMuted ? "#27272A" : "#00F0FF"} />
			<path
				d="M93.1911 80.4883H128.212L164.039 116.086C166.37 118.402 166.382 122.168 164.063 124.496L118.117 170.674H82.0405L92.9473 160.07L132.992 120.278L93.4556 80.4854"
				fill={isMuted ? "#E4E4E7" : "black"}
			/>
			<path
				d="M107.585 120.188H72.5635L36.7367 84.5904C34.4061 82.2747 34.3942 78.5083 36.7129 76.1807L82.6588 30H118.735L107.829 40.6036L67.7835 80.396L107.32 120.188"
				fill={isMuted ? "#E4E4E7" : "black"}
			/>
		</g>
		<defs>
			<clipPath id="clip0_bitget_logo_banner">
				<rect width="200" height="200" fill="white" />
			</clipPath>
		</defs>
	</svg>
);


export const PromoBanner: React.FC<PromoBannerProps> = ({ promoStatus, onOpenQuests, isPenalty = false }) => {
	const { t } = useTranslation(["mining", "common"]);

	const isPenaltyMode = Boolean(
		isPenalty ||
		promoStatus?.isPenalty ||
		(promoStatus?.rebateMultiplier !== undefined && promoStatus.rebateMultiplier < 0)
	);

	if (!promoStatus?.hasActiveCampaign && !isPenaltyMode) {
		return null;
	}

	if (isPenaltyMode) {
		return (
			<div
				onClick={onOpenQuests}
				className="group relative cursor-pointer overflow-hidden rounded-2xl border border-white/10 dark:border-white/10 bg-[#0c1017]/90 dark:bg-[#0c1017]/90 p-4 sm:p-5 transition-all duration-300 hover:border-white/20 shadow-md hover:shadow-xl"
			>
				<div className="relative flex items-center justify-between gap-4">
					{/* Left: Icon & Text */}
					<div className="flex items-center gap-4 min-w-0">
						<div className="relative flex h-11 w-11 sm:h-12 sm:w-12 shrink-0 items-center justify-center rounded-xl border border-white/10 bg-white/[0.04] p-1.5 transition-transform duration-300 group-hover:scale-105">
							<BitgetLogoSvg isMuted className="h-full w-full" />
						</div>

						<div className="min-w-0">
							<div className="flex flex-wrap items-center gap-2">
								<h3 className="text-sm sm:text-base font-bold text-white tracking-tight">
									{promoStatus?.campaignName || t("promoBannerRevokedTitle", "Bitget Launch Airdrop")}
								</h3>
								<span className="text-xs sm:text-sm font-bold text-rose-500 tracking-wide flex items-center gap-1.5">
									• {t("promoBannerRevokedStatus", "PARTNERSHIP REVOKED")}
								</span>
								<span className="rounded-full border border-white/15 bg-white/[0.06] px-2.5 py-0.5 text-[9px] sm:text-[10px] font-mono font-bold uppercase tracking-wider text-zinc-300">
									{t("promoBannerRevokedBadge", "REVOKED / PARTNERSHIP BREACH")}
								</span>
							</div>
							<p className="mt-1 text-xs text-zinc-400 font-normal leading-relaxed line-clamp-2">
								{t(
									"promoBannerRevokedSubtitle",
									"This campaign has been permanently suspended due to partner's breach of agreed launch commitments. All promotional rewards have been reallocated."
								)}
							</p>
						</div>
					</div>

					{/* Right: Circular Arrow Action */}
					<div className="shrink-0 pl-2">
						<div className="flex h-9 w-9 sm:h-10 sm:w-10 items-center justify-center rounded-full border border-white/15 bg-white/[0.04] text-zinc-400 transition-all duration-300 group-hover:translate-x-1 group-hover:bg-white/[0.08] group-hover:border-white/30 group-hover:text-white">
							<ArrowRight className="h-4 w-4" />
						</div>
					</div>
				</div>
			</div>
		);
	}

	const totalSlots = promoStatus.quests?.reduce((acc, q) => acc + (q.totalSlots || 0), 0) || 0;
	const claimedSlots = promoStatus.quests?.reduce((acc, q) => acc + (q.claimedSlots || 0), 0) || 0;
	const slotsLeft = Math.max(0, totalSlots - claimedSlots);

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
			: "All Supported Exchanges"
		: (targetExKey ? exchangeLabels[targetExKey] : null) || promoStatus.exchangeId || "Partner";

	return (
		<div
			onClick={onOpenQuests}
			className="group relative cursor-pointer overflow-hidden rounded-2xl border-2 border-[#1DA2B4]/50 dark:border-[#00E5FF]/40 bg-gradient-to-r from-[#1DA2B4]/20 via-[#0E7490]/10 to-[#00D4FF]/15 dark:from-[#1DA2B4]/25 dark:via-[#0B1A2A]/90 dark:to-[#00D4FF]/15 p-4 sm:p-5 transition-all duration-300 hover:-translate-y-0.5 hover:border-[#1DA2B4]/80 dark:hover:border-[#00E5FF]/70 shadow-[0_2px_12px_rgba(29,162,180,0.12)] hover:shadow-[0_4px_20px_rgba(29,162,180,0.25)] dark:shadow-[0_0_20px_rgba(29,162,180,0.15)] dark:hover:shadow-[0_10px_40px_rgba(0,0,0,0.5),0_0_40px_rgba(0,212,255,0.3)]"
		>
			{/* Bright ambient glow blobs */}
			<div className="pointer-events-none absolute -right-12 -top-12 h-56 w-56 rounded-full bg-[radial-gradient(circle,rgba(0,229,255,0.25)_0%,rgba(29,162,180,0.1)_40%,transparent_70%)] dark:bg-[radial-gradient(circle,rgba(0,229,255,0.2)_0%,rgba(29,162,180,0.08)_40%,transparent_70%)]" />
			<div className="pointer-events-none absolute -left-8 -bottom-8 h-40 w-40 rounded-full bg-[radial-gradient(circle,rgba(29,162,180,0.15)_0%,transparent_60%)] dark:bg-[radial-gradient(circle,rgba(0,212,255,0.12)_0%,transparent_60%)]" />

			<div className="relative flex flex-col sm:flex-row sm:items-center justify-between gap-4">
				{/* Left: Icon & Titles */}
				<div className="flex items-center gap-4 min-w-0">
					<div className="relative flex h-12 w-12 shrink-0 items-center justify-center rounded-xl border-2 border-[#1DA2B4]/40 dark:border-[#00E5FF]/50 bg-gradient-to-br from-[#1DA2B4]/25 to-[#0E7490]/15 dark:from-[#1DA2B4]/30 dark:to-[#00D4FF]/10 p-2 shadow-[0_0_12px_rgba(0,240,255,0.25)] dark:shadow-[0_0_24px_rgba(0,229,255,0.35)] transition-transform duration-300 group-hover:scale-110">
						{isUniversal ? (
							<Globe className="h-6 w-6 text-cyan-400" />
						) : targetExKey === "bitget" ? (
							<BitgetLogoSvg className="h-full w-full drop-shadow-[0_2px_8px_rgba(0,240,255,0.4)]" />
						) : targetExLogo ? (
							<img src={targetExLogo} alt={targetExLabel} className="h-full w-full object-contain" />
						) : (
							<Gift className="h-6 w-6 text-cyan-400" />
						)}
					</div>

					<div className="min-w-0">
						<div className="flex flex-wrap items-center gap-2">
							<h3 className="text-base font-bold text-foreground dark:text-white tracking-tight">
								{promoStatus.campaignName || `${targetExLabel} Launch Airdrop — 10,000,000 $DEPTH`}
							</h3>
							{promoStatus.isAdminPreview ? (
								<span className="flex items-center gap-1 rounded-full border border-amber-500/40 bg-amber-500/15 px-2.5 py-0.5 text-[10px] font-black uppercase tracking-wider text-amber-600 dark:text-amber-400">
									<Lock className="h-2.5 w-2.5" />
									{t("adminPreviewBadge", "ADMIN PREVIEW")}
								</span>
							) : (
								<span className="flex items-center gap-1.5 rounded-full border-2 border-[#00D4FF]/50 dark:border-[#00E5FF]/50 bg-[#1DA2B4]/20 dark:bg-[#00E5FF]/15 px-2.5 py-0.5 text-[10px] font-extrabold uppercase tracking-widest text-[#0E7490] dark:text-[#00E5FF] shadow-[0_0_16px_rgba(0,229,255,0.3)] animate-pulse">
									<span className="h-1.5 w-1.5 rounded-full bg-[#0E7490] dark:bg-[#00E5FF] shadow-[0_0_6px_rgba(0,229,255,0.6)]" />
									{t("liveBadge", "LIVE")}
								</span>
							)}
						</div>
						<p className="mt-0.5 truncate text-xs text-slate-600 dark:text-slate-400">
							{promoStatus.description ||
								(isUniversal
									? "Connect any supported exchange API key & trade to earn exclusive Genesis NFT Passes and $DEPTH rewards."
									: `Connect ${targetExLabel} API keys & trade to earn up to 25,000 $DEPTH per quest.`)}
						</p>
					</div>
				</div>

				{/* Right: Metrics & Arrow */}
				<div className="flex items-center justify-between sm:justify-end gap-5 sm:gap-6 sm:border-l sm:border-[#1DA2B4]/20 dark:sm:border-[#00D4FF]/15 sm:pl-6 shrink-0">
					{/* Slots Left */}
					<div className="text-left sm:text-center">
						<div className="text-base sm:text-lg font-black text-foreground dark:text-white font-mono">
							{slotsLeft.toLocaleString()}
						</div>
						<div className="text-[10px] uppercase tracking-wider text-slate-500 dark:text-slate-400">
							{t("promoSlotsLeft", "Slots left")}
						</div>
					</div>

					{/* Airdrop Pool */}
					<div className="text-left sm:text-center">
						<div className="text-base sm:text-lg font-black font-mono bg-gradient-to-r from-[#0E7490] via-[#1DA2B4] to-[#0066FF] dark:from-[#00E5FF] dark:via-[#1DA2B4] dark:to-[#60A5FA] bg-clip-text text-transparent">
							{((promoStatus.totalPool as number) || 10_000_000).toLocaleString()}
						</div>
						<div className="text-[10px] uppercase tracking-wider text-[#0E7490] dark:text-[#67E8F9] font-semibold">
							{t("promoAirdropPool", "Airdrop pool")}
						</div>
					</div>

					{/* Claimed */}
					<div className="text-left sm:text-center">
						<div className="text-base sm:text-lg font-black text-foreground dark:text-white font-mono">
							{(promoStatus.distributed || 0).toLocaleString()}
						</div>
						<div className="text-[10px] uppercase tracking-wider text-slate-500 dark:text-slate-400">
							{t("promoClaimedShort", "Claimed")}
						</div>
					</div>

					{/* Action Arrow */}
					<div className="flex h-9 w-9 items-center justify-center rounded-xl bg-[#1DA2B4]/10 dark:bg-[#00D4FF]/10 border border-[#1DA2B4]/30 dark:border-[#00D4FF]/25 text-[#0E7490] dark:text-[#67E8F9] transition-all duration-300 group-hover:translate-x-1 group-hover:bg-[#1DA2B4]/25 dark:group-hover:bg-[#00D4FF]/20 group-hover:border-[#1DA2B4]/60 dark:group-hover:border-[#00E5FF]/50 group-hover:text-[#1DA2B4] dark:group-hover:text-[#00E5FF] group-hover:shadow-[0_0_12px_rgba(29,162,180,0.3)]">
						<ArrowRight className="h-4 w-4" />
					</div>
				</div>
			</div>
		</div>
	);
};
