// frontend/src/components/achievements/SteamAchievementNotification.tsx

import { AnimatePresence, motion } from "framer-motion";
import {
	Activity,
	Award,
	Box,
	Building2,
	CheckCircle2,
	CircleDollarSign,
	CloudLightning,
	Coins,
	Crown,
	Diamond,
	Fish,
	Flame,
	Gauge,
	Globe,
	GraduationCap,
	HandHeart,
	Hourglass,
	Medal,
	Network,
	Pickaxe,
	Radio,
	Rocket,
	Server,
	Share2,
	Shield,
	Sparkles,
	Trophy,
	UserPlus,
	Users,
	Wallet,
	X,
	Zap,
} from "lucide-react";
import type React from "react";
import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { useAuth } from "@/context/AuthContext";
import { useWebSocket } from "@/context/WebSocketProvider";

// Icon mapping matching Achievements.tsx
const iconMap: Record<string, React.ElementType> = {
	mining_activated: Pickaxe,
	mining_wallet_linked: Wallet,
	mining_first_trade: Sparkles,
	welcome_bonus_claimed: Award,
	mining_volume_1k: CircleDollarSign,
	mining_volume_10k: Coins,
	mining_volume_100k: Trophy,
	mining_volume_1m: Fish,
	mining_volume_10m: Crown,
	mining_daily_volume_10k: Activity,
	mining_daily_volume_100k: CloudLightning,
	mining_daily_top_miner: Trophy,
	mining_daily_top5_miner: Medal,
	mining_first_referral: UserPlus,
	mining_5_referrals: Users,
	mining_10_referrals: Network,
	mining_50_referrals: Building2,
	mining_active_squad: Radio,
	mining_mentor_bonus: GraduationCap,
	mining_ref_volume_100k: Share2,
	mining_ref_earnings_100k: Diamond,
	mining_streak_7d: Flame,
	mining_streak_30d: Shield,
	mining_epochs_100: Award,
	mining_halving_survivor: Hourglass,
	mining_depth_1k: Coins,
	mining_depth_10k: Box,
	mining_depth_100k: Crown,
	mining_jackpot_epoch: Zap,
	mining_flawless_telemetry: CheckCircle2,
	mining_high_speed_turnover: Gauge,
	mining_profitable: Trophy,
	mining_multi_exchange: Globe,
	mining_all_exchanges: Globe,
	mining_node_operator: Server,
	mining_boost_active: Rocket,
	mining_diamond_staker: HandHeart,
};

export interface UnlockedAchievementData {
	id: string;
	name: string;
	description: string;
	icon?: string;
	xp_reward: number;
	rarity: "COMMON" | "RARE" | "EPIC" | "LEGENDARY" | string;
}

// Web Audio API synthesized crystal trophy chime (no external audio assets needed!)
const playAchievementChime = () => {
	try {
		const AudioContextClass =
			window.AudioContext ||
			(window as unknown as { webkitAudioContext: typeof AudioContext })
				.webkitAudioContext;
		if (!AudioContextClass) return;

		const ctx = new AudioContextClass();
		const now = ctx.currentTime;

		// Harmonic 1 - Bright lead fanfare
		const osc1 = ctx.createOscillator();
		const gain1 = ctx.createGain();
		osc1.type = "sine";
		osc1.frequency.setValueAtTime(587.33, now); // D5
		osc1.frequency.exponentialRampToValueAtTime(1174.66, now + 0.12); // D6
		gain1.gain.setValueAtTime(0.18, now);
		gain1.gain.exponentialRampToValueAtTime(0.0001, now + 1.2);
		osc1.connect(gain1);
		gain1.connect(ctx.destination);
		osc1.start(now);
		osc1.stop(now + 1.2);

		// Harmonic 2 - Sparkling bell resonance
		const osc2 = ctx.createOscillator();
		const gain2 = ctx.createGain();
		osc2.type = "triangle";
		osc2.frequency.setValueAtTime(1479.98, now + 0.08); // F#6
		gain2.gain.setValueAtTime(0.12, now + 0.08);
		gain2.gain.exponentialRampToValueAtTime(0.0001, now + 1.5);
		osc2.connect(gain2);
		gain2.connect(ctx.destination);
		osc2.start(now + 0.08);
		osc2.stop(now + 1.5);
	} catch {
		// Audio context autoplay policy gracefully ignored
	}
};

