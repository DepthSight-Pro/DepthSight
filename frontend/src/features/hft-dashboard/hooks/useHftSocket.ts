// src/features/hft-dashboard/hooks/useHftSocket.ts

import { useCallback, useEffect, useRef } from "react";
import { useAuth } from "../../../context/AuthContext";
import type {
	HftBotEvent,
	HftEquityUpdate,
	HftLogEvent,
	OracleSymbol,
} from "../types/hft.types";
import { useHftStore } from "./useHftStore";

const RECONNECT_INTERVAL = 3000;
const HFT_CHANNELS = [
	"hft:status",
	"hft:equity",
	"hft:oracle:symbols",
	"hft:oracle",
	"hft:events",
];

// Helper to convert Rust HftEvent to UI-friendly HftLogEvent
function mapRustEventToLog(event: HftBotEvent): HftLogEvent | null {
	const timestamp = Math.floor(Date.now() / 1000);
	const id = `${event.type}_${timestamp}_${Math.random().toString(36).substr(2, 9)}`;

	switch (event.type) {
		case "bot_started":
			return {
				id,
				timestamp,
				type: "INFO",
				message: `Bot started for user ${event.user_id}`,
				symbol: event.bot_id.split("_")[2] || undefined,
			};
		case "bot_stopped":
			return {
				id,
				timestamp,
				type: "INFO",
				message: `Bot ${event.bot_id} stopped`,
			};
		case "signal":
			return {
				id,
				timestamp,
				type: "INFO",
				message: `${event.side.toUpperCase()} signal @ ${event.price} (prob: ${(event.prob * 100).toFixed(1)}%)`,
				symbol: event.symbol,
			};
		case "trade": {
			const pnl = parseFloat(event.realized_pnl);
			return {
				id,
				timestamp,
				type: "TRADE",
				message: `${event.side.toUpperCase()} ${event.qty} @ ${event.price} | PnL: ${pnl >= 0 ? "+" : ""}${pnl.toFixed(2)} USDT`,
				symbol: event.symbol,
				meta: { leverage: event.leverage, realized_pnl: pnl },
			};
		}
		case "error":
			return {
				id,
				timestamp,
				type: "ERROR",
				message: event.message,
				symbol: event.bot_id.split("_")[2] || undefined,
			};
		case "status":
			// Status events update global state, not logs
			return null;
		case "heartbeat":
			// Heartbeats are handled separately in hft:status
			return null;
		case "log":
			return {
				id,
				timestamp,
				type: "INFO",
				message: event.message,
				symbol: event.bot_id.split("_")[2] || undefined,
			};
		default:
			return null;
	}
}

export const useHftSocket = () => {
	const socketRef = useRef<WebSocket | null>(null);
	const connectRef = useRef<() => void>(() => {});
	const {
		setConnectionStatus,
		updateStatus,
		addEquityPoint,
		setOracleSymbols,
		addLog,
	} = useHftStore();
	const { token: authToken } = useAuth();

	const connect = useCallback(() => {
		const token = authToken;

		if (!token) {
			console.error("No auth token found. Please log in.");
			return;
		}

		// Construct WS URL - assumes local or same-origin proxy
		const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
		const host = window.location.host;
		const wsUrl = import.meta.env.DEV
			? `ws://localhost:8765/ws?token=${token}`
			: `${protocol}//${host}/ws?token=${token}`;

		const ws = new WebSocket(wsUrl);

		ws.onopen = () => {
			console.log("HFT Socket Connected");
			setConnectionStatus(true);

			// Subscribe to channels
			HFT_CHANNELS.forEach((channel) => {
				ws.send(JSON.stringify({ action: "subscribe", channel }));
			});
		};

		ws.onmessage = (event) => {
			try {
				const data = JSON.parse(event.data);
				const { topic, payload } = data;

				switch (topic) {
					case "hft:status":
						// Heartbeat from Rust bot - update status
						if (payload.type === "heartbeat") {
							updateStatus({
								active_bots: payload.active_bots,
								engine_active: payload.active_bots > 0,
								latency_ms: payload.latency_ms,
								server_load_cpu: payload.cpu_usage,
								server_load_ram: payload.ram_usage,
							});
						} else if (payload.type === "status") {
							// Bot status update
							updateStatus({ engine_active: true });
						}
						break;
					case "hft:equity":
						addEquityPoint(payload as HftEquityUpdate);
						break;
					case "hft:oracle:symbols":
						setOracleSymbols(payload as OracleSymbol[]);
						break;
					case "hft:oracle":
						// This handles global regime commands if any, usually internal to bot
						break;
					case "hft:events": {
						// Map Rust HftEvent to HftLogEvent
						const logEvent = mapRustEventToLog(payload);
						if (logEvent) {
							addLog(logEvent);
						}
						break;
					}
					default:
						// console.log("Unknown topic:", topic);
						break;
				}
			} catch (e) {
				console.error("Error parsing WS message:", e);
			}
		};

		ws.onclose = () => {
			console.log("HFT Socket Disconnected");
			setConnectionStatus(false);
			socketRef.current = null;
			setTimeout(() => connectRef.current(), RECONNECT_INTERVAL);
		};

		ws.onerror = (err) => {
			// Only log errors if the socket is not being intentionally closed
			if (
				ws.readyState !== WebSocket.CLOSED &&
				ws.readyState !== WebSocket.CLOSING
			) {
				console.error("HFT Socket Error:", err);
			}
			ws.close();
		};

		socketRef.current = ws;
	}, [
		authToken,
		setConnectionStatus,
		updateStatus,
		addEquityPoint,
		setOracleSymbols,
		addLog,
	]);

	useEffect(() => {
		connectRef.current = connect;
	}, [connect]);

	useEffect(() => {
		connect();
		return () => {
			if (socketRef.current) {
				socketRef.current.close();
			}
		};
	}, [connect]);
};
