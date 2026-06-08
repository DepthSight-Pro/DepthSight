// pwa/contexts/NotificationContext.tsx

import {
	createContext,
	type ReactNode,
	useCallback,
	useContext,
	useEffect,
	useState,
} from "react";
import { toast } from "react-hot-toast";
import { useTranslation } from "react-i18next";
import {
	requestNotificationPermission,
	subscribeUserToPush,
	unsubscribeUserFromPush,
} from "../services/notificationService";

export interface AppNotification {
	id: string;
	type:
		| "achievement"
		| "backtest"
		| "position_opened"
		| "position_closed"
		| "info";
	title: string;
	subtitle: string;
	timestamp: number;
	read: boolean;
	icon?: string;
	bgColor?: string;
	// Navigation data
	navigationData?: {
		screen?: string;
		params?: Record<string, unknown>;
	};
}

interface NotificationContextType {
	notificationsEnabled: boolean;
	isSubscribing: boolean;
	notifications: AppNotification[];
	unreadCount: number;
	toggleNotifications: () => Promise<void>;
	markAsRead: (id: string) => void;
	markAllAsRead: () => void;
	clearNotifications: () => void;
	addNotification: (
		notification: Omit<AppNotification, "id" | "timestamp" | "read">,
	) => void;
}

const NotificationContext = createContext<NotificationContextType | undefined>(
	undefined,
);

export const NotificationProvider = ({ children }: { children: ReactNode }) => {
	const [notificationsEnabled, setNotificationsEnabled] = useState<boolean>(
		() => {
			// Check if Service Worker and Push are supported
			const isSupported =
				"serviceWorker" in navigator && "PushManager" in window;
			if (!isSupported) return false;
			return localStorage.getItem("notificationsEnabled") === "true";
		},
	);
	const [isSubscribing, setIsSubscribing] = useState<boolean>(false);
	const [notifications, setNotifications] = useState<AppNotification[]>(() => {
		const saved = localStorage.getItem("appNotifications");
		return saved ? JSON.parse(saved) : [];
	});

	const unreadCount = notifications.filter((n) => !n.read).length;
	const { t } = useTranslation("pwa-common");

	useEffect(() => {
		localStorage.setItem("notificationsEnabled", String(notificationsEnabled));
	}, [notificationsEnabled]);

	useEffect(() => {
		localStorage.setItem("appNotifications", JSON.stringify(notifications));
	}, [notifications]);

	// Check Service Worker support on mount
	useEffect(() => {
		if (!("serviceWorker" in navigator) || !("PushManager" in window)) {
			console.warn("Push notifications are not supported in this environment");
			const timer = setTimeout(() => {
				setNotificationsEnabled(false);
			}, 0);
			return () => clearTimeout(timer);
		}
	}, []);

	const addNotification = useCallback(
		(notification: Omit<AppNotification, "id" | "timestamp" | "read">) => {
			const newNotification: AppNotification = {
				...notification,
				id: `notif-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`,
				timestamp: Date.now(),
				read: false,
			};
			setNotifications((prev) => [newNotification, ...prev]);
		},
		[],
	);

	const markAsRead = useCallback((id: string) => {
		setNotifications((prev) =>
			prev.map((n) => (n.id === id ? { ...n, read: true } : n)),
		);
	}, []);

	const markAllAsRead = useCallback(() => {
		setNotifications((prev) => prev.map((n) => ({ ...n, read: true })));
	}, []);

	const clearNotifications = useCallback(() => {
		setNotifications([]);
	}, []);

	const toggleNotifications = useCallback(async () => {
		console.log("toggleNotifications function called.");
		if (!("serviceWorker" in navigator) || !("PushManager" in window)) {
			toast.error(t("notifications.pushNotSupported"));
			return;
		}

		if (notificationsEnabled) {
			// --- Unsubscribe logic ---
			setIsSubscribing(true);
			try {
				await unsubscribeUserFromPush();
				setNotificationsEnabled(false);
				toast.success(t("notifications.notificationsDisabled"));
			} catch (err) {
				console.error("Unsubscribe error:", err);
				// Even if it fails, we disable it visually
				setNotificationsEnabled(false);
				toast.error(t("notifications.unsubscribeFailedLocal"));
			} finally {
				setIsSubscribing(false);
			}
		} else {
			// --- Subscribe logic ---
			// 1. Request permission first, without setting loading state
			const permission = await requestNotificationPermission();

			if (permission === "granted") {
				// 2. If granted, THEN set loading state and subscribe
				setIsSubscribing(true);
				try {
					await subscribeUserToPush();
					setNotificationsEnabled(true);
					toast.success(t("notifications.notificationsEnabled"));
				} catch (err) {
					console.error("Push subscription failed:", err);
					toast.error(t("notifications.subscribeFailed"));
					// Revert state if subscription fails
					setNotificationsEnabled(false);
				} finally {
					// 3. Always remove loading state
					setIsSubscribing(false);
				}
			} else if (permission === "denied") {
				toast.error(t("notifications.permissionBlocked"));
			}
			// If permission is 'default' (user dismissed the prompt), we do nothing.
		}
	}, [notificationsEnabled, t]);

	return (
		<NotificationContext.Provider
			value={{
				notificationsEnabled,
				isSubscribing,
				notifications,
				unreadCount,
				toggleNotifications,
				addNotification,
				markAsRead,
				markAllAsRead,
				clearNotifications,
			}}
		>
			{children}
		</NotificationContext.Provider>
	);
};

export const useNotifications = () => {
	const context = useContext(NotificationContext);
	if (context === undefined) {
		throw new Error(
			"useNotifications must be used within a NotificationProvider",
		);
	}
	return context;
};
