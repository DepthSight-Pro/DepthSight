// pwa/components/Achievements.tsx

import type React from "react";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { ICONS } from "../constants";
import { api } from "../services/api";
import type {
	Achievement,
	User,
	UserAchievement,
	UserGenesResponse,
} from "../types";
import { Card, CardContent, CardHeader, CardTitle } from "./Card";
import Progress from "./Progress";
import { Logo } from "./ui/logo";

// Use only available icons from constants.tsx
const iconMap: { [key: string]: React.ElementType } = {
	// Onboarding
	first_backtest: ICONS.History,
	first_save: ICONS.Star,
	used_ai_assistant: ICONS.Star,
	first_optimization: ICONS.Settings,
	first_api_key: ICONS.Key,
	first_paper_trade: ICONS.Star,
	reset_paper: ICONS.History,
	// Grinding
	"10_backtests": ICONS.Research,
	"100_backtests": ICONS.Research,
	"500_backtests": ICONS.Research,
	"1000_trades_backtests": ICONS.TrendingDown,
	"10000_trades_backtests": ICONS.TrendingDown,
	"50_optimizations": ICONS.Settings,
	save_10_strategies: ICONS.Strategies,
	// Performance
	sniper: ICONS.Star,
	marathon_runner: ICONS.Star,
	hard_nut: ICONS.Star,
	alpha_hunter: ICONS.Star,
	money_printer: ICONS.Dollar,
	winning_streak: ICONS.Star,
	phoenix: ICONS.Star,
	flawless_victory: ICONS.Star,
	// Exploration
	clairvoyant: ICONS.Star,
	diversifier: ICONS.Star,
	show_off: ICONS.Star,
	contender: ICONS.Star,
	the_intervention: ICONS.Star,
	pulling_the_plug: ICONS.Stop,
	the_professor: ICONS.Star,
	// Complexity
	strategy_5_blocks: ICONS.Strategies,
	the_architect: ICONS.Strategies,
	logician: ICONS.Star,
	inventor: ICONS.Star,
	order_flow_purist: ICONS.Star,
	prudent_manager: ICONS.Settings,
	// Genome
	"10_strategies_discovery": ICONS.Research,
	the_spark: ICONS.Star,
	gem_hunter: ICONS.Star,
	treasure_hunter: ICONS.Star,
	myth_buster: ICONS.Research,
	gene_collector: ICONS.Star,
	geneticist: ICONS.Star,
	natural_selection: ICONS.Star,
	// Community
	recruiter: ICONS.Profile,
	first_commission: ICONS.Dollar,
	partner: ICONS.Star,
	// Easter Eggs
	underminer: ICONS.Star,
	the_pacifist: ICONS.Star,
	perfectly_balanced: ICONS.Percent,
	diamond_hands: ICONS.Star,
};

const getRarityColor = (rarity: string) => {
	switch (rarity?.toLowerCase()) {
		case "legendary":
			return "from-yellow-500 to-orange-500";
		case "epic":
			return "from-purple-500 to-pink-500";
		case "rare":
			return "from-blue-500 to-cyan-500";
		default:
			return "from-gray-500 to-gray-600";
	}
};

const getRarityBadgeClass = (rarity: string) => {
	switch (rarity?.toLowerCase()) {
		case "legendary":
			return "bg-yellow-500/10 text-yellow-500 border-yellow-500/30";
		case "epic":
			return "bg-purple-500/10 text-purple-500 border-purple-500/30";
		case "rare":
			return "bg-blue-500/10 text-blue-500 border-blue-500/30";
		default:
			return "bg-gray-500/10 text-gray-500 border-gray-500/30";
	}
};

const getXpForLevel = (level: number): number => {
	if (level <= 1) {
		return 0;
	}
	let total = 0;
	for (let i = 1; i < level; i++) {
		total += Math.floor(100 * 1.5 ** (i - 1));
	}
	return total;
};

interface RankInfo {
	name: string;
	color: string;
	Icon: React.ElementType;
}

const getRank = (level: number, t: (key: string) => string): RankInfo => {
	if (level >= 10)
		return {
			name: t("achievements.grandmaster"),
			color: "text-red-500",
			Icon: ICONS.Star,
		};
	if (level >= 8)
		return {
			name: t("achievements.legend"),
			color: "text-yellow-500",
			Icon: ICONS.Dollar,
		};
	if (level >= 6)
		return {
			name: t("achievements.master"),
			color: "text-purple-500",
			Icon: ICONS.Strategies,
		};
	if (level >= 4)
		return {
			name: t("achievements.analyst"),
			color: "text-blue-500",
			Icon: ICONS.Research,
		};
	if (level >= 2)
		return {
			name: t("achievements.apprentice"),
			color: "text-emerald-500",
			Icon: ICONS.History,
		};
	return {
		name: t("achievements.novice"),
		color: "text-gray-500",
		Icon: ICONS.Star,
	};
};

