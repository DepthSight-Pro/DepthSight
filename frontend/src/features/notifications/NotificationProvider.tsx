// src/features/notifications/NotificationProvider.tsx
/* eslint-disable react-refresh/only-export-components */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type React from "react";
import { createContext, useContext } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useToast } from "@/components/ui/use-toast";
import { useAuth } from "@/context/AuthContext";
import { useWebSocket } from "@/context/WebSocketProvider";
import { useStrategyConfigsList } from "@/lib/api";
import type { StrategyData } from "@/types/api";
import {
	applyStrategyDisplayName,
	buildNameByConfigId,
	resolveStrategyDisplayName,
} from "./resolveStrategyName";
import {
	isUiNotificationPayload,
	normalizeSeverity,
	type UiNotification,
	type UiNotificationPayload,
} from "./types";

const MAX_STORED = 100;

interface NotificationContextValue {
	notifications: UiNotification[];
	unreadCount: number;
	markAsRead: (id: string) => void;
	markAllAsRead: () => void;
	clearNotifications: () => void;
}

const NotificationContext =
	createContext<NotificationContextValue | null>(null);

const storageKey = (userId: number) => `depthsight:notifications:${userId}`;

function loadStored(userId: number): UiNotification[] {
	try {
		const raw = localStorage.getItem(storageKey(userId));
		if (!raw) return [];
		const parsed = JSON.parse(raw) as unknown;
		if (!Array.isArray(parsed)) return [];
		return parsed
			.filter(
				(n): n is UiNotification =>
					typeof n === "object" &&
					n !== null &&
					typeof (n as UiNotification).id === "string",
			)
			.slice(0, MAX_STORED);
	} catch {
		return [];
	}
}

type ToastFn = ReturnType<typeof useToast>["toast"];

// Same renderer as strategy-launch notifications (shadcn Toaster): default
// glass card, destructive variant for errors.
function showToast(toast: ToastFn, n: UiNotification) {
	const duration = n.severity === "error" ? 8000 : 5000;
	if (n.severity === "error") {
		toast({ variant: "destructive", title: n.title, description: n.body, duration });
		return;
	}
	toast({ title: n.title, description: n.body, duration });
}

export const NotificationProvider: React.FC<{ children: React.ReactNode }> = ({
	children,
}) => {
	const { user } = useAuth();
	const { subscribe, unsubscribe } = useWebSocket();
	const { toast } = useToast();
	const queryClient = useQueryClient();
	const { data: savedConfigs } = useStrategyConfigsList();
	const userId = user?.id;
	const [notifications, setNotifications] = useState<UiNotification[]>([]);
	const toastedIds = useRef<Set<string>>(new Set());
	const [prevUserId, setPrevUserId] = useState<number | undefined>(undefined);

	// Render-phase user switch (same pattern as EventLog): reload per-user history.
	if (userId !== prevUserId) {
		setPrevUserId(userId);
		setNotifications(userId ? loadStored(userId) : []);
	}

	// Persist.
	useEffect(() => {
		if (!userId) return;
		try {
			localStorage.setItem(
				storageKey(userId),
				JSON.stringify(notifications.slice(0, MAX_STORED)),
			);
		} catch {
			// Storage full or unavailable: keep in-memory only.
		}
	}, [notifications, userId]);

	// Same source as the "Best strategies" card: saved configs id -> custom name.
	const nameByConfigId = useMemo(
		() => buildNameByConfigId(savedConfigs),
		[savedConfigs],
	);

	// Running strategy snapshots already in the React Query cache (all modes
	// and accounts, push-driven). Cache read only, no extra requests.
	const collectStrategies = useCallback((): StrategyData[] => {
		const all: StrategyData[] = [];
		for (const q of queryClient
			.getQueryCache()
			.findAll({ queryKey: ["strategies"] })) {
			const d = q.state.data as unknown;
			if (Array.isArray(d)) all.push(...(d as StrategyData[]));
		}
		return all;
	}, [queryClient]);

	const handlePayload = useCallback(
		(payload: unknown) => {
			if (!isUiNotificationPayload(payload)) return;
			const incoming: UiNotificationPayload = payload;
			if (userId !== undefined && incoming.user_id !== userId) {
				return;
			}
			const display = resolveStrategyDisplayName(
				{
					symbol: incoming.symbol,
					api_key_id: incoming.api_key_id,
					data: incoming.data,
				},
				collectStrategies(),
				nameByConfigId,
			);
			const text = applyStrategyDisplayName(
				incoming.title,
				incoming.body,
				incoming.data?.strategy,
				display,
			);
			const next: UiNotification = {
				...incoming,
				type: incoming.type as UiNotification["type"],
				severity: normalizeSeverity(incoming.severity),
				title: text.title,
				body: text.body,
				read: false,
			};
			setNotifications((prev) => {
				if (prev.some((n) => n.id === next.id)) return prev;
				return [next, ...prev].slice(0, MAX_STORED);
			});
			if (!toastedIds.current.has(next.id)) {
				toastedIds.current.add(next.id);
				showToast(toast, next);
			}
		},
		[userId, toast, collectStrategies, nameByConfigId],
	);

	// Late fix-up (render-phase, same pattern as EventLog): notifications baked
	// before configs finished loading get their custom names once configs arrive.
	const [prevConfigs, setPrevConfigs] = useState<typeof savedConfigs>(undefined);
	if (savedConfigs !== prevConfigs) {
		setPrevConfigs(savedConfigs);
		if (savedConfigs && savedConfigs.length > 0) {
			const strategies = collectStrategies();
			setNotifications((prev) => {
				let changed = false;
				const next = prev.map((n) => {
					const system = n.data?.strategy;
					if (
						!system ||
						(!n.title.includes(system) && !n.body.includes(system))
					) {
						return n;
					}
					const display = resolveStrategyDisplayName(
						n,
						strategies,
						nameByConfigId,
					);
					if (!display) return n;
					const text = applyStrategyDisplayName(
						n.title,
						n.body,
						system,
						display,
					);
					if (text.title === n.title && text.body === n.body) return n;
					changed = true;
					return { ...n, title: text.title, body: text.body };
				});
				return changed ? next : prev;
			});
		}
	}

	useEffect(() => {
		if (!userId) return;
		const channel = `user:${userId}:notifications`;
		subscribe(channel, handlePayload);
		return () => {
			unsubscribe(channel, handlePayload);
		};
	}, [userId, subscribe, unsubscribe, handlePayload]);

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

	const value = useMemo<NotificationContextValue>(() => {
	 const unreadCount = notifications.reduce(
			(acc, n) => acc + (n.read ? 0 : 1),
			0,
		);
		return {
			notifications,
			unreadCount,
			markAsRead,
			markAllAsRead,
			clearNotifications,
		};
	}, [notifications, markAsRead, markAllAsRead, clearNotifications]);

	return (
		<NotificationContext.Provider value={value}>
			{children}
		</NotificationContext.Provider>
	);
};

export const useNotifications = (): NotificationContextValue => {
	const ctx = useContext(NotificationContext);
	if (!ctx) {
		throw new Error(
			"useNotifications must be used within a NotificationProvider",
		);
	}
	return ctx;
};
