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
	/^depthsight:events:trades:(\d+)$/,
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
	topic.startsWith("depthsight:events:trades") ||
	topic.startsWith("depthsight:events:log");

const getSocketUrl = (token: string | null, reconnectKey = 0) => {
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

	// Add the token to the final URL.
	// `reconnectKey` is intentionally part of the URL so manual reconnects
	// produce a new value and force `react-use-websocket` to reconnect.
	const separator = finalUrl.includes("?") ? "&" : "?";
	return `${finalUrl}${separator}token=${encodeURIComponent(token)}&_r=${reconnectKey}`;
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
	const lastSeq = useRef<Record<string, number>>({});
	const lastPortfolioByKey = useRef<
		Record<
			string,
			{ equity: number; wallet: number; unrealized: number; today: number }
		>
	>({});

	// Synchronize when authToken from useAuth() updates.
	// Adjusted during render (not in an effect) to avoid cascading renders.
	if (authToken && authToken !== currentToken) {
		setCurrentToken(authToken);
	}

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
		return getSocketUrl(tokenToUse, reconnectKey);
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

		// Stale-drop for out-of-order push snapshots (reconnect/resubscribe).
		// Seq is per-controller, so scope by api_key_id for multi-account.
		const isFresh = (key: string, seq: unknown, apiKey?: unknown): boolean => {
			const n = typeof seq === "number" ? seq : Number(seq);
			if (!Number.isFinite(n)) return true; // legacy payload without seq
			const scope =
				apiKey === null || apiKey === undefined
					? key
					: `${key}:${String(apiKey)}`;
			if ((lastSeq.current[scope] ?? -1) > n) return false;
			lastSeq.current[scope] = n;
			return true;
		};

		interface PushPayload {
			user_id?: number;
			api_key_id?: number | null;
			seq?: number;
			data?: unknown;
		}

		const normMode = (m: unknown): string => String(m ?? "").toLowerCase();

		/**
		 * Push snapshots are per-controller (user + api_key), while list queries
		 * may aggregate several accounts ("all"). Merge by api_key_id instead of
		 * replacing, otherwise one account's snapshot wipes the others.
		 *
		 * Snapshots may be truncated (backend sends core fields only, heavy
		 * traces stay in the REST state keys). Rows are therefore merged
		 * per identity, so fields missing from the push — `executions`,
		 * `signal_details_json`, `partial_tp_orders`, `dca_orders` — keep the
		 * values loaded via REST. Without this the live deal chart loses the
		 * limit/partial order rails after the first push (~8 s).
		 */
		const rowIdentity = (row: Record<string, unknown>): string => {
			const id = row.id ?? row.__id;
			if (id !== null && id !== undefined && String(id) !== "") {
				return `id:${String(id)}`;
			}
			// Positions without a client order id fall back to their
			// book-keeping key: symbol + account + mode.
			return `sym:${String(row.symbol ?? "")}|${String(
				row.api_key_id ?? "",
			)}|${normMode(row.mode)}`;
		};

		const mergeListPush = <T extends Record<string, unknown>>(
			rootKey: string,
			queryModeIndex: number,
			queryApiKeyIndex: number,
			payload: PushPayload,
			rows: T[],
		): void => {
			const apiKey =
				payload.api_key_id === null || payload.api_key_id === undefined
					? null
					: Number(payload.api_key_id);
			const cache = queryClient.getQueryCache();
			const queries = cache.findAll({ queryKey: [rootKey] });
			if (queries.length === 0) {
				queryClient.setQueryData(authScopedQueryKey(rootKey), rows);
				return;
			}
			for (const q of queries) {
				const key = q.queryKey as unknown[];
				const qMode = key[queryModeIndex] as string | undefined;
				const qApiKey = key[queryApiKeyIndex] as number | "all" | undefined;
				// A single-account query shows only its own controller data.
				if (
					typeof qApiKey === "number" &&
					apiKey !== null &&
					Number(qApiKey) !== apiKey
				) {
					continue;
				}
				let incoming = rows;
				if (qMode) {
					const filtered = rows.filter(
						(r) => !r.mode || normMode(r.mode) === normMode(qMode),
					);
					// Never wipe on mode mismatch — keep payload as-is.
					if (filtered.length > 0 || rows.length === 0) incoming = filtered;
				}
				queryClient.setQueryData(key as readonly unknown[], (old: unknown) => {
					if (!Array.isArray(old)) return incoming;
					const oldRows = old as T[];
					const cachedByIdentity = new Map<string, T>();
					for (const row of oldRows) {
						cachedByIdentity.set(rowIdentity(row), row);
					}
					// Fresh push values win, but cached-only fields survive
					// (closed positions simply disappear from `incoming`).
					const merged = incoming.map((row) => {
						const cachedRow = cachedByIdentity.get(rowIdentity(row));
						return cachedRow ? { ...cachedRow, ...row } : row;
					});
					if (apiKey === null)
						// Unknown controller scope: never wipe on empty snapshots.
						return incoming.length === 0 ? oldRows : merged;
					// Drop only this controller's rows IN THE SAME MODE bucket:
					// a paper-controller push must not wipe live rows of the
					// same account (and vice versa).
					const rest = oldRows.filter((o) => {
						if (Number(o.api_key_id) !== apiKey) return true;
						const om = (o as Record<string, unknown>).mode;
						if (om === null || om === undefined || !qMode) return false;
						return normMode(om) !== normMode(qMode);
					});
					return [...rest, ...merged];
				});
			}
		};

		const applyPositionsPush = (payload: unknown) => {
			const p = payload as PushPayload;
			if (!isFresh("positions", p?.seq, p?.api_key_id)) return;
			if (!Array.isArray(p?.data)) {
				queryClient.invalidateQueries({ queryKey: ["positions"] });
				return;
			}
			// ["positions", authScope, mode, apiKeyId, marketType]
			mergeListPush("positions", 2, 3, p, p.data as Record<string, unknown>[]);
		};

		const applyStrategiesPush = (payload: unknown) => {
			const p = payload as PushPayload;
			if (!isFresh("strategies", p?.seq, p?.api_key_id)) return;
			if (!Array.isArray(p?.data)) {
				queryClient.invalidateQueries({ queryKey: ["strategies"] });
				return;
			}
			const mapped = (p.data as Array<Record<string, unknown>>).map((s) => ({
				...s,
				name: (s.name ?? s.strategy_name ?? "") as string,
			}));
			// ["strategies", authScope, mode, apiKeyId]
			mergeListPush("strategies", 2, 3, p, mapped);
		};

		// Per-controller portfolio numbers for "all accounts" aggregation.
		const portfolioStore = lastPortfolioByKey.current;

		const applyPortfolioPush = (payload: unknown) => {
			const p = payload as PushPayload;
			if (!isFresh("portfolio", p?.seq, p?.api_key_id)) return;
			const d = p?.data as Record<string, unknown> | undefined;
			if (!d || typeof d !== "object") {
				queryClient.invalidateQueries({ queryKey: ["portfolioStatus"] });
				return;
			}
			const numbers = {
				equity: Number(d.total_equity ?? d.total_wallet_balance ?? 0),
				wallet: Number(d.total_wallet_balance ?? 0),
				unrealized: Number(d.total_unrealized_pnl ?? 0),
				today: Number(d.today_pnl ?? 0),
			};
			const apiKey =
				p.api_key_id === null || p.api_key_id === undefined
					? null
					: String(p.api_key_id);
			if (apiKey !== null) portfolioStore[apiKey] = numbers;
			const toMapped = (n: typeof numbers) => ({
				balance: n.equity,
				today_pnl: n.today,
				is_trading_allowed: (d.is_trading_allowed as boolean) ?? true,
				consecutive_losses: Number(d.consecutive_losses ?? 0),
				timestamp_utc: (d.updated_at as string) ?? new Date().toISOString(),
				total_unrealized_pnl: n.unrealized,
				totalUnrealizedPnl: n.unrealized,
			});
			// ["portfolioStatus", authScope, mode, apiKeyId, marketType]
			const queries = queryClient
				.getQueryCache()
				.findAll({ queryKey: ["portfolioStatus"] });
			if (queries.length === 0) {
				queryClient.setQueryData(
					authScopedQueryKey("portfolioStatus"),
					toMapped(numbers),
				);
				return;
			}
			for (const q of queries) {
				const key = q.queryKey as unknown[];
				const qApiKey = key[3] as number | "all" | undefined;
				let n = numbers;
				if (
					(qApiKey === "all" || qApiKey === undefined) &&
					apiKey !== null &&
					Object.keys(portfolioStore).length > 0
				) {
					// Aggregated view: sum across known controllers.
					n = Object.values(portfolioStore).reduce(
						(acc, v) => ({
							equity: acc.equity + v.equity,
							wallet: acc.wallet + v.wallet,
							unrealized: acc.unrealized + v.unrealized,
							today: acc.today + v.today,
						}),
						{ equity: 0, wallet: 0, unrealized: 0, today: 0 },
					);
				} else if (
					typeof qApiKey === "number" &&
					apiKey !== null &&
					Number(qApiKey) !== Number(apiKey)
				) {
					continue; // another account's query
				}
				const mapped = toMapped(n);
				queryClient.setQueryData(
					key as readonly unknown[],
					(old: unknown) => ({
						...((old as Record<string, unknown>) ?? {}),
						...mapped,
					}),
				);
			}
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

				// Global push handling runs first so caches stay fresh even when
				// a component also listens on the same topic (no early return).
				if (topic.startsWith("depthsight:events:portfolio:")) {
					applyPortfolioPush(payload);
				} else if (topic.startsWith("depthsight:events:strategies:")) {
					applyStrategiesPush(payload);
				} else if (topic.startsWith("depthsight:events:positions:")) {
					applyPositionsPush(payload);
				} else if (topic.startsWith("depthsight:events:trades:")) {
					queryClient.invalidateQueries({ queryKey: ["tradeHistory"] });
					queryClient.invalidateQueries({ queryKey: ["portfolioEquity"] });
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

	// Engine push channels live for the whole session. The WS server forwards
	// ONLY subscribed topics, so without this nothing would ever arrive.
	// Cache updates happen in the global message handler above; the callback
	// is a noop placeholder.
	const noopPushCallback = useCallback(() => {}, []);
	useEffect(() => {
		if (!user?.id) return;
		const channels = [
			`depthsight:events:positions:${user.id}`,
			`depthsight:events:strategies:${user.id}`,
			`depthsight:events:portfolio:${user.id}`,
			`depthsight:events:trades:${user.id}`,
		];
		channels.forEach((c) => subscribe(c, noopPushCallback));
		return () => {
			channels.forEach((c) => unsubscribe(c, noopPushCallback));
		};
	}, [user?.id, subscribe, unsubscribe, noopPushCallback]);

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
