// pwa/lib/nftAssets.ts
//
// Bundled asset imports for Genesis NFT Passes for PWA.

import genesisPass0Img from "@/content/nft/genesis_pass_0.jpg";
import genesisPass1Img from "@/content/nft/genesis_pass_1.jpg";
import genesisPass2Img from "@/content/nft/genesis_pass_2.jpg";

export { genesisPass0Img, genesisPass1Img, genesisPass2Img };

export type NftColorTheme = "gold" | "purple" | "cyan" | "emerald" | "rose";

export interface ColorThemeDef {
	id: NftColorTheme;
	label: string;
	color: string;
	borderClass: string;
	bgGradientClass: string;
	glowClass: string;
	badgeClass: string;
	accentTextClass: string;
}

export const COLOR_THEMES: Record<NftColorTheme, ColorThemeDef> = {
	gold: {
		id: "gold",
		label: "Gold / Amber",
		color: "#F59E0B",
		borderClass: "border-amber-500/50 hover:border-amber-400/80",
		bgGradientClass: "bg-gradient-to-r from-amber-500/15 via-card/50 to-yellow-500/10",
		glowClass: "shadow-[0_0_20px_rgba(245,158,11,0.18)]",
		badgeClass: "border-amber-500/40 bg-amber-500/15 text-amber-300",
		accentTextClass: "text-amber-400",
	},
	purple: {
		id: "purple",
		label: "Neon Violet",
		color: "#A855F7",
		borderClass: "border-purple-500/50 hover:border-purple-400/80",
		bgGradientClass: "bg-gradient-to-r from-purple-500/15 via-card/50 to-violet-500/10",
		glowClass: "shadow-[0_0_20px_rgba(168,85,247,0.18)]",
		badgeClass: "border-purple-500/40 bg-purple-500/15 text-purple-300",
		accentTextClass: "text-purple-400",
	},
	cyan: {
		id: "cyan",
		label: "Azure Cyan",
		color: "#06B6D4",
		borderClass: "border-cyan-500/50 hover:border-cyan-400/80",
		bgGradientClass: "bg-gradient-to-r from-cyan-500/15 via-card/50 to-blue-500/10",
		glowClass: "shadow-[0_0_20px_rgba(6,182,212,0.18)]",
		badgeClass: "border-cyan-500/40 bg-cyan-500/15 text-cyan-300",
		accentTextClass: "text-cyan-400",
	},
	emerald: {
		id: "emerald",
		label: "Matrix Green",
		color: "#10B981",
		borderClass: "border-emerald-500/50 hover:border-emerald-400/80",
		bgGradientClass: "bg-gradient-to-r from-emerald-500/15 via-card/50 to-teal-500/10",
		glowClass: "shadow-[0_0_20px_rgba(16,185,129,0.18)]",
		badgeClass: "border-emerald-500/40 bg-emerald-500/15 text-emerald-300",
		accentTextClass: "text-emerald-400",
	},
	rose: {
		id: "rose",
		label: "Crimson Rose",
		color: "#F43F5E",
		borderClass: "border-rose-500/50 hover:border-rose-400/80",
		bgGradientClass: "bg-gradient-to-r from-rose-500/15 via-card/50 to-pink-500/10",
		glowClass: "shadow-[0_0_20px_rgba(244,63,94,0.18)]",
		badgeClass: "border-rose-500/40 bg-rose-500/15 text-rose-300",
		accentTextClass: "text-rose-400",
	},
};

export const getNftPassImageUrl = (tokenId?: number | null, customUrl?: string | null): string => {
	if (customUrl && customUrl.trim() && !customUrl.startsWith("/nft/genesis_pass_")) {
		return customUrl;
	}
	if (tokenId === 0) return genesisPass0Img;
	if (tokenId === 2) return genesisPass2Img;
	return genesisPass1Img;
};

export const getQuestColorTheme = (themeName?: string | null, defaultTheme: NftColorTheme = "purple"): ColorThemeDef => {
	if (themeName && (themeName in COLOR_THEMES)) {
		return COLOR_THEMES[themeName as NftColorTheme];
	}
	return COLOR_THEMES[defaultTheme];
};

