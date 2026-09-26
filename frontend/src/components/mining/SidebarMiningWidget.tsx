// frontend/src/components/mining/SidebarMiningWidget.tsx
import React, { useState, useEffect, useMemo } from "react";
import { Link, useLocation } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { Pickaxe, ChevronRight } from "lucide-react";
import { cn } from "@/lib/utils";
import { Radial } from "@/components/ui/quant-ui";
import {
	Tooltip,
	TooltipContent,
	TooltipProvider,
	TooltipTrigger,
} from "@/components/ui/tooltip";
import type { LocalMiningStatusResponse, MiningDailyHistoryItem } from "@/lib/api";

function formatShortDate(dateStr: string): string {
	if (!dateStr) return "";
	const parts = dateStr.split("-");
	if (parts.length === 3) {
		return `${parts[2]}.${parts[1]}`;
	}
	return dateStr;
}

function generateDefaultDailySeries(todayReward: number = 0): MiningDailyHistoryItem[] {
	const list: MiningDailyHistoryItem[] = [];
	const now = new Date();
	for (let i = 13; i >= 0; i--) {
		const d = new Date(now);
		d.setDate(d.getDate() - i);
		const dateStr = d.toISOString().slice(0, 10);
		list.push({
			date: dateStr,
			reward: i === 0 ? todayReward : 0,
			rebates: 0,
			tradesCount: 0,
		});
	}
	return list;
}

interface SidebarMiningWidgetProps {
	isExpanded: boolean;
	miningStatus?: LocalMiningStatusResponse;
	className?: string;
}

