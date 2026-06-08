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
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";

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
		<Card className="border-2 bg-gradient-to-br from-background to-muted/20">
			<CardHeader className="pb-3">
				<CardTitle className="flex items-center justify-between">
					<div className="flex items-center gap-2">
						{rank.icon}
						<span className={rank.color}>{rank.name}</span>
					</div>
					<Badge variant="outline" className="text-lg font-bold">
						{t("level")} {level}
					</Badge>
				</CardTitle>
			</CardHeader>
			<CardContent className="space-y-4">
				{/* XP Progress Bar */}
				<div className="space-y-2">
					<div className="flex justify-between text-sm">
						<span className="text-muted-foreground">{t("experience")}</span>
						<span className="font-mono font-medium">
							{xpInCurrentLevel} / {xpNeededForNextLevel} {t("xp")}
						</span>
					</div>
					<Progress value={progressPercent} className="h-3" />
					<p className="text-xs text-muted-foreground text-right">
						{Math.max(0, xpNeededForNextLevel - xpInCurrentLevel)}{" "}
						{t("xpToLevel")} {level + 1}
					</p>
				</div>

				{/* Stats Grid */}
				<div className="grid grid-cols-3 gap-4 pt-2 border-t">
					<div className="text-center">
						<div className="text-2xl font-bold text-primary">
							{xp.toLocaleString()}
						</div>
						<div className="text-xs text-muted-foreground">{t("totalXP")}</div>
					</div>
					<div className="text-center">
						<div className="text-2xl font-bold text-green-500">
							{totalGenes}
						</div>
						<div className="text-xs text-muted-foreground">
							{t("genesFound")}
						</div>
					</div>
					<div className="text-center">
						<div className="text-2xl font-bold text-yellow-500">{level}</div>
						<div className="text-xs text-muted-foreground">{t("level")}</div>
					</div>
				</div>
			</CardContent>
		</Card>
	);
};
