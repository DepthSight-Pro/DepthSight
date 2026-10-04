// frontend/src/components/mining/PromoBanner.tsx
import React from "react";
import { useTranslation } from "react-i18next";
import { ArrowRight, Lock } from "lucide-react";
import type { PromoStatusResponse } from "@/types/api";

interface PromoBannerProps {
	promoStatus: PromoStatusResponse;
	onOpenQuests: () => void;
}

export const BitgetLogoSvg: React.FC<{ className?: string }> = ({ className = "w-full h-full" }) => (
	<svg viewBox="0 0 200 200" fill="none" xmlns="http://www.w3.org/2000/svg" className={className}>
		<g clipPath="url(#clip0_bitget_logo_banner)">
			<circle cx="100" cy="100" r="100" fill="#00F0FF" />
			<path
				d="M93.1911 80.4883H128.212L164.039 116.086C166.37 118.402 166.382 122.168 164.063 124.496L118.117 170.674H82.0405L92.9473 160.07L132.992 120.278L93.4556 80.4854"
				fill="black"
			/>
			<path
				d="M107.585 120.188H72.5635L36.7367 84.5904C34.4061 82.2747 34.3942 78.5083 36.7129 76.1807L82.6588 30H118.735L107.829 40.6036L67.7835 80.396L107.32 120.188"
				fill="black"
			/>
		</g>
		<defs>
			<clipPath id="clip0_bitget_logo_banner">
				<rect width="200" height="200" fill="white" />
			</clipPath>
		</defs>
	</svg>
);


export const PromoBanner: React.FC<PromoBannerProps> = ({ promoStatus, onOpenQuests }) => {
	const { t } = useTranslation(["mining", "common"]);

	if (!promoStatus?.hasActiveCampaign) {
		return null;
	}

	const totalSlots = promoStatus.quests?.reduce((acc, q) => acc + (q.totalSlots || 0), 0) || 0;
	const claimedSlots = promoStatus.quests?.reduce((acc, q) => acc + (q.claimedSlots || 0), 0) || 0;
	const slotsLeft = Math.max(0, totalSlots - claimedSlots);

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
					<div className="relative flex h-12 w-12 shrink-0 items-center justify-center rounded-xl border-2 border-[#1DA2B4]/40 dark:border-[#00E5FF]/50 bg-gradient-to-br from-[#1DA2B4]/25 to-[#0E7490]/15 dark:from-[#1DA2B4]/30 dark:to-[#00D4FF]/10 p-1.5 shadow-[0_0_12px_rgba(0,240,255,0.25)] dark:shadow-[0_0_24px_rgba(0,229,255,0.35)] transition-transform duration-300 group-hover:scale-110">
						<BitgetLogoSvg className="h-full w-full drop-shadow-[0_2px_8px_rgba(0,240,255,0.4)]" />
					</div>

					<div className="min-w-0">
						<div className="flex flex-wrap items-center gap-2">
							<h3 className="text-base font-bold text-foreground dark:text-white tracking-tight">
								{promoStatus.campaignName || t("promoBannerTitle", "Bitget Launch Airdrop — 10,000,000 $DEPTH")}
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
								t("promoBannerSubtitle", "Connect Bitget API keys & trade to earn up to 25,000 $DEPTH per quest.")}
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
