// src/components/research/UserProgressCard.tsx

import type { TFunction } from "i18next";
import {
	BarChart,
	Crown,
	Gem,
	GraduationCap,
	Search,
	Shield,
	Star,
	Trophy,
	Wrench,
	Zap,
} from "lucide-react";
import type React from "react";
import { useTranslation } from "react-i18next";
import { cn } from "@/lib/utils";

interface UserProgressCardProps {
	level: number;
	xp: number;
	totalGenes?: number;
}

// Calculate XP needed for next level (exponential curve)
const getXpForLevel = (level: number): number => {
	if (level <= 1) {
		return 0;
	}
	let totalXp = 0;
	for (let i = 1; i < level; i++) {
		totalXp += Math.floor(100 * 1.5 ** (i - 1));
	}
	return totalXp;
};

// Get rank based on level (New 10-tier system)
const getRank = (
	level: number,
	t: TFunction<"account">,
): { name: string; color: string; icon: React.ReactNode } => {
	switch (true) {
		case level >= 10:
			return {
				name: t("rank.grandmaster"),
				color: "text-red-500",
				icon: <Crown className="w-5 h-5" />,
			};
		case level === 9:
			return {
				name: t("rank.legend"),
				color: "text-yellow-500",
				icon: <Gem className="w-5 h-5" />,
			};
		case level === 8:
			return {
				name: t("rank.master"),
				color: "text-purple-500",
				icon: <Trophy className="w-5 h-5" />,
			};
		case level === 7:
			return {
				name: t("rank.veteran"),
				color: "text-indigo-500",
				icon: <Shield className="w-5 h-5" />,
			};
		case level === 6:
			return {
				name: t("rank.expert"),
				color: "text-blue-500",
				icon: <Star className="w-5 h-5" />,
			};
		case level === 5:
			return {
				name: t("rank.specialist"),
				color: "text-cyan-500",
				icon: <Wrench className="w-5 h-5" />,
			};
		case level === 4:
			return {
				name: t("rank.analyst"),
				color: "text-teal-500",
				icon: <BarChart className="w-5 h-5" />,
			};
		case level === 3:
			return {
				name: t("rank.researcher"),
				color: "text-emerald-500",
				icon: <Search className="w-5 h-5" />,
			};
		case level === 2:
			return {
				name: t("rank.apprentice"),
				color: "text-green-500",
				icon: <GraduationCap className="w-5 h-5" />,
			};
		default:
			return {
				name: t("rank.novice"),
				color: "text-gray-500",
				icon: <Zap className="w-5 h-5" />,
			};
	}
};

export const UserProgressCard: React.FC<UserProgressCardProps> = ({
	level,
	xp,
	totalGenes = 0,
}) => {
	const { t } = useTranslation(["account"]);
	const currentLevelXp = getXpForLevel(level);
	const nextLevelXp = getXpForLevel(level + 1);
	const xpInCurrentLevel = xp - currentLevelXp;
	const xpNeededForNextLevel = nextLevelXp - currentLevelXp;
	const progressPercent = Math.min(
		(xpInCurrentLevel / xpNeededForNextLevel) * 100,
		100,
	);

	const rank = getRank(level, t);

	return (
		<div className="glass relative overflow-hidden rounded-2xl border border-white/10 p-5 shadow-2xl backdrop-blur-xl">
			{/* Ambient background glow matching rank color */}
			<div className="pointer-events-none absolute -right-12 -top-12 h-44 w-44 rounded-full bg-cyan/10 blur-3xl" />
			<div className="pointer-events-none absolute -left-12 -bottom-12 h-44 w-44 rounded-full bg-azure/10 blur-3xl" />

			<div className="relative z-10 space-y-4">
				{/* Top Row: Rank & Level */}
				<div className="flex items-center justify-between">
					<div className="flex items-center gap-3">
						<div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl border border-white/15 bg-white/[0.04] shadow-inner">
							<span className={rank.color}>{rank.icon}</span>
						</div>
						<div>
							<div className="text-[10px] uppercase tracking-wider font-mono text-white/40">
								{t("rankTitle", "Player Rank")}
							</div>
							<div className={cn("text-base font-bold tracking-tight", rank.color)}>
								{rank.name}
							</div>
						</div>
					</div>

					<div className="flex items-center gap-2">
						<div className="rounded-xl border border-cyan/40 bg-cyan/10 px-3.5 py-1 text-right shadow-[0_0_15px_-3px_rgba(0,212,255,0.4)]">
							<div className="text-[9px] uppercase tracking-wider font-mono text-cyan/70">
								{t("level", "Level")}
							</div>
							<div className="font-mono text-lg font-black text-cyan">
								{level}
							</div>
						</div>
					</div>
				</div>

				{/* XP Progress Bar */}
				<div className="space-y-1.5 pt-1">
					<div className="flex justify-between items-baseline text-xs">
						<span className="text-[11px] font-medium text-white/50">
							{t("experience", "Experience")}
						</span>
						<span className="font-mono text-[11px] font-semibold text-white/90">
							{xpInCurrentLevel.toLocaleString()} <span className="text-white/40">/</span> {xpNeededForNextLevel.toLocaleString()}{" "}
							<span className="text-cyan font-bold">{t("xp", "XP")}</span>
						</span>
					</div>

					{/* Custom glowing progress bar */}
					<div className="relative h-2.5 w-full overflow-hidden rounded-full bg-white/[0.06] p-0.5">
						<div
							className="h-full rounded-full bg-gradient-to-r from-azure via-cyan to-emerald-400 shadow-[0_0_12px_rgba(0,212,255,0.7)] transition-all duration-500"
							style={{ width: `${progressPercent}%` }}
						/>
					</div>

					<div className="flex justify-between text-[10px] text-white/40 font-mono">
						<span>{progressPercent.toFixed(1)}%</span>
						<span>
							{Math.max(0, xpNeededForNextLevel - xpInCurrentLevel).toLocaleString()}{" "}
							{t("xpToLevel", "XP to Level")} {level + 1}
						</span>
					</div>
				</div>

				{/* Stats Grid */}
				<div className="grid grid-cols-3 gap-3 border-t border-white/5 pt-3.5">
					<div className="rounded-xl border border-white/5 bg-white/[0.02] p-2.5 text-center">
						<div className="font-mono text-lg font-bold text-white">
							{xp.toLocaleString()}
						</div>
						<div className="text-[10.5px] uppercase tracking-wider text-white/40">
							{t("totalXP", "Total XP")}
						</div>
					</div>
					<div className="rounded-xl border border-white/5 bg-white/[0.02] p-2.5 text-center">
						<div className="font-mono text-lg font-bold text-emerald-400">
							{totalGenes}
						</div>
						<div className="text-[10.5px] uppercase tracking-wider text-white/40">
							{t("genesFound", "Genes Found")}
						</div>
					</div>
					<div className="rounded-xl border border-white/5 bg-white/[0.02] p-2.5 text-center">
						<div className="font-mono text-lg font-bold text-amber-400">
							{level}
						</div>
						<div className="text-[10.5px] uppercase tracking-wider text-white/40">
							{t("level", "Level")}
						</div>
					</div>
				</div>
			</div>
		</div>
	);
};
