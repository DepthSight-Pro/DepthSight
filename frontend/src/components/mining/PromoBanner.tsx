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
	<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 2500 2500" className={className}>
		<circle fill="#1DA2B4" cx="1250" cy="1250" r="1250" />
		<g fill="#FFFFFF" fillRule="evenodd" clipRule="evenodd">
			<path d="M925,415c22-24,54-37,86-37h212c27,0,41,32,22,51L826,876h231l235,249H826l466,499h-282c-33,0-64-14-86-37 l-473-506c-42-45-42-115,0-160l473-506H925z" />
			<path d="M1575,2085c-22,24-54,37-86,37h-212c-27,0-41-32-22-51l419-447h-231l-235-249h466l-466-499h282 c33,0,64,14,86,37l473,506c42,45,42,115,0,160l-473,506H1575z" />
		</g>
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

	const distributedM = ((promoStatus.distributed || 0) / 1_000_000).toFixed(1);

	return (
		<div
			onClick={onOpenQuests}
			className="group relative mb-6 cursor-pointer overflow-hidden rounded-2xl border border-[#1DA2B4]/40 bg-gradient-to-r from-[#1DA2B4]/15 via-[#0F1923]/95 to-blue-500/10 p-4 sm:p-5 transition-all duration-300 hover:-translate-y-0.5 hover:border-[#00F0FF]/70 hover:shadow-[0_10px_35px_rgba(0,0,0,0.5),0_0_35px_rgba(29,162,180,0.25)]"
		>
			{/* Ambient background glow */}
			<div className="pointer-events-none absolute -right-16 -top-16 h-72 w-72 rounded-full bg-[radial-gradient(circle,rgba(0,240,255,0.15)_0%,rgba(29,162,180,0.05)_40%,transparent_70%)]" />

			<div className="relative flex flex-col sm:flex-row sm:items-center justify-between gap-4">
				{/* Left: Icon & Titles */}
				<div className="flex items-center gap-4 min-w-0">
					<div className="relative flex h-12 w-12 shrink-0 items-center justify-center rounded-xl border border-[#00F0FF]/40 bg-[#1DA2B4]/20 p-1.5 shadow-[0_0_20px_rgba(29,162,180,0.3)] transition-transform duration-300 group-hover:scale-105">
						<BitgetLogoSvg className="h-full w-full drop-shadow-[0_2px_8px_rgba(29,162,180,0.5)]" />
					</div>

					<div className="min-w-0">
						<div className="flex flex-wrap items-center gap-2">
							<h3 className="text-base font-bold text-white tracking-tight">
								{promoStatus.campaignName || t("promoBannerTitle", "Bitget Launch Airdrop — 10,000,000 $DEPTH")}
							</h3>
							{promoStatus.isAdminPreview ? (
								<span className="flex items-center gap-1 rounded-full border border-amber-500/40 bg-amber-500/15 px-2.5 py-0.5 text-[10px] font-black uppercase tracking-wider text-amber-400">
									<Lock className="h-2.5 w-2.5" />
									{t("adminPreviewBadge", "ADMIN PREVIEW")}
								</span>
							) : (
								<span className="flex items-center gap-1.5 rounded-full border border-[#00F0FF]/40 bg-[#1DA2B4]/15 px-2.5 py-0.5 text-[10px] font-extrabold uppercase tracking-widest text-[#00F0FF] shadow-[0_0_12px_rgba(0,240,255,0.25)] animate-pulse">
									<span className="h-1.5 w-1.5 rounded-full bg-[#00F0FF]" />
									{t("liveBadge", "LIVE")}
								</span>
							)}
						</div>
						<p className="mt-0.5 truncate text-xs text-muted-foreground">
							{promoStatus.description ||
								t("promoBannerSubtitle", "Connect Bitget API keys & trade to earn up to 25,000 $DEPTH per quest.")}
						</p>
					</div>
				</div>

				{/* Right: Metrics & Arrow */}
				<div className="flex items-center justify-between sm:justify-end gap-6 sm:border-l sm:border-white/10 sm:pl-6 shrink-0">
					<div className="text-left sm:text-center">
						<div className="text-base sm:text-lg font-black text-white font-mono">{slotsLeft.toLocaleString()}</div>
						<div className="text-[10px] uppercase tracking-wider text-muted-foreground">
							{t("promoSlotsLeft", "Slots left")}
						</div>
					</div>

					<div className="text-left sm:text-center">
						<div className="text-base sm:text-lg font-black text-[#00F0FF] font-mono">{distributedM}M</div>
						<div className="text-[10px] uppercase tracking-wider text-muted-foreground">
							{t("promoClaimed", "$DEPTH claimed")}
						</div>
					</div>

					<div className="flex h-8 w-8 items-center justify-center rounded-lg bg-white/5 text-muted-foreground transition-all duration-300 group-hover:translate-x-1 group-hover:bg-[#1DA2B4]/20 group-hover:text-[#00F0FF]">
						<ArrowRight className="h-4 w-4" />
					</div>
				</div>
			</div>
		</div>
	);
};