interface UserProgressCardProps {
	level: number;
	xp: number;
	totalGenes: number;
}

const UserProgressCard: React.FC<UserProgressCardProps> = ({
	level,
	xp,
	totalGenes,
}) => {
	const { t } = useTranslation("pwa-common");
	const currentLevelXp = getXpForLevel(level);
	const nextLevelXp = getXpForLevel(level + 1);
	const xpInCurrentLevel = Math.max(0, xp - currentLevelXp);
	const xpNeededForNextLevel = Math.max(1, nextLevelXp - currentLevelXp);
	const progressPercent = Math.min(
		100,
		(xpInCurrentLevel / xpNeededForNextLevel) * 100,
	);
	const xpToNext = Math.max(0, xpNeededForNextLevel - xpInCurrentLevel);
	const rank = getRank(level, t);

	return (
		<Card className="border-2 border-[hsl(var(--border))] bg-gradient-to-br from-[hsl(var(--card))] to-[hsl(var(--card))/0.6]">
			<CardHeader className="mb-0 border-none pb-0">
				<CardTitle className="flex items-center justify-between text-base">
					<span className="flex items-center gap-2">
						<rank.Icon className={`h-5 w-5 ${rank.color}`} />
						<span className={`${rank.color}`}>{rank.name}</span>
					</span>
					<span className="rounded-full border border-[hsl(var(--border))] px-3 py-1 text-sm font-semibold text-[hsl(var(--card-foreground))]">
						{t("achievements.level", { level })}
					</span>
				</CardTitle>
			</CardHeader>
			<CardContent className="mt-4 space-y-4">
				<div className="space-y-2">
					<div className="flex justify-between text-xs text-[hsl(var(--muted-foreground))]">
						<span>{t("achievements.experience")}</span>
						<span className="font-mono text-[hsl(var(--card-foreground))]">
							{xpInCurrentLevel} / {xpNeededForNextLevel} XP
						</span>
					</div>
					<Progress value={progressPercent} />
					<div className="text-right text-xs text-[hsl(var(--muted-foreground))]">
						{t("achievements.xpToNextLevel", { xpToNext, level: level + 1 })}
					</div>
				</div>

				<div className="grid grid-cols-3 gap-4 border-t border-[hsl(var(--border))] pt-3">
					<div className="text-center">
						<div className="text-2xl font-bold text-[hsl(var(--primary))]">
							{xp.toLocaleString()}
						</div>
						<div className="text-xs text-[hsl(var(--muted-foreground))]">
							{t("achievements.totalXp")}
						</div>
					</div>
					<div className="text-center">
						<div className="text-2xl font-bold text-green-500">
							{totalGenes}
						</div>
						<div className="text-xs text-[hsl(var(--muted-foreground))]">
							{t("achievements.genesFound")}
						</div>
					</div>
					<div className="text-center">
						<div className="text-2xl font-bold text-yellow-500">{level}</div>
						<div className="text-xs text-[hsl(var(--muted-foreground))]">
							{t("achievements.currentLevel")}
						</div>
					</div>
				</div>
			</CardContent>
		</Card>
	);
};