function calculateEpochInfo(
	launchDateStr?: string,
	serverEpochNumber?: number,
	fallbackCount: number = 1,
	currentTimeMs: number = Date.now(),
) {
	const now = new Date(currentTimeMs);
	const utcYear = now.getUTCFullYear();
	const utcMonth = now.getUTCMonth();
	const utcDate = now.getUTCDate();

	const epochStart = Date.UTC(utcYear, utcMonth, utcDate, 0, 0, 0);
	const epochEnd = Date.UTC(utcYear, utcMonth, utcDate + 1, 0, 0, 0);

	const totalMs = epochEnd - epochStart;
	const elapsedMs = Math.max(0, now.getTime() - epochStart);
	const remainingMs = Math.max(0, epochEnd - now.getTime());

	const progressRatio = Math.min(1, Math.max(0, elapsedMs / totalMs));
	const progressPercent = Math.round(progressRatio * 100);

	const hours = Math.floor(remainingMs / (1000 * 60 * 60));
	const minutes = Math.floor((remainingMs % (1000 * 60 * 60)) / (1000 * 60));
	const seconds = Math.floor((remainingMs % (1000 * 60)) / 1000);

	const countdown = `${String(hours).padStart(2, "0")}:${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;

	let epochNumber: number;
	if (typeof serverEpochNumber === "number" && serverEpochNumber >= 1) {
		epochNumber = serverEpochNumber;
	} else if (launchDateStr) {
		const lDate = new Date(launchDateStr);
		if (!Number.isNaN(lDate.getTime())) {
			const launchUtc = Date.UTC(
				lDate.getUTCFullYear(),
				lDate.getUTCMonth(),
				lDate.getUTCDate(),
			);
			const diffDays = Math.floor(
				(epochStart - launchUtc) / (1000 * 60 * 60 * 24),
			);
			epochNumber = Math.max(1, diffDays + 1);
		} else {
			epochNumber = Math.max(1, fallbackCount);
		}
	} else {
		epochNumber = Math.max(1, fallbackCount);
	}

	return {
		progressRatio,
		progressPercent,
		countdown,
		epochNumber,
	};
}

function formatCompact(val: number): string {
	if (val >= 1_000_000) return `${(val / 1_000_000).toFixed(2)}M`;
	if (val >= 1_000) return `${(val / 1_000).toFixed(1)}K`;
	return val.toFixed(1);
}

export const SidebarMiningWidget: React.FC<SidebarMiningWidgetProps> = ({
	isExpanded,
	miningStatus,
	className,
}) => {
	const { t } = useTranslation(["mining", "common"]);
	const { pathname } = useLocation();
	const isActive = pathname === "/mining" || pathname.startsWith("/mining");

	const stats = miningStatus?.stats;
	const launchDate =
		miningStatus?.launchDate ||
		miningStatus?.launch_date ||
		(stats?.launchDate as string | undefined) ||
		(stats?.launch_date as string | undefined);

	const serverEpoch =
		miningStatus?.epochNumber ??
		miningStatus?.epoch_number ??
		(typeof stats?.epochNumber === "number" ? stats.epochNumber : undefined) ??
		(typeof stats?.epoch_number === "number" ? stats.epoch_number : undefined);

	const historyCount =
		miningStatus?.dailyHistory?.length ||
		miningStatus?.daily_history?.length ||
		stats?.dailyHistory?.length ||
		stats?.daily_history?.length ||
		1;

	const [now, setNow] = useState(() => Date.now());

	useEffect(() => {
		const timer = setInterval(() => {
			setNow(Date.now());
		}, 1000);
		return () => clearInterval(timer);
	}, []);

	const epochInfo = useMemo(
		() => calculateEpochInfo(launchDate, serverEpoch, historyCount, now),
		[launchDate, serverEpoch, historyCount, now],
	);

	const totalMined = miningStatus?.totalMined ?? stats?.totalNodeMined ?? stats?.serverTotalMined ?? 0;
	const todayReward = stats?.your_epoch_reward ?? stats?.yourEpochReward ?? 0;

	// 14-Day Rate Bar Chart data (matching MiningRateCard on the /mining tab)
	const displayData = useMemo<MiningDailyHistoryItem[]>(() => {
		const rawHistory =
			miningStatus?.dailyHistory ||
			miningStatus?.daily_history ||
			stats?.dailyHistory ||
			stats?.daily_history;

		let list: MiningDailyHistoryItem[];
		if (rawHistory && rawHistory.length > 0) {
			if (rawHistory.length >= 14) {
				list = rawHistory.slice(-14);
			} else {
				const padded: MiningDailyHistoryItem[] = [];
				const firstDate = new Date(rawHistory[0].date);
				const needed = 14 - rawHistory.length;
				for (let i = needed; i > 0; i--) {
					const d = new Date(firstDate);
					d.setDate(d.getDate() - i);
					padded.push({
						date: d.toISOString().slice(0, 10),
						reward: 0,
						rebates: 0,
						tradesCount: 0,
					});
				}
				list = [...padded, ...rawHistory];
			}
		} else {
			list = generateDefaultDailySeries(todayReward);
		}

		// Ensure today's estimated reward is reflected on the active day if higher
		if (list.length > 0 && todayReward > 0) {
			const lastIdx = list.length - 1;
			if ((list[lastIdx].reward ?? 0) < todayReward) {
				const updated = [...list];
				updated[lastIdx] = {
					...updated[lastIdx],
					reward: todayReward,
				};
				list = updated;
			}
		}

		return list;
	}, [miningStatus, stats, todayReward]);

	const maxReward = useMemo(() => {
		const maxVal = Math.max(...displayData.map((d) => d.reward || 0), 0);
		return maxVal > 0 ? maxVal : 1;
	}, [displayData]);

	const { progressRatio, progressPercent, countdown, epochNumber } = epochInfo;

	// COLLAPSED VIEW
	if (!isExpanded) {
		return (
			<div className={cn("flex justify-center w-full", className)}>
				<Tooltip>
					<TooltipTrigger asChild>
						<Link
							to="/mining"
							className={cn(
								"group relative flex h-14 w-12 flex-col items-center justify-center rounded-xl border p-1 transition-all duration-200",
								isActive
									? "border-cyan-500/60 bg-cyan-500/10 shadow-[0_0_15px_rgba(0,240,255,0.25)]"
									: "border-white/10 bg-white/[0.02] hover:border-cyan-500/40 hover:bg-white/[0.05]",
							)}
						>
							{/* Radial progress ring with Pickaxe in the center */}
							<div className="relative flex items-center justify-center">
								<Radial
									value={progressRatio}
									size={32}
									stroke={2.5}
									color="#00F0FF"
									glow={false}
								>
									<Pickaxe className="h-3.5 w-3.5 text-cyan-400 group-hover:scale-110 transition-transform" />
								</Radial>
							</div>

							{/* Percentage below radial in cyan (not green) */}
							<span className="mt-0.5 font-mono text-[8px] font-black text-cyan-300 leading-none">
								{progressPercent}%
							</span>
						</Link>
					</TooltipTrigger>

					<TooltipContent
						side="right"
						sideOffset={10}
						className="z-[100] w-64 rounded-xl border border-cyan-500/30 bg-[#0B0D12]/95 p-3.5 text-white shadow-2xl backdrop-blur-xl"
					>
						{/* Tooltip Header */}
						<div className="flex items-center justify-between border-b border-white/10 pb-2">
							<div className="flex items-center gap-1.5">
								<div className="p-1 rounded bg-cyan-500/10 text-cyan-400">
									<Pickaxe className="h-3.5 w-3.5" />
								</div>
								<span className="text-xs font-bold text-white tracking-tight">
									{t("sidebarMiningEpoch", "Epoch")} #{epochNumber}
								</span>
							</div>
							<span className="font-mono text-[9px] font-bold text-cyan-300 bg-cyan-500/15 border border-cyan-500/25 px-1.5 py-0.5 rounded">
								{progressPercent}% {t("sidebarMiningEpochProgress", "completed")}
							</span>
						</div>

						{/* Tooltip Body with Cyan Numbers */}
						<div className="mt-2.5 space-y-2 text-xs font-mono">
							<div className="flex items-center justify-between">
								<span className="text-white/40 text-[11px] font-sans">
									{t("sidebarMiningUntilSettlement", "Until settlement")}:
								</span>
								<span className="font-bold text-cyan-400">{countdown}</span>
							</div>

							<div className="flex items-center justify-between">
								<span className="text-white/40 text-[11px] font-sans">
									{t("sidebarMiningEstReward", "Est. Reward")}:
								</span>
								<span className="font-bold text-cyan-400">
									~{todayReward >= 1000 ? Math.round(todayReward).toLocaleString() : todayReward.toFixed(1)} $DEPTH
								</span>
							</div>

							<div className="flex items-center justify-between border-t border-white/5 pt-1.5">
								<span className="text-white/40 text-[11px] font-sans">
									{t("sidebarMiningTotalBalance", "Total Balance")}:
								</span>
								<span className="font-black bg-gradient-to-r from-[#00F0FF] via-[#1DA2B4] to-blue-400 bg-clip-text text-transparent">
									{totalMined >= 1000 ? Math.round(totalMined).toLocaleString() : totalMined.toFixed(2)} $DEPTH
								</span>
							</div>
						</div>

						<div className="mt-2.5 pt-2 border-t border-white/5 flex items-center justify-between text-[9px] text-cyan-400/80 hover:text-cyan-300 transition-colors">
							<span>{t("sidebarMiningClickHub", "Click to open Trade Mining Hub →")}</span>
							<ChevronRight className="h-3 w-3" />
						</div>
					</TooltipContent>
				</Tooltip>
			</div>
		);
	}

	// EXPANDED VIEW
	return (
		<div className={cn("w-full px-2", className)}>
			<Link
				to="/mining"
				className={cn(
					"group relative block cursor-pointer overflow-hidden rounded-xl border p-2.5 transition-all duration-300",
					isActive
						? "border-cyan-500/50 bg-gradient-to-b from-cyan-500/10 via-white/[0.03] to-transparent shadow-[0_0_20px_rgba(0,240,255,0.15)]"
						: "border-white/10 bg-white/[0.02] hover:border-cyan-500/40 hover:bg-white/[0.04] hover:shadow-[0_4px_16px_rgba(0,0,0,0.4)]",
				)}
			>
				{/* Top Header: Epoch & Countdown in cyan */}
				<div className="flex items-center justify-between text-[10px] mb-1.5">
					<div className="flex items-center gap-1.5 text-white/70 font-bold uppercase tracking-wider">
						<Pickaxe className="h-3.5 w-3.5 text-cyan-400 group-hover:scale-105 transition-transform" />
						<span>{t("sidebarMiningEpoch", "Epoch")} #{epochNumber}</span>
					</div>
					<span className="font-mono text-cyan-400 font-semibold text-[10px]">
						{countdown} {t("sidebarMiningUntilSettlement", "until settlement")}
					</span>
				</div>

				{/* 24-Hour Epoch Progress Bar */}
				<div className="w-full bg-white/10 h-1.5 rounded-full overflow-hidden mb-2">
					<div
						className="h-full rounded-full bg-gradient-to-r from-cyan-500 via-blue-500 to-indigo-500 shadow-[0_0_8px_rgba(0,240,255,0.5)] transition-all duration-1000"
						style={{ width: `${progressPercent}%` }}
					/>
				</div>

				{/* Middle Stat Metrics: cyan numbers */}
				<div className="flex items-center justify-between text-xs">
					<div>
						<div className="text-[9px] uppercase tracking-wider text-white/40 font-medium leading-none">
							{t("sidebarMiningEstReward", "Est. Reward")}
						</div>
						<div className="font-mono text-xs font-black text-cyan-400 mt-0.5 leading-tight">
							~{todayReward >= 1000 ? Math.round(todayReward).toLocaleString() : todayReward.toFixed(1)}{" "}
							<span className="text-[9.5px] text-cyan-300/80 font-bold">$DEPTH</span>
						</div>
					</div>

					<div className="text-right">
						<div className="text-[9px] uppercase tracking-wider text-white/40 font-medium leading-none">
							{t("sidebarMiningTotalBalance", "Total Balance")}
						</div>
						<div className="font-mono text-xs font-bold text-white mt-0.5 leading-tight">
							<span className="bg-gradient-to-r from-[#00F0FF] via-[#1DA2B4] to-blue-400 bg-clip-text text-transparent font-black">
								{formatCompact(totalMined)}
							</span>{" "}
							<span className="text-[9.5px] text-white/40 font-normal">$DEPTH</span>
						</div>
					</div>
				</div>

				{/* 14-Day Rate Bar Chart (matching /mining tab) */}
				<div className="mt-2.5 pt-2 border-t border-white/5 space-y-1">
					<TooltipProvider delayDuration={80}>
						<div className="flex items-end gap-1 h-7 px-0.5">
							{displayData.map((item, idx) => {
								const isToday = idx === displayData.length - 1;
								const isZero = (item.reward || 0) <= 0;
								const heightPct = Math.max(
									Math.round(((item.reward || 0) / maxReward) * 100),
									isZero ? 10 : 18,
								);

								return (
									<Tooltip key={item.date || idx}>
										<TooltipTrigger asChild>
											<div
												className={cn(
													"flex-1 rounded-t-sm transition-all cursor-pointer relative",
													isToday
														? "bg-gradient-to-t from-cyan-600/50 via-cyan-400 to-cyan-200 border-t border-cyan-300 shadow-[0_0_8px_rgba(0,212,255,0.4)] hover:shadow-[0_0_12px_rgba(0,212,255,0.9)] hover:to-white"
														: isZero
															? "bg-white/10 hover:bg-white/20"
															: "bg-gradient-to-t from-blue-600/35 via-cyan-500/75 to-cyan-400 hover:from-cyan-400 hover:to-white hover:shadow-[0_0_10px_rgba(0,212,255,0.8)]",
												)}
												style={{
													height: `${heightPct}%`,
													opacity: isZero ? 0.35 : 0.6 + (idx / displayData.length) * 0.4,
												}}
											/>
										</TooltipTrigger>
										<TooltipContent
											side="top"
											align={isToday ? "end" : "center"}
											sideOffset={8}
											collisionPadding={12}
											className="bg-black/95 border-cyan-500/30 text-white font-mono text-[10px] p-2 backdrop-blur-md shadow-2xl z-[100] pointer-events-none"
										>
											<div className="flex items-center justify-between gap-2 border-b border-white/10 pb-1 mb-1">
												<span className="font-semibold text-white/80">
													{isToday ? t("today", "Today") : formatShortDate(item.date)}
												</span>
												{isToday && (
													<span className="text-[8px] px-1 py-0.2 rounded bg-cyan-500/20 text-cyan-300">
														{t("inProgress", "In progress")}
													</span>
												)}
											</div>
											<div className="flex justify-between gap-2">
												<span className="text-white/60">{t("sidebarMiningEstReward", "Reward")}:</span>
												<span className="font-bold text-cyan-300">
													{(item.reward || 0) >= 1000
														? Math.round(item.reward).toLocaleString()
														: (item.reward || 0).toFixed(1)}{" "}
													$DEPTH
												</span>
											</div>
										</TooltipContent>
									</Tooltip>
								);
							})}
						</div>
					</TooltipProvider>

					{/* Time axis labels */}
					<div className="flex justify-between text-[8px] font-mono text-white/35 px-0.5">
						<span>
							{displayData[0]?.date
								? formatShortDate(displayData[0].date)
								: "14d"}
						</span>
						<span>
							{displayData[6]?.date
								? formatShortDate(displayData[6].date)
								: "7d"}
						</span>
						<span className="text-cyan-400/80 font-medium">
							{t("today", "Today")}
						</span>
					</div>
				</div>
			</Link>
		</div>
	);
};

export default SidebarMiningWidget;
