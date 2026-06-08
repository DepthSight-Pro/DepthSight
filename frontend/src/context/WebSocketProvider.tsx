// src/context/WebSocketProvider.tsx

import { useQueryClient } from "@tanstack/react-query";
/* eslint-disable react-refresh/only-export-components */
import type React from "react";
import {
	createContext,
	useCallback,
	useContext,
	useEffect,
	useMemo,
	useRef,
} from "react";
import useBaseWebSocket, { type ReadyState } from "react-use-websocket";
import { authScopedQueryKey } from "@/lib/queryKeys";
import type { LogEntry } from "@/types/api";
import { useAuth } from "./AuthContext";

// --- Types for dynamic subscriptions ---
type WebSocketCallback = (payload: unknown) => void;
type SubscriptionMap = Map<string, Set<WebSocketCallback>>;

interface WebSocketContextType {
	readyState: ReadyState;
	subscribe: (channel: string, callback: WebSocketCallback) => void;
	unsubscribe: (channel: string, callback: WebSocketCallback) => void;
}

const WebSocketContext = createContext<WebSocketContextType | null>(null);

const protectedUserTopicPatterns = [
	/^user_logs:(\d+)$/,
	/^important_logs:(\d+)$/,
	/^depthsight:events:positions:(\d+)$/,
	/^depthsight:events:strategies:(\d+)$/,
	/^depthsight:events:portfolio:(\d+)$/,
];

const getTopicUserId = (topic: string): number | null => {
	for (const pattern of protectedUserTopicPatterns) {
		const match = topic.match(pattern);
		if (match) return Number(match[1]);
	}
	return null;
};

const isUserScopedTopic = (topic: string) =>
	topic.startsWith("user_logs:") ||
	topic.startsWith("important_logs:") ||
	topic.startsWith("depthsight:events:positions") ||
	topic.startsWith("depthsight:events:strategies") ||
	topic.startsWith("depthsight:events:portfolio") ||
	topic.startsWith("depthsight:events:log");

const getSocketUrl = (token: string | null) => {
	// If there is no token, do not attempt to connect
	if (!token) {
		console.warn(
			"WebSocket: Auth token not found, connection will be delayed.",
		);
		return null;
	}

	let finalUrl: string;

	// Vite provides the import.meta.env.DEV variable, which is true only when running `npm run dev`
	if (import.meta.env.DEV) {
		// DEVELOPMENT MODE: take the URL from the .env file
		const WS_URL_DEV = import.meta.env.VITE_WS_URL;
		if (!WS_URL_DEV) {
			console.error(
				"VITE_WS_URL is not defined in your .env file for development!",
			);
			return null;
		}
		finalUrl = WS_URL_DEV;
	} else {
		// PRODUCTION MODE: build the URL dynamically
		// 1. Determine the protocol: 'wss:' for https, 'ws:' for http
		const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
		// 2. Determine the host: this will be your_domain.com
		const host = window.location.host;
		// 3. Construct the URL. Nginx on the server will intercept /ws and redirect where needed.
		finalUrl = `${protocol}//${host}/ws`;
	}

	// Add the token to the final URL
	return `${finalUrl}?token=${encodeURIComponent(token)}`;
};

