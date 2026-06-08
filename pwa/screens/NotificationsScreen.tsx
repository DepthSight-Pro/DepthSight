// pwa/screens/NotificationsScreen.tsx

import type { TFunction } from "i18next";
import type React from "react";
import { useTranslation } from "react-i18next";
import {
	type AppNotification,
	useNotifications,
} from "../contexts/NotificationContext";
import { Screen } from "../types";

// Translatable function for displaying time
const formatTimeAgo = (timestamp: number, t: TFunction): string => {
	const seconds = Math.floor((Date.now() - timestamp) / 1000);
	const minutes = Math.floor(seconds / 60);
	const hours = Math.floor(minutes / 60);
	const days = Math.floor(hours / 24);

	if (seconds < 60) return t("notifications.time.justNow");
	if (minutes < 60)
		return t("notifications.time.minutesAgo", { count: minutes });
	if (hours < 24) return t("notifications.time.hoursAgo", { count: hours });
	if (days < 7) return t("notifications.time.daysAgo", { count: days });
	return new Date(timestamp).toLocaleDateString(undefined, {
		month: "short",
		day: "numeric",
	});
};

interface NotificationItemProps {
	notification: AppNotification;
	onMarkAsRead: (id: string) => void;
	onNavigate?: (screen: Screen, params?: Record<string, unknown>) => void;
}

// Restored NotificationItem component
const NotificationItem: React.FC<NotificationItemProps> = ({
	notification,
	onMarkAsRead,
	onNavigate,
}) => {
	const { t } = useTranslation("pwa-common");

	const handleClick = () => {
		if (!notification.read) {
			onMarkAsRead(notification.id);
		}

		if (notification.navigationData?.screen && onNavigate) {
			const screenKey = notification.navigationData
				.screen as keyof typeof Screen;
			const screen = Screen[screenKey];
			if (screen) {
				onNavigate(screen, notification.navigationData.params);
			}
		}
	};

	const hasNavigation = !!notification.navigationData?.screen;

	return (
		<div
			className={`bg-[hsl(var(--card))] rounded-xl p-4 mb-3 shadow-sm transition hover:shadow-md active:scale-[0.98] ${
				hasNavigation ? "cursor-pointer" : "cursor-default"
			} ${
				!notification.read
					? "border-2 border-[hsl(var(--primary))]"
					: "border border-[hsl(var(--border))]"
			}`}
			onClick={handleClick}
		>
			<div className="flex gap-3">
				<div
					className={`w-10 h-10 ${notification.bgColor || "bg-[hsl(var(--secondary))]"} rounded-full flex items-center justify-center text-white text-lg flex-shrink-0`}
				>
					{notification.icon || "🔔"}
				</div>
				<div className="flex-1 min-w-0">
					<div className="flex items-start justify-between gap-2">
						<div className="font-medium text-[hsl(var(--card-foreground))]">
							{notification.title}
						</div>
						<div className="flex items-center gap-1 flex-shrink-0">
							{!notification.read && (
								<div className="w-2 h-2 bg-[hsl(var(--primary))] rounded-full"></div>
							)}
							{hasNavigation && (
								<svg
									className="w-4 h-4 text-[hsl(var(--muted-foreground))]"
									fill="none"
									stroke="currentColor"
									viewBox="0 0 24 24"
								>
									<path
										strokeLinecap="round"
										strokeLinejoin="round"
										strokeWidth={2}
										d="M9 5l7 7-7 7"
									/>
								</svg>
							)}
						</div>
					</div>
					<div className="text-sm text-[hsl(var(--muted-foreground))] break-words">
						{notification.subtitle}
					</div>
					<div className="text-xs text-[hsl(var(--muted-foreground))] mt-1">
						{formatTimeAgo(notification.timestamp, t)}
					</div>
				</div>
			</div>
		</div>
	);
};

interface NotificationsScreenProps {
	onNavigate?: (screen: Screen, params?: Record<string, unknown>) => void;
}

const NotificationsScreen: React.FC<NotificationsScreenProps> = ({
	onNavigate,
}) => {
	const {
		notifications,
		markAsRead,
		markAllAsRead,
		clearNotifications,
		unreadCount,
	} = useNotifications();
	const { t } = useTranslation("pwa-common");

	return (
		<div className="p-4 animate-fadeIn">
			{notifications.length > 0 ? (
				<>
					<div className="flex gap-3 mb-4">
						{unreadCount > 0 && (
							<button
								onClick={markAllAsRead}
								className="flex-1 py-2 px-4 rounded-lg bg-[hsl(var(--secondary))] text-[hsl(var(--secondary-foreground))] text-sm font-medium transition hover:opacity-90"
							>
								{t("notifications.markAllAsRead")}
							</button>
						)}
						<button
							onClick={clearNotifications}
							className="flex-1 py-2 px-4 rounded-lg bg-red-500/10 text-red-500 text-sm font-medium transition hover:bg-red-500/20"
						>
							{t("notifications.clearAll")}
						</button>
					</div>
					<div>
						{notifications.map((notification) => (
							<NotificationItem
								key={notification.id}
								notification={notification}
								onMarkAsRead={markAsRead}
								onNavigate={onNavigate}
							/>
						))}
					</div>
				</>
			) : (
				<div className="flex flex-col items-center justify-center py-20 text-center">
					<div className="text-6xl mb-4">🔔</div>
					<div className="text-lg font-medium text-[hsl(var(--foreground))] mb-2">
						{t("notifications.empty.title")}
					</div>
					<div className="text-sm text-[hsl(var(--muted-foreground))]">
						{t("notifications.empty.description")}
					</div>
				</div>
			)}
		</div>
	);
};

export default NotificationsScreen;
