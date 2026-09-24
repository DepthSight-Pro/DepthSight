// pwa/components/mining/PromoBannerPwa.tsx
import React from "react";
import { useTranslation } from "react-i18next";
import { ArrowRight, Lock } from "lucide-react";
import { BitgetLogoSvg } from "./BitgetLogoSvg";

interface PromoQuestSlots {
	totalSlots?: number;
	claimedSlots?: number;
	[key: string]: unknown;
}

interface PromoBannerStatus {
	hasActiveCampaign?: boolean;
	quests?: PromoQuestSlots[];
	distributed?: number;
	campaignName?: string;
	description?: string;
	isAdminPreview?: boolean;
	[key: string]: unknown;
}

interface PromoBannerPwaProps {
	promoStatus: PromoBannerStatus | null;
	onOpenQuests: () => void;
}

export const PromoBannerPwa: React.FC<PromoBannerPwaProps> = ({
	promoStatus,
	onOpenQuests,
}) => {
	const { t } = useTranslation("pwa-common");

	if (!promoStatus?.hasActiveCampaign) {
		return null;
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

	const distributedM = ((promoStatus.distributed || 0) / 1_000_000).toFixed(1);

	return (
		<div
			onClick={onOpenQuests}
			role="button"
			tabIndex={0}
			className="group relative cursor-pointer overflow-hidden rounded-2xl border border-[#1DA2B4]/40 bg-gradient-to-r from-[#1DA2B4]/15 via-[#0F1923]/95 to-blue-500/10 p-4 transition-all duration-300 active:scale-[0.98] hover:border-[#00F0FF]/70 hover:shadow-[0_8px_30px_rgba(29,162,180,0.25)]"
		>
			{/* Ambient background glow */}
			<div className="pointer-events-none absolute -right-10 -top-10 h-48 w-48 rounded-full bg-[radial-gradient(circle,rgba(0,240,255,0.18)_0%,rgba(29,162,180,0.05)_50%,transparent_70%)]" />

			{/* Top Header: Logo + Title + Status Badge */}
			<div className="flex items-start gap-3">
				<div className="relative flex h-11 w-11 shrink-0 items-center justify-center rounded-xl border border-[#00F0FF]/40 bg-[#1DA2B4]/20 p-1.5 shadow-[0_0_15px_rgba(29,162,180,0.35)]">
					<BitgetLogoSvg className="h-full w-full drop-shadow-[0_2px_8px_rgba(29,162,180,0.5)]" />
				</div>

				<div className="min-w-0 flex-1">
					<div className="flex flex-wrap items-center gap-1.5">
						<h3 className="text-sm font-bold text-white tracking-tight leading-snug">
							{promoStatus.campaignName ||
								t("mining.promoBannerTitle", "Bitget Launch Airdrop")}
						</h3>
						{promoStatus.isAdminPreview ? (
							<span className="inline-flex items-center gap-1 rounded-full border border-amber-500/40 bg-amber-500/15 px-2 py-0.5 text-[9px] font-black uppercase tracking-wider text-amber-400">
								<Lock className="h-2 w-2" />
								{t("mining.adminPreviewBadge", "ADMIN PREVIEW")}
							</span>
						) : (
							<span className="inline-flex items-center gap-1 rounded-full border border-[#00F0FF]/40 bg-[#1DA2B4]/15 px-2 py-0.5 text-[9px] font-extrabold uppercase tracking-widest text-[#00F0FF] shadow-[0_0_10px_rgba(0,240,255,0.3)] animate-pulse">
								<span className="h-1.5 w-1.5 rounded-full bg-[#00F0FF]" />
								{t("mining.liveBadge", "LIVE")}
							</span>
						)}
					</div>
					<p className="mt-1 text-[11px] text-muted-foreground leading-tight line-clamp-2">
						{promoStatus.description ||
							t(
								"mining.promoBannerSubtitle",
								"Connect Bitget API keys & trade to earn up to 25,000 $DEPTH per quest.",
							)}
					</p>
				</div>
			</div>

			{/* Bottom Metrics Bar */}
			<div className="mt-3.5 pt-3 border-t border-white/10 flex items-center justify-between gap-2">
				<div className="flex items-center gap-4">
					<div>
						<div className="text-sm font-black text-white font-mono">
							{slotsLeft.toLocaleString()}
						</div>
						<div className="text-[9px] uppercase tracking-wider text-muted-foreground">
							{t("mining.promoSlotsLeft", "Slots left")}
						</div>
					</div>

					<div className="border-l border-white/10 pl-4">
						<div className="text-sm font-black text-[#00F0FF] font-mono">
							{distributedM}M
						</div>
						<div className="text-[9px] uppercase tracking-wider text-muted-foreground">
							{t("mining.promoClaimed", "$DEPTH claimed")}
						</div>
					</div>
				</div>

				<div className="flex items-center gap-1.5 text-xs font-bold text-[#00F0FF] bg-[#1DA2B4]/20 border border-[#00F0FF]/30 rounded-xl px-2.5 py-1.5 transition-all group-hover:bg-[#00F0FF] group-hover:text-black">
					<span>{t("mining.subtabQuests", "Quests")}</span>
					<ArrowRight className="h-3.5 w-3.5" />
				</div>
			</div>
		</div>
	);
};