const getRarityStyles = (rarity: string) => {
	switch (rarity?.toUpperCase()) {
		case "LEGENDARY":
			return {
				border: "border-amber-500/80 shadow-[0_0_30px_rgba(245,158,11,0.4)]",
				badge: "bg-amber-500/20 text-amber-400 border-amber-500/50",
				iconGlow: "text-amber-400 drop-shadow-[0_0_12px_rgba(245,158,11,0.8)]",
				bgGlow: "from-amber-950/40 via-zinc-950 to-zinc-950",
				bar: "from-amber-400 to-orange-500",
			};
		case "EPIC":
			return {
				border: "border-purple-500/80 shadow-[0_0_30px_rgba(168,85,247,0.4)]",
				badge: "bg-purple-500/20 text-purple-400 border-purple-500/50",
				iconGlow: "text-purple-400 drop-shadow-[0_0_12px_rgba(168,85,247,0.8)]",
				bgGlow: "from-purple-950/40 via-zinc-950 to-zinc-950",
				bar: "from-purple-400 to-pink-500",
			};
		case "RARE":
			return {
				border: "border-cyan-500/80 shadow-[0_0_25px_rgba(6,182,212,0.35)]",
				badge: "bg-cyan-500/20 text-cyan-400 border-cyan-500/50",
				iconGlow: "text-cyan-400 drop-shadow-[0_0_10px_rgba(6,182,212,0.8)]",
				bgGlow: "from-cyan-950/40 via-zinc-950 to-zinc-950",
				bar: "from-cyan-400 to-blue-500",
			};
		default:
			return {
				border: "border-zinc-600/70 shadow-[0_0_20px_rgba(161,161,170,0.2)]",
				badge: "bg-zinc-700/20 text-zinc-300 border-zinc-600/50",
				iconGlow: "text-zinc-300 drop-shadow-[0_0_8px_rgba(255,255,255,0.4)]",
				bgGlow: "from-zinc-900/60 via-zinc-950 to-zinc-950",
				bar: "from-zinc-400 to-zinc-600",
			};
	}
};

