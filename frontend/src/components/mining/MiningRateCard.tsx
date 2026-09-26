import React, { useMemo } from "react";
import { useTranslation } from "react-i18next";
import { Pickaxe } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";
import type { MiningDailyHistoryItem } from "@/lib/api";

export interface MiningRateCardProps {
  userCumulativeRebate: number;
  totalDistributed: number;
  hasWelcomeBonus: boolean;
  welcomeProgress: number;
  userRewardSharePercent: number;
  todayEstimatedReward?: number;
  dailyHistory?: MiningDailyHistoryItem[];
  baseRate?: number;
  className?: string;
}

// Generate fallback 14-day daily series ending today
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

function formatShortDate(dateStr: string): string {
  if (!dateStr) return "";
  const parts = dateStr.split("-");
  if (parts.length === 3) {
    return `${parts[2]}.${parts[1]}`;
  }
  return dateStr;
}

const formatCompact = (n: number) => {
  if (!Number.isFinite(n) || n === 0) return "0";
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return n.toLocaleString("en-US", { maximumFractionDigits: 1 });
};

export const MiningRateCard: React.FC<MiningRateCardProps> = ({
  userCumulativeRebate,
  totalDistributed,
  hasWelcomeBonus,
  welcomeProgress,
  userRewardSharePercent,
  todayEstimatedReward = 0,
  dailyHistory,
  className,
}) => {
  const { t, i18n } = useTranslation(["mining", "common"]);

  const displayData = useMemo<MiningDailyHistoryItem[]>(() => {
    if (dailyHistory && dailyHistory.length > 0) {
      if (dailyHistory.length >= 14) {
        return dailyHistory.slice(-14);
      }
      // Pad leading items if less than 14
      const padded: MiningDailyHistoryItem[] = [];
      const firstDate = new Date(dailyHistory[0].date);
      const needed = 14 - dailyHistory.length;
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
      return [...padded, ...dailyHistory];
    }
    return generateDefaultDailySeries(todayEstimatedReward);
  }, [dailyHistory, todayEstimatedReward]);

  const todayItem = displayData[displayData.length - 1];
  const currentTodayReward = todayItem?.reward ?? todayEstimatedReward ?? 0;
  const maxReward = useMemo(() => {
    const maxVal = Math.max(...displayData.map((d) => d.reward), 0);
    return maxVal > 0 ? maxVal : 1;
  }, [displayData]);

  const dayUnit = i18n.language.startsWith("ru") ? "день" : "day";

  return (
    <div
      className={cn(
        "glass relative rounded-2xl border border-border/80 dark:border-white/10 shadow-xl overflow-hidden p-3.5 sm:p-4 flex flex-col justify-between animate-fade-up",
        className,
      )}
    >
      {/* Ambient background glow */}
      <div className="absolute -top-16 -right-16 w-36 h-36 rounded-full bg-cyan-500/10 blur-3xl pointer-events-none" />
      <div className="absolute -bottom-16 -left-16 w-36 h-36 rounded-full bg-blue-500/5 blur-3xl pointer-events-none" />

      <div className="relative z-10 flex flex-col justify-between flex-1 gap-2.5">
        {/* Header */}
        <div className="flex items-center justify-between mb-0.5">
          <div className="flex items-center gap-2">
            <div className="p-1.5 rounded-lg bg-cyan-500/10 border border-cyan-500/20 text-cyan-500 dark:text-cyan-400">
              <Pickaxe className="h-4 w-4" />
            </div>
            <div>
              <h3 className="text-sm font-bold text-foreground dark:text-white tracking-wide leading-tight">
                {t("miningRate", "Mining Rate")}
              </h3>
              <p className="text-[10px] text-muted-foreground dark:text-white/50 leading-none mt-0.5">
                {t("miningRateSubtitle", "DEPTH / day · last 14 days")}
              </p>
            </div>
          </div>

          <Badge className="bg-cyan-500/10 text-cyan-600 dark:text-cyan-400 border-cyan-500/20 font-mono text-[10px] rounded-md px-2 py-0.5 flex items-center gap-1.5 shadow-sm">
            <span className="relative flex h-1.5 w-1.5">
              <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-cyan-400 opacity-75" />
              <span className="relative inline-flex rounded-full h-1.5 w-1.5 bg-cyan-400" />
            </span>
            ~{currentTodayReward.toFixed(1)} DEPTH/{dayUnit}
          </Badge>
        </div>

        {/* 14-Day Rate Bar Chart */}
        <div className="space-y-1 pt-0.5 flex-1 flex flex-col justify-end">
          <TooltipProvider delayDuration={80}>
            <div className="flex items-end gap-1 sm:gap-1.5 h-[58px] sm:h-[64px] px-0.5">
              {displayData.map((item, idx) => {
                const isToday = idx === displayData.length - 1;
                const isZero = item.reward <= 0;
                const heightPct = Math.max(
                  (item.reward / maxReward) * 100,
                  isZero ? 6 : 14,
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
                              ? "bg-black/10 dark:bg-white/10 hover:bg-black/20 dark:hover:bg-white/20"
                              : "bg-gradient-to-t from-blue-600/35 via-cyan-500/75 to-cyan-400 hover:from-cyan-400 hover:to-white hover:shadow-[0_0_10px_rgba(0,212,255,0.8)]",
                        )}
                        style={{
                          height: `${heightPct}%`,
                          opacity: isZero ? 0.35 : 0.6 + (idx / 14) * 0.4,
                        }}
                      />
                    </TooltipTrigger>
                    <TooltipContent
                      side="top"
                      align={isToday ? "end" : "center"}
                      sideOffset={8}
                      collisionPadding={12}
                      className="bg-popover text-popover-foreground border-border/80 dark:border-cyan-500/30 font-mono text-[10px] p-2 backdrop-blur-md shadow-2xl z-[100] pointer-events-none"
                    >
                      <div className="flex items-center justify-between gap-3 text-[10px] text-muted-foreground dark:text-white/50 border-b border-border/60 dark:border-white/10 pb-1 mb-1">
                        <span className="font-semibold text-foreground/90 dark:text-white/80">
                          {isToday
                            ? t("today", "Today")
                            : formatShortDate(item.date)}
                        </span>
                        {isToday && (
                          <span className="text-[8px] px-1 py-0.2 rounded bg-cyan-500/15 text-cyan-700 dark:text-cyan-300 font-sans">
                            {t("inProgress", "In progress")}
                          </span>
                        )}
                      </div>
                      <div className="space-y-0.5 text-[10.5px]">
                        <div className="flex justify-between gap-3">
                          <span className="text-muted-foreground dark:text-white/60">
                            {t("totalMined", "Reward")}:
                          </span>
                          <span className="font-bold text-cyan-600 dark:text-cyan-300">
                            {item.reward.toFixed(1)} DEPTH
                          </span>
                        </div>
                        {item.rebates !== undefined && item.rebates > 0 && (
                          <div className="flex justify-between gap-3">
                            <span className="text-muted-foreground dark:text-white/60">
                              {t("todayRebates", "Rebates")}:
                            </span>
                            <span className="font-semibold text-foreground dark:text-white">
                              ${item.rebates.toFixed(2)}
                            </span>
                          </div>
                        )}
                        {item.tradesCount !== undefined &&
                          item.tradesCount > 0 && (
                            <div className="flex justify-between gap-3">
                              <span className="text-muted-foreground dark:text-white/60">
                                {t("common:trades", "Trades")}:
                              </span>
                              <span className="font-semibold text-foreground/90 dark:text-white/80">
                                {item.tradesCount}
                              </span>
                            </div>
                          )}
                      </div>
                    </TooltipContent>
                  </Tooltip>
                );
              })}
            </div>
          </TooltipProvider>

          {/* Time axis labels */}
          <div className="flex justify-between text-[8px] font-mono text-muted-foreground/60 dark:text-white/35 px-1 pt-0.5">
            <span>
              {displayData[0]?.date
                ? formatShortDate(displayData[0].date)
                : t("daysAgo", { days: 14 })}
            </span>
            <span>
              {displayData[6]?.date
                ? formatShortDate(displayData[6].date)
                : t("daysAgo", { days: 7 })}
            </span>
            <span className="text-cyan-600 dark:text-cyan-400 font-medium">
              {t("today", "Today")}
            </span>
          </div>
        </div>

        {/* Bottom Metrics Row */}
        <div className="mt-auto grid grid-cols-4 gap-2 border-t border-border/40 dark:border-white/5 pt-2.5">
          <div className="space-y-0.5 min-w-0">
            <div className="text-[9px] uppercase tracking-wider text-muted-foreground/75 dark:text-white/40 font-medium truncate">
              {t("cumulativeRebate", "Cumulative rebate")}
            </div>
            <div className="font-mono text-xs font-semibold text-foreground dark:text-white truncate">
              ${userCumulativeRebate.toFixed(1)}
            </div>
          </div>

          <div className="space-y-0.5 min-w-0">
            <div className="text-[9px] uppercase tracking-wider text-muted-foreground/75 dark:text-white/40 font-medium truncate">
              {t("distributed", "Distributed")}
            </div>
            <div className="font-mono text-xs font-semibold text-foreground dark:text-white truncate">
              {formatCompact(totalDistributed)} Ð
            </div>
          </div>

          <div className="space-y-0.5 min-w-0">
            <div className="text-[9px] uppercase tracking-wider text-muted-foreground/75 dark:text-white/40 font-medium truncate">
              {t("welcomeBonus", "Welcome bonus")}
            </div>
            <div className="font-mono text-xs font-semibold truncate">
              {hasWelcomeBonus ? (
                <span className="text-amber-500 dark:text-amber-300 font-bold">
                  {t("claimed", "Claimed")}
                </span>
              ) : (
                <span className="text-muted-foreground dark:text-white/70">
                  {Math.round(welcomeProgress)}%
                </span>
              )}
            </div>
          </div>

          <div className="space-y-0.5 min-w-0">
            <div className="text-[9px] uppercase tracking-wider text-muted-foreground/75 dark:text-white/40 font-medium truncate">
              {t("rewardShare", "Reward share")}
            </div>
            <div className="font-mono text-xs font-semibold text-cyan-600 dark:text-cyan-400 truncate">
              {userRewardSharePercent}%
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};

export default MiningRateCard;