const Achievements = () => {
	const { t } = useTranslation("pwa-common");
	const [allAchievements, setAllAchievements] = useState<Achievement[]>([]);
	const [userAchievements, setUserAchievements] = useState<UserAchievement[]>(
		[],
	);
	const [user, setUser] = useState<User | null>(null);
	const [genesData, setGenesData] = useState<UserGenesResponse | null>(null);
	const [loading, setLoading] = useState(true);
	const [error, setError] = useState<string | null>(null);

	useEffect(() => {
		const fetchData = async () => {
			try {
				setLoading(true);
				const currentUser = await api.getMe();
				setUser(currentUser);

				const [achievements, userAchs, genesResponse] = await Promise.all([
					api.getAchievements(),
					api.getUserAchievements(currentUser.id),
					api.getMyGenes(),
				]);

				setAllAchievements(achievements);
				setUserAchievements(userAchs);
				setGenesData(genesResponse);
			} catch (err) {
				setError(err instanceof Error ? err.message : String(err));
			} finally {
				setLoading(false);
			}
		};

		fetchData();
	}, []);

	if (loading) {
		return (
			<div className="flex justify-center items-center min-h-[400px]">
				<Logo size="lg" className="mb-8 animate-pulse" />
			</div>
		);
	}

	if (error) {
		return (
			<div className="p-4 text-center text-[hsl(var(--loss))]">
				{t("common.error", { message: error })}
			</div>
		);
	}

	const unlockedAchievementIds = new Set(
		userAchievements?.map((ua) => ua.achievement_id),
	);
	const unlockedCount = userAchievements?.length || 0;
	const totalCount = allAchievements?.length || 0;
	const level = user?.level || 1;
	const xp = user?.xp || 0;
	const totalGenes = genesData?.total || 0;
	const unlockedPercent =
		totalCount > 0 ? Math.round((unlockedCount / totalCount) * 100) : 0;

	// Show only unlocked achievements
	const unlockedAchievements =
		allAchievements?.filter((achievement) =>
			unlockedAchievementIds.has(achievement.id),
		) || [];

	return (
		<div className="space-y-6">
			<UserProgressCard level={level} xp={xp} totalGenes={totalGenes} />

			{/* Achievement Stats */}
			<div className="grid grid-cols-2 md:grid-cols-3 gap-4">
				<Card>
					<CardContent className="pt-6 text-center">
						<div className="text-3xl font-bold text-[hsl(var(--profit))]">
							{unlockedCount}
						</div>
						<div className="text-sm text-[hsl(var(--muted-foreground))]">
							{t("achievements.achievementsUnlocked")}
						</div>
					</CardContent>
				</Card>
				<Card>
					<CardContent className="pt-6 text-center">
						<div className="text-3xl font-bold text-[hsl(var(--primary))]">
							{totalCount}
						</div>
						<div className="text-sm text-[hsl(var(--muted-foreground))]">
							{t("achievements.totalAvailable")}
						</div>
					</CardContent>
				</Card>
				<Card>
					<CardContent className="pt-6 text-center">
						<div className="text-3xl font-bold text-blue-500">
							{unlockedPercent}%
						</div>
						<div className="text-sm text-[hsl(var(--muted-foreground))]">
							{t("achievements.collectionProgress")}
						</div>
					</CardContent>
				</Card>
			</div>

			{/* Achievements Grid - only unlocked */}
			<div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-4">
				{unlockedAchievements.length > 0 ? (
					unlockedAchievements.map((achievement) => {
						const Icon = iconMap[achievement.id] || ICONS.Star;
						const rarityGradient = getRarityColor(achievement.rarity);
						const userAchievement = userAchievements?.find(
							(ua) => ua.achievement_id === achievement.id,
						);

						return (
							<Card
								key={achievement.id}
								className="relative overflow-hidden transition-all cursor-pointer hover:scale-105 border-2 shadow-lg"
							>
								{/* Rarity gradient top border */}
								<div
									className={`absolute top-0 left-0 right-0 h-1 bg-gradient-to-r ${rarityGradient}`}
								/>

								<CardContent className="p-6 flex flex-col items-center justify-center space-y-3">
									{/* Icon */}
									<div
										className={`relative p-4 rounded-full bg-gradient-to-br ${rarityGradient}`}
									>
										<Icon className="w-8 h-8 text-white" />

										{/* Star effect */}
										<ICONS.Star className="absolute -top-1 -right-1 w-4 h-4 text-yellow-400 animate-pulse" />
									</div>

									{/* Title */}
									<div className="text-xs font-semibold text-center text-[hsl(var(--card-foreground))]">
										{t(
											`achievements.list.${achievement.id}.name`,
											achievement.name,
										)}
									</div>

									{/* XP Badge */}
									<div
										className={`text-xs px-2 py-1 rounded ${getRarityBadgeClass(achievement.rarity)}`}
									>
										{t("achievements.xpReward", { xp: achievement.xp_reward })}
									</div>

									{/* Date unlocked */}
									{userAchievement && (
										<div className="text-xs text-[hsl(var(--muted-foreground))] text-center">
											{new Date(
												userAchievement.unlocked_at,
											).toLocaleDateString()}
										</div>
									)}

									{/* Description tooltip on hover */}
									<div className="absolute inset-0 bg-[hsl(var(--card))] p-3 opacity-0 hover:opacity-100 transition-opacity flex flex-col items-center justify-center text-center text-xs">
										<div className="font-bold mb-2">
											{t(
												`achievements.list.${achievement.id}.name`,
												achievement.name,
											)}
										</div>
										<div className="text-[hsl(var(--muted-foreground))]">
											{t(
												`achievements.list.${achievement.id}.description`,
												achievement.description,
											)}
										</div>
										<div
											className={`mt-2 px-2 py-1 rounded text-xs ${getRarityBadgeClass(achievement.rarity)}`}
										>
											{t("achievements.rarityDisplay", {
												rarity: achievement.rarity,
											})}
										</div>
									</div>
								</CardContent>
							</Card>
						);
					})
				) : (
					<div className="col-span-full text-center text-[hsl(var(--muted-foreground))] py-8">
						{t("achievements.noAchievements")}
					</div>
				)}
			</div>
		</div>
	);
};

export default Achievements;
