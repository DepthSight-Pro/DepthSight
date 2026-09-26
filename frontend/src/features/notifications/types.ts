// src/features/notifications/types.ts
//
// Contract mirror of bot_module/ui_notifier.py payload.
// The backend publishes these to Redis channel `user:{user_id}:notifications`.

export type UiNotificationType =
	| "position_opened"
	| "position_closed"
	| "partial_tp"
	| "scale_in"
	| "sl_moved"
	| "risk_alert"
	| "order_error"
	| "blacklist"
	| "bot_error"
	| "hft_signal"
	| "hft_trade"
	| "hft_closed"
	| "hft_info"
	| "info";

export type UiNotificationSeverity = "info" | "success" | "warning" | "error";

export interface UiNotificationPayload {
	id: string;
	type: string;
	severity: UiNotificationSeverity;
	title: string;
	body: string;
	symbol: string | null;
	side: string | null;
	ts_ms: number;
	user_id: number;
	api_key_id: number | null;
	tag: string;
	data: Record<string, string>;
}

export interface UiNotification extends UiNotificationPayload {
	type: UiNotificationType;
	read: boolean;
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

/** Narrows unknown WS payloads; rejects gene_discovered and other foreign events. */
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
		typeof v.body === "string" &&
		typeof v.ts_ms === "number" &&
		(typeof v.severity !== "string" || KNOWN_SEVERITIES.has(v.severity))
	);
}

export function normalizeSeverity(
	severity: unknown,
): UiNotificationSeverity {
	return typeof severity === "string" &&
		KNOWN_SEVERITIES.has(severity)
		? (severity as UiNotificationSeverity)
		: "info";
}
