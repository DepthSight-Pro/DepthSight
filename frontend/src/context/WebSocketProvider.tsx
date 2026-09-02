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
	useState,
} from "react";
import useBaseWebSocket, { ReadyState } from "react-use-websocket";
import { authScopedQueryKey } from "@/lib/queryKeys";
import { refreshAuthToken } from "@/lib/apiClient";
import type { LogEntry } from "@/types/api";
import { useAuth } from "./AuthContext";

// --- Types for dynamic subscriptions ---
type WebSocketCallback = (payload: unknown) => void;
type SubscriptionMap = Map<string, Set<WebSocketCallback>>;

interface WebSocketContextType {
	readyState: ReadyState;
	subscribe: (channel: string, callback: WebSocketCallback) => void;
	unsubscribe: (channel: string, callback: WebSocketCallback) => void;
	reconnect: () => Promise<void>;
}

const WebSocketContext = createContext<WebSocketContextType | null>(null);

const isTokenExpired = (token: string | null): boolean => {
	if (!token) return true;
	try {
		const parts = token.split(".");
		if (parts.length !== 3) return false;
		const payload = JSON.parse(atob(parts[1]));
		if (!payload.exp) return false;
		return Date.now() >= payload.exp * 1000 - 60000;
	} catch {
		return false;
	}
};

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

	const [currentToken, setCurrentToken] = useState<string | null>(() => {
		return (
			authToken ||
			(typeof window !== "undefined"
				? localStorage.getItem("authToken")
				: null)
		);
	});
	const [reconnectKey, setReconnectKey] = useState<number>(0);
	const isHandlingAuthClose = useRef<boolean>(false);

	// Synchronize when authToken from useAuth() updates
	useEffect(() => {
		if (authToken && authToken !== currentToken) {
			setCurrentToken(authToken);
		}
	}, [authToken, currentToken]);

	// Listen for auth:token-refreshed event across the app
	useEffect(() => {
		const handleTokenRefreshed = (e: Event) => {
			const customEvent = e as CustomEvent<{ token: string }>;
			if (customEvent.detail?.token) {
				setCurrentToken(customEvent.detail.token);
			}
		};
		window.addEventListener("auth:token-refreshed", handleTokenRefreshed);
		return () => {
			window.removeEventListener("auth:token-refreshed", handleTokenRefreshed);
		};
	}, []);

	// Proactive reconnect function (also callable manually or on auth failure)
	const reconnect = useCallback(async () => {
		console.log("[WS] Reconnecting WebSocket...");
		const latestToken = localStorage.getItem("authToken");
		if (isTokenExpired(latestToken)) {
			console.log("[WS] Token expired or invalid, refreshing before reconnect...");
			const newToken = await refreshAuthToken();
			if (newToken) {
				setCurrentToken(newToken);
			}
		} else if (latestToken && latestToken !== currentToken) {
			setCurrentToken(latestToken);
		}
		setReconnectKey((k) => k + 1);
	}, [currentToken]);

	// Re-check token before building URL
	const socketUrl = useMemo(() => {
		const tokenToUse = currentToken || localStorage.getItem("authToken");
		return getSocketUrl(tokenToUse);
	}, [currentToken, reconnectKey]);

	const { lastMessage, readyState, sendMessage } = useBaseWebSocket(
		socketUrl,
		{
			shouldReconnect: () => true,
			reconnectInterval: 3000,
			retryOnError: true,
			onOpen: () => {
				console.log("[WS] Connection established, restoring active subscriptions...");
				isHandlingAuthClose.current = false;
				// Resubscribe to all active channels
				subscriptions.current.forEach((callbacks, channel) => {
					if (callbacks.size > 0) {
						console.log(`[WS] Resubscribing to channel: ${channel}`);
						sendMessage(JSON.stringify({ action: "subscribe", channel }));
					}
				});
			},
			onClose: async (event) => {
				console.warn(`[WS] Connection closed with code: ${event.code}`);
				// Code 1008 is WS_1008_POLICY_VIOLATION, thrown on token expiration/invalid credentials
				if ((event.code === 1008 || event.code === 4401) && !isHandlingAuthClose.current) {
					isHandlingAuthClose.current = true;
					console.log("[WS] Auth error code 1008 received. Refreshing token...");
					const freshToken = await refreshAuthToken();
					if (freshToken) {
						setCurrentToken(freshToken);
						setReconnectKey((k) => k + 1);
					}
				}
			},
		},
		!!socketUrl,
	);

	// Heartbeat ping every 25 seconds to keep connection alive through Caddy/proxies
	useEffect(() => {
		if (readyState !== ReadyState.OPEN) return;

		const interval = setInterval(() => {
			try {
				sendMessage(JSON.stringify({ action: "ping" }));
			} catch (e) {
				console.warn("[WS] Error sending ping heartbeat:", e);
			}
		}, 25000);

		return () => clearInterval(interval);
	}, [readyState, sendMessage]);

	// Tab visibility and online network recovery
	useEffect(() => {
		const handleVisibilityOrOnline = async () => {
			if (document.visibilityState === "visible") {
				const token = localStorage.getItem("authToken");
				if (isTokenExpired(token)) {
					console.log("[WS] Tab returned and token expired, refreshing token...");
					const newToken = await refreshAuthToken();
					if (newToken) {
						setCurrentToken(newToken);
						setReconnectKey((k) => k + 1);
						return;
					}
				}
				if (readyState === ReadyState.CLOSED || readyState === ReadyState.UNINSTANTIATED) {
					console.log("[WS] Tab returned and socket is closed, attempting reconnect...");
					reconnect();
				}
			}
		};

		document.addEventListener("visibilitychange", handleVisibilityOrOnline);
		window.addEventListener("online", handleVisibilityOrOnline);
		return () => {
			document.removeEventListener("visibilitychange", handleVisibilityOrOnline);
			window.removeEventListener("online", handleVisibilityOrOnline);
		};
	}, [readyState, reconnect]);

	const subscribe = useCallback(
		(channel: string, callback: WebSocketCallback) => {
			if (!subscriptions.current.has(channel)) {
				subscriptions.current.set(channel, new Set());
				if (readyState === ReadyState.OPEN) {
					console.log(`[WS] Subscribing to channel: ${channel}`);
					sendMessage(JSON.stringify({ action: "subscribe", channel }));
				}
			}
			subscriptions.current.get(channel)?.add(callback);
		},
		[readyState, sendMessage],
	);

	const unsubscribe = useCallback(
		(channel: string, callback: WebSocketCallback) => {
			if (subscriptions.current.has(channel)) {
				const channelCallbacks = subscriptions.current.get(channel)!;
				channelCallbacks.delete(callback);

				if (channelCallbacks.size === 0) {
					console.log(`[WS] Unsubscribing from channel: ${channel}`);
					if (readyState === ReadyState.OPEN) {
						sendMessage(JSON.stringify({ action: "unsubscribe", channel }));
					}
					subscriptions.current.delete(channel);
				}
			}
		},
		[readyState, sendMessage],
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
				if (message && message.action === "pong") {
					return;
				}
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
		<WebSocketContext.Provider
			value={{ readyState, subscribe, unsubscribe, reconnect }}
		>
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
	return { readyState: context.readyState, reconnect: context.reconnect };
};