export const SteamAchievementNotification: React.FC = () => {
	const { t } = useTranslation(["account", "common"]);
	const { subscribe, unsubscribe } = useWebSocket();
	const { user } = useAuth();

	const [queue, setQueue] = useState<UnlockedAchievementData[]>([]);
	const [current, setCurrent] = useState<UnlockedAchievementData | null>(null);

	const enqueue = useCallback((item: UnlockedAchievementData) => {
		setQueue((prev) => [...prev, item]);
	}, []);

	// Handle next item in queue
	useEffect(() => {
		if (!current && queue.length > 0) {
			const nextItem = queue[0];
			setCurrent(nextItem);
			setQueue((prev) => prev.slice(1));
			playAchievementChime();

			// Auto-dismiss after 6.5s
			const timer = setTimeout(() => {
				setCurrent(null);
			}, 6500);

			return () => clearTimeout(timer);
		}
	}, [current, queue]);

	// WebSocket listener for achievement events
	useEffect(() => {
		const handlePayload = (payload: unknown) => {
			if (!payload) return;
			const p = payload as {
				type?: string;
				achievement?: UnlockedAchievementData;
				id?: string;
				name?: string;
				description?: string;
				xp_reward?: number;
				rarity?: string;
			};

			// Handle either payload.achievement or direct achievement object
			const ach = p.achievement || (p.id ? (p as UnlockedAchievementData) : null);
			if (ach && ach.name) {
				enqueue({
					id: ach.id,
					name: ach.name,
					description: ach.description || "",
					icon: ach.icon,
					xp_reward: ach.xp_reward || 50,
					rarity: ach.rarity || "COMMON",
				});
			}
		};

		// Subscribe to global channel & user-specific notifications channel
		subscribe("achievement_unlocked", handlePayload);
		if (user?.id) {
			subscribe(`user:${user.id}:notifications`, handlePayload);
		}

		return () => {
			unsubscribe("achievement_unlocked", handlePayload);
			if (user?.id) {
				unsubscribe(`user:${user.id}:notifications`, handlePayload);
			}
		};
	}, [subscribe, unsubscribe, user?.id, enqueue]);

	if (!current) return null;

	const styles = getRarityStyles(current.rarity);
	const IconComponent = iconMap[current.id] || Trophy;

	// Localized name & description fallback
	const localizedName = t(`account:${current.id}.name`, {
		defaultValue: current.name,
	});
	const localizedDesc = t(`account:${current.id}.description`, {
		defaultValue: current.description,
	});

	return (
		<div className="fixed bottom-6 right-6 z-[9999] pointer-events-auto max-w-sm w-full select-none">
			<AnimatePresence>
				<motion.div
					key={current.id}
					initial={{ opacity: 0, y: 40, scale: 0.92 }}
					animate={{ opacity: 1, y: 0, scale: 1 }}
					exit={{ opacity: 0, y: 20, scale: 0.95 }}
					transition={{ type: "spring", stiffness: 450, damping: 30 }}
					className={`relative overflow-hidden rounded-xl border bg-gradient-to-r ${styles.bgGlow} ${styles.border} backdrop-blur-xl p-4 shadow-2xl`}
				>
					{/* Animated Metallic Sheen / Sweep Effect */}
					<div className="pointer-events-none absolute -inset-full animate-[spin_8s_linear_infinite] opacity-10 bg-[conic-gradient(from_0deg,transparent_0_340deg,white_360deg)]" />

					{/* Header Banner (Steam / Xbox style) */}
					<div className="flex items-center justify-between gap-2 pb-2 mb-2 border-b border-white/10">
						<div className="flex items-center gap-1.5">
							<Trophy className="w-3.5 h-3.5 text-amber-400 animate-pulse" />
							<span className="text-[10px] font-black uppercase tracking-[0.2em] text-amber-400/90 font-mono">
								{t("common:achievementUnlockedTitle", "ДОСТИЖЕНИЕ РАЗБЛОКИРОВАНО")}
							</span>
						</div>
						<button
							type="button"
							onClick={() => setCurrent(null)}
							className="text-zinc-500 hover:text-zinc-300 transition-colors p-0.5 rounded"
						>
							<X className="w-3.5 h-3.5" />
						</button>
					</div>

					{/* Main Body */}
					<div className="flex items-center gap-3.5">
						{/* Glowing Achievement Icon Box */}
						<div
							className={`relative flex h-14 w-14 shrink-0 items-center justify-center rounded-lg border ${styles.border} bg-black/60 shadow-inner`}
						>
							<IconComponent className={`h-7 w-7 ${styles.iconGlow}`} />
						</div>

						{/* Content */}
						<div className="flex-1 min-w-0">
							<div className="flex items-center gap-2">
								<h4 className="text-sm font-bold text-white truncate drop-shadow-sm">
									{localizedName}
								</h4>
								<span
									className={`text-[9px] font-black uppercase px-1.5 py-0.5 rounded border ${styles.badge}`}
								>
									{current.rarity}
								</span>
							</div>

							<p className="text-xs text-zinc-400 line-clamp-2 mt-0.5 leading-snug">
								{localizedDesc}
							</p>

							{/* Rewards Footer */}
							<div className="flex items-center gap-2 mt-2">
								<div className="flex items-center gap-1 bg-amber-500/10 border border-amber-500/30 text-amber-400 px-2 py-0.5 rounded text-[11px] font-semibold">
									<Sparkles className="w-3 h-3 text-amber-400" />
									<span>+{current.xp_reward} XP</span>
								</div>
							</div>
						</div>
					</div>

					{/* Auto-dismiss progress bar */}
					<motion.div
						initial={{ width: "100%" }}
						animate={{ width: "0%" }}
						transition={{ duration: 6.5, ease: "linear" }}
						className={`absolute bottom-0 left-0 h-1 bg-gradient-to-r ${styles.bar}`}
					/>
				</motion.div>
			</AnimatePresence>
		</div>
	);
};
