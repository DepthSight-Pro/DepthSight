// src/features/notifications/NotificationBell.tsx

import { Bell, CheckCheck, Trash2 } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import {
	DropdownMenu,
	DropdownMenuContent,
	DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { cn } from "@/lib/utils";
import { useNotifications } from "./NotificationProvider";
import type { UiNotification, UiNotificationSeverity } from "./types";

const SEVERITY_STYLES: Record<UiNotificationSeverity, string> = {
	info: "bg-cyan",
	// Keep emerald/amber/rose in sync with toast accents.
	success: "bg-emerald-400",
	warning: "bg-amber-400",
	error: "bg-rose-500",
};

function TimeAgo({ tsMs }: { tsMs: number }) {
	const { t } = useTranslation("notifications");
	// Snapshot once per mount (dropdown content remounts on open).
	const [now] = useState(() => Date.now());
	const seconds = Math.max(0, Math.floor((now - tsMs) / 1000));
	if (seconds < 60) return <span>{t("justNow")}</span>;
	const minutes = Math.floor(seconds / 60);
	if (minutes < 60) return <span>{t("minutesAgo", { count: minutes })}</span>;
	const hours = Math.floor(minutes / 60);
	if (hours < 24) return <span>{t("hoursAgo", { count: hours })}</span>;
	const days = Math.floor(hours / 24);
	if (days < 30) return <span>{t("daysAgo", { count: days })}</span>;
	return <span>{new Date(tsMs).toLocaleDateString()}</span>;
}

function NotificationRow({
	notification,
	onOpen,
}: {
	notification: UiNotification;
	onOpen: (id: string) => void;
}) {
	return (
		<button
			type="button"
			onClick={() => onOpen(notification.id)}
			className={cn(
				"relative flex w-full gap-2.5 rounded-lg px-3 py-2.5 text-left transition-colors",
				"hover:bg-muted/70 dark:hover:bg-white/[0.06]",
				!notification.read && "bg-muted/40 dark:bg-white/[0.03]",
			)}
		>
			<span
				className={cn(
					"mt-1.5 h-2 w-2 shrink-0 rounded-full",
					SEVERITY_STYLES[notification.severity],
				)}
			/>
			<span className="min-w-0 flex-1">
				<span className="flex items-start justify-between gap-2">
					<span className="text-[13px] font-semibold leading-snug text-foreground dark:text-white">
						{notification.title}
					</span>
					{!notification.read && (
						<span className="mt-1 h-1.5 w-1.5 shrink-0 rounded-full bg-cyan shadow-[0_0_6px_rgba(0,212,255,0.9)]" />
					)}
				</span>
				<span className="mt-0.5 line-clamp-2 block text-xs leading-relaxed text-muted-foreground dark:text-white/60">
					{notification.body}
				</span>
				<span className="mt-1 flex items-center gap-2 text-[11px] text-muted-foreground/80 dark:text-white/40">
					{notification.symbol && (
						<span className="rounded bg-muted dark:bg-white/[0.07] px-1.5 py-px font-mono text-foreground/80 dark:text-white/70">
							{notification.symbol}
						</span>
					)}
					<TimeAgo tsMs={notification.ts_ms} />
				</span>
			</span>
		</button>
	);
}

export function NotificationBell() {
	const { t } = useTranslation("notifications");
	const {
		notifications,
		unreadCount,
		markAsRead,
		markAllAsRead,
		clearNotifications,
	} = useNotifications();

	return (
		<DropdownMenu>
			<DropdownMenuTrigger asChild>
				<button
					type="button"
					aria-label={t("bellLabel")}
					title={t("bellLabel")}
					className="relative flex h-7 w-7 sm:h-8 sm:w-8 shrink-0 items-center justify-center rounded-lg border border-border/80 dark:border-white/8 bg-card dark:bg-white/[0.03] text-muted-foreground dark:text-white/70 transition-all hover:bg-muted dark:hover:bg-white/[0.08] hover:text-foreground dark:hover:text-white"
				>
					<Bell className="h-3.5 w-3.5 sm:h-4 sm:w-4" />
					{unreadCount > 0 && (
						<span className="absolute -right-1 -top-1 flex h-4 min-w-4 items-center justify-center rounded-full bg-cyan px-1 text-[10px] font-bold leading-none text-obsidian shadow-[0_0_8px_rgba(0,212,255,0.9)]">
							{unreadCount > 99 ? "99+" : unreadCount}
						</span>
					)}
				</button>
			</DropdownMenuTrigger>
			<DropdownMenuContent
				align="end"
				sideOffset={8}
				className="w-[min(380px,calc(100vw-2rem))] rounded-xl border border-border dark:border-white/10 bg-popover/95 dark:bg-background/80 bg-gradient-to-b dark:from-white/[0.05] dark:to-white/[0.015] p-2 text-popover-foreground shadow-2xl backdrop-blur-xl"
			>
				<div className="flex items-center justify-between px-2 py-1.5">
					<span className="text-sm font-semibold text-foreground dark:text-white">
						{t("title")}
						{unreadCount > 0 && (
							<span className="ml-1.5 rounded-full bg-cyan/15 px-1.5 py-px text-[11px] font-bold text-cyan">
								{unreadCount}
							</span>
						)}
					</span>
					<span className="flex items-center gap-1">
						{unreadCount > 0 && (
							<button
								type="button"
								onClick={markAllAsRead}
								title={t("markAllAsRead")}
								className="rounded-md p-1.5 text-muted-foreground hover:text-foreground hover:bg-muted dark:text-white/50 dark:hover:bg-white/10 dark:hover:text-white transition-colors"
							>
								<CheckCheck className="h-4 w-4" />
							</button>
						)}
						{notifications.length > 0 && (
							<button
								type="button"
								onClick={clearNotifications}
								title={t("clearAll")}
								className="rounded-md p-1.5 text-muted-foreground hover:text-rose-500 hover:bg-rose-500/10 dark:text-white/50 dark:hover:bg-rose-500/20 dark:hover:text-rose-300 transition-colors"
							>
								<Trash2 className="h-4 w-4" />
							</button>
						)}
					</span>
				</div>
				<div className="max-h-[min(420px,60vh)] space-y-1 overflow-y-auto">
					{notifications.length === 0 ? (
						<div className="flex flex-col items-center px-4 py-8 text-center">
							<Bell className="mb-2 h-8 w-8 text-muted-foreground/40 dark:text-white/20" />
							<p className="text-sm font-medium text-foreground/80 dark:text-white/80">
								{t("emptyTitle")}
							</p>
							<p className="mt-1 text-xs text-muted-foreground dark:text-white/50">
								{t("emptyDescription")}
							</p>
						</div>
					) : (
						notifications
							.slice(0, 30)
							.map((n) => (
								<NotificationRow
									key={n.id}
									notification={n}
									onOpen={markAsRead}
								/>
							))
					)}
				</div>
			</DropdownMenuContent>
		</DropdownMenu>
	);
}
