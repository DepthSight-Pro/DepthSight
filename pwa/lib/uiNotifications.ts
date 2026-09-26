// pwa/lib/uiNotifications.ts
//
// Mapper for structured trading notifications published by the backend
// (bot_module/ui_notifier.py) to Redis channel `user:{user_id}:notifications`.
// Payload contract: {id, type, severity, title, body, symbol, side, ts_ms,
// user_id, api_key_id, tag, data}. Foreign events on the same channel
// (e.g. gene_discovered) are ignored.

import type {
	AppNotificationSeverity,
	AppNotificationType,
} from "../contexts/NotificationContext";

export interface UiNotificationPayload {
	id: string;
	type: string;
	severity: AppNotificationSeverity;
	title: string;
	body: string;
	symbol: string | null;
	side: string | null;
	ts_ms: number;
	user_id: number;
	tag: string;
}

export interface MappedUiNotification {
	type: AppNotificationType;
	title: string;
	subtitle: string;
	icon: string;
	bgColor: string;
	severity: AppNotificationSeverity;
	navigationData?: {
		screen?: string;
		params?: Record<string, unknown>;
	};
}

const KNOWN_TYPES: ReadonlySet<string> = new Set([
	"position_opened",
	"position_closed",
	"partial_tp",
	"scale_in",
	"sl_moved",
	"risk_alert",
	"order_error",
	"blacklist",
	"bot_error",
	"hft_signal",
	"hft_trade",
	"hft_closed",
	"hft_info",
	"info",
]);

const KNOWN_SEVERITIES: ReadonlySet<string> = new Set([
	"info",
	"success",
	"warning",
	"error",
]);

const asString = (value: unknown): string | null =>
	typeof value === "string" ? value : null;

export function isUiNotificationPayload(
	value: unknown,
): value is UiNotificationPayload {
	if (typeof value !== "object" || value === null) return false;
	const v = value as Record<string, unknown>;
	return (
		typeof v.id === "string" &&
		typeof v.type === "string" &&
		KNOWN_TYPES.has(v.type) &&
		typeof v.title === "string" &&
		typeof v.ts_ms === "number"
	);
}

function normalizeSeverity(value: unknown): AppNotificationSeverity {
	return typeof value === "string" && KNOWN_SEVERITIES.has(value)
		? (value as AppNotificationSeverity)
		: "info";
}

const STRATEGIES_NAV = { screen: "Strategies" as const };

export function mapUiNotification(
	payload: UiNotificationPayload,
): MappedUiNotification {
	const severity = normalizeSeverity(payload.severity);
	const title = payload.title || "DepthSight";
	const subtitle = asString(payload.body) ?? "";
	const symbolSuffix = payload.symbol ? ` · ${payload.symbol}` : "";

	switch (payload.type) {
		case "position_opened":
			return {
				type: "position_opened",
				title,
				subtitle,
				icon: "🚀",
				bgColor: "bg-blue-500",
				severity,
				navigationData: STRATEGIES_NAV,
			};
		case "position_closed":
			return {
				type: "position_closed",
				title,
				subtitle,
				icon: severity === "success" ? "💰" : severity === "error" ? "📉" : "⚖️",
				bgColor:
					severity === "success"
						? "bg-green-500"
						: severity === "error"
							? "bg-red-500"
							: "bg-slate-500",
				severity,
				navigationData: STRATEGIES_NAV,
			};
		case "partial_tp":
			return {
				type: "partial_tp",
				title,
				subtitle,
				icon: "🎯",
				bgColor: "bg-emerald-500",
				severity,
				navigationData: STRATEGIES_NAV,
			};
		case "sl_moved":
			return {
				type: "sl_moved",
				title,
				subtitle,
				icon: "🛡️",
				bgColor: "bg-sky-500",
				severity,
				navigationData: STRATEGIES_NAV,
			};
		case "scale_in":
			return {
				type: "scale_in",
				title,
				subtitle,
				icon: "➕",
				bgColor: "bg-indigo-500",
				severity,
				navigationData: STRATEGIES_NAV,
			};
		case "risk_alert":
			return {
				type: "risk_alert",
				title,
				subtitle,
				icon: severity === "error" ? "🛑" : "⚠️",
				bgColor: severity === "error" ? "bg-red-600" : "bg-amber-500",
				severity,
			};
		case "order_error":
			return {
				type: "order_error",
				title,
				subtitle,
				icon: "❌",
				bgColor: "bg-red-500",
				severity,
			};
		case "blacklist":
			return {
				type: "blacklist",
				title,
				subtitle,
				icon: "🚫",
				bgColor: "bg-orange-500",
				severity,
			};
		case "bot_error":
			return {
				type: "bot_error",
				title,
				subtitle,
				icon: "🆘",
				bgColor: "bg-red-600",
				severity,
			};
		case "hft_signal":
			return {
				type: "hft_signal",
				title,
				subtitle,
				icon: "⚡",
				bgColor: "bg-violet-500",
				severity,
			};
		case "hft_trade":
			return {
				type: "hft_trade",
				title,
				subtitle,
				icon: "💸",
				bgColor: "bg-blue-500",
				severity,
			};
		case "hft_closed":
			return {
				type: "hft_closed",
				title,
				subtitle,
				icon: severity === "success" ? "💰" : severity === "error" ? "📉" : "⚖️",
				bgColor:
					severity === "success"
						? "bg-green-500"
						: severity === "error"
							? "bg-red-500"
							: "bg-slate-500",
				severity,
			};
		case "hft_info":
			return {
				type: "hft_info",
				title,
				subtitle,
				icon: "ℹ️",
				bgColor: "bg-slate-500",
				severity,
			};
		default:
			return {
				type: "info",
				title: title + symbolSuffix,
				subtitle,
				icon: "🔔",
				bgColor: "bg-[hsl(var(--secondary))]",
				severity,
			};
	}
}