export const WebSocketProvider: React.FC<{ children: React.ReactNode }> = ({
	children,
}) => {
	const queryClient = useQueryClient();
	const { token: authToken, user } = useAuth();
	const subscriptions = useRef<SubscriptionMap>(new Map());

	const socketUrl = useMemo(() => getSocketUrl(authToken), [authToken]);

	const { lastMessage, readyState, sendMessage } = useBaseWebSocket(
		socketUrl,
		{
			shouldReconnect: () => true,
			reconnectInterval: 5000,
			retryOnError: true,
		},
		!!socketUrl, // Only connect when socketUrl is fully built with a token
	);

	const subscribe = useCallback(
		(channel: string, callback: WebSocketCallback) => {
			if (!subscriptions.current.has(channel)) {
				subscriptions.current.set(channel, new Set());
				console.log(`[WS] Subscribing to channel: ${channel}`);
				sendMessage(JSON.stringify({ action: "subscribe", channel }));
			}
			subscriptions.current.get(channel)?.add(callback);
		},
		[sendMessage],
	);

	const unsubscribe = useCallback(
		(channel: string, callback: WebSocketCallback) => {
			if (subscriptions.current.has(channel)) {
				const channelCallbacks = subscriptions.current.get(channel)!;
				channelCallbacks.delete(callback);

				if (channelCallbacks.size === 0) {
					console.log(`[WS] Unsubscribing from channel: ${channel}`);
					sendMessage(JSON.stringify({ action: "unsubscribe", channel }));
					subscriptions.current.delete(channel);
				}
			}
		},
		[sendMessage],
	);

	// Auth token sync is now handled by useAuth() and React re-rendering

	useEffect(() => {
		const currentUserId = user?.id;

		const isCurrentUserTopic = (topic: string, payload: unknown): boolean => {
			const topicUserId = getTopicUserId(topic);
			if (topicUserId !== null) {
				return currentUserId === topicUserId;
			}

			const payloadUserId =
				payload && typeof payload === "object"
					? Number((payload as Record<string, unknown>).user_id)
					: NaN;
			if (Number.isFinite(payloadUserId)) {
				return currentUserId === payloadUserId;
			}

			return !isUserScopedTopic(topic);
		};

		const appendLogEntry = (payload: unknown) => {
			queryClient.setQueryData(
				authScopedQueryKey("eventLog"),
				(oldData: LogEntry[] | undefined) => {
					const newLogEntry = payload as LogEntry;
					if (!newLogEntry.id)
						newLogEntry.id = `${newLogEntry.timestamp}-${Math.random()}`;
					const updatedLogs = oldData
						? [newLogEntry, ...oldData]
						: [newLogEntry];
					return updatedLogs.slice(0, 200);
				},
			);
		};

		if (lastMessage !== null) {
			try {
				const message = JSON.parse(lastMessage.data);
				const { topic, payload } = message;

				if (!isCurrentUserTopic(topic, payload)) {
					console.warn(
						`[WS] Ignoring user-scoped message outside current auth scope: ${topic}`,
					);
					return;
				}

				if (subscriptions.current.has(topic)) {
					subscriptions.current.get(topic)?.forEach((callback) => {
						try {
							callback(payload);
						} catch (e) {
							console.error(
								`Error in websocket callback for topic ${topic}`,
								e,
							);
						}
					});
					return;
				}

				// Handle user-scoped channels (channels with user_id suffix)
				// Pattern: depthsight:events:positions:{user_id}
				if (topic.startsWith("depthsight:events:portfolio:")) {
					queryClient.invalidateQueries({ queryKey: ["portfolioStatus"] });
				} else if (topic.startsWith("depthsight:events:strategies:")) {
					queryClient.invalidateQueries({ queryKey: ["strategies"] });
				} else if (topic.startsWith("depthsight:events:positions:")) {
					queryClient.invalidateQueries({ queryKey: ["positions"] });
				} else if (
					topic.startsWith("depthsight:events:log") ||
					topic.startsWith("user_logs:")
				) {
					appendLogEntry(payload);
				}
				// Legacy support for non-user-scoped channels (will be removed in future)
				switch (topic) {
					case "depthsight:events:portfolio":
						queryClient.invalidateQueries({ queryKey: ["portfolioStatus"] });
						break;
					case "depthsight:events:strategies":
						queryClient.invalidateQueries({ queryKey: ["strategies"] });
						break;
					case "depthsight:events:positions":
						queryClient.invalidateQueries({ queryKey: ["positions"] });
						break;
					case "depthsight:events:log":
						appendLogEntry(payload);
						break;
					default:
						break;
				}
			} catch (e) {
				console.error(
					"Failed to parse WebSocket message",
					e,
					"Data:",
					lastMessage.data,
				);
			}
		}
	}, [lastMessage, queryClient, user?.id]);

	return (
		<WebSocketContext.Provider value={{ readyState, subscribe, unsubscribe }}>
			{children}
		</WebSocketContext.Provider>
	);
};

/**
 * New hook providing full access to WebSocket, including subscribe/unsubscribe.
 */
export const useWebSocket = () => {
	const context = useContext(WebSocketContext);
	if (context === null) {
		throw new Error("useWebSocket must be used within a WebSocketProvider");
	}
	return context;
};

/**
 * Legacy hook for backward compatibility. Used by components
 * that only need the connection status.
 */
export const useWebSocketStatus = () => {
	const context = useContext(WebSocketContext);
	if (context === null) {
		throw new Error(
			"useWebSocketStatus must be used within a WebSocketProvider",
		);
	}
	return { readyState: context.readyState };
};
