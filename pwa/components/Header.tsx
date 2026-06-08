// pwa/components/Header.tsx

import type React from "react";
import { useTranslation } from "react-i18next";
import { ICONS } from "../constants";
import { useNotifications } from "../contexts/NotificationContext";

interface HeaderProps {
	title: string;
	onMenuClick: () => void;
	onBackClick?: () => void;
	showBackButton?: boolean;
}

const Header: React.FC<HeaderProps> = ({
	title,
	onMenuClick,
	onBackClick,
	showBackButton,
}) => {
	const {
		notificationsEnabled,
		toggleNotifications,
		unreadCount,
		isSubscribing,
	} = useNotifications();
	const { t } = useTranslation("pwa-common");

	const handleToggleNotifications = async () => {
		await toggleNotifications();
	};

	return (
		<header className="bg-[hsl(var(--background))] p-4 shadow-sm flex items-center gap-4 z-10 sticky top-0 border-b border-[hsl(var(--border))]">
			{showBackButton ? (
				<button
					type="button"
					className="w-10 h-10 rounded-full flex items-center justify-center transition hover:bg-[hsl(var(--secondary))]"
					onClick={onBackClick}
					aria-label={t("buttons.back")}
				>
					<ICONS.Back className="w-6 h-6 text-[hsl(var(--foreground))]" />
				</button>
			) : (
				<button
					type="button"
					className="w-10 h-10 rounded-full flex items-center justify-center transition hover:bg-[hsl(var(--secondary))]"
					onClick={onMenuClick}
					aria-label={t("buttons.menu")}
				>
					<ICONS.Menu className="w-6 h-6 text-[hsl(var(--foreground))]" />
				</button>
			)}
			<h1 className="text-xl font-bold text-[hsl(var(--foreground))] flex-1 truncate">
				{title}
			</h1>
			<button
				type="button"
				onClick={handleToggleNotifications}
				className={`relative w-10 h-10 rounded-full flex items-center justify-center transition ${
					isSubscribing
						? "opacity-50 cursor-wait"
						: "hover:bg-[hsl(var(--secondary))] cursor-pointer"
				} ${notificationsEnabled ? "bg-green-500/10" : ""}`}
				title={
					notificationsEnabled
						? t("header.notificationsEnabledTitle")
						: t("header.notificationsDisabledTitle")
				}
				aria-label={
					notificationsEnabled
						? t("header.notificationsEnabledTitle")
						: t("header.notificationsDisabledTitle")
				}
				disabled={isSubscribing}
			>
				{isSubscribing ? (
					<ICONS.Loader className="w-6 h-6 text-[hsl(var(--muted-foreground))] animate-spin" />
				) : notificationsEnabled ? (
					<ICONS.Notifications className="w-6 h-6 text-green-500 animate-pulse" />
				) : (
					<ICONS.Notifications className="w-6 h-6 text-[hsl(var(--muted-foreground))]" />
				)}
				{unreadCount > 0 && (
					<span className="absolute top-0 right-0 block h-3 w-3 rounded-full ring-2 ring-[hsl(var(--background))] bg-[hsl(var(--primary))]" />
				)}
			</button>
		</header>
	);
};

export default Header;
