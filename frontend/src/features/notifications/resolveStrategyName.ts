// src/features/notifications/resolveStrategyName.ts
//
// Resolves the user-defined strategy config name for a notification,
// the same way the "Best strategies" card on the dashboard does
// (config_id -> saved config name). Falls back to the system name
// carried in the payload when nothing matches.

import type { StrategyData } from "@/types/api";
import type { UiNotification } from "./types";

const SYSTEM_NAMES: ReadonlySet<string> = new Set([
	"VisualBuilderStrategy",
	"VisualBuilder",
]);

export function buildNameByConfigId(
	configs: Array<{ id: unknown; name: unknown }> | undefined,
): Map<string, string> {
	const m = new Map<string, string>();
	for (const c of configs ?? []) {
		if (c.id && c.name) m.set(String(c.id), String(c.name));
	}
	return m;
}

function coversSymbol(s: StrategyData, symbol: string): boolean {
	if ((s.symbol_selection_mode || "STATIC").toUpperCase() === "DYNAMIC") {
		return true;
	}
	if (Array.isArray(s.symbols)) {
		for (const item of s.symbols) {
			if (String(item).toUpperCase() === symbol) return true;
		}
	}
	// Snapshot `symbol` may be a single symbol or a comma-joined list.
	for (const part of String(s.symbol || "").split(",")) {
		if (part.trim().toUpperCase() === symbol) return true;
	}
	return false;
}

function sameAccount(
	strategyApiKey: number | null | undefined,
	notificationApiKey: number | null | undefined,
): boolean {
	if (strategyApiKey == null || notificationApiKey == null) return true;
	return Number(strategyApiKey) === Number(notificationApiKey);
}

/** Custom config name for the notification's strategy, or null. */
export function resolveStrategyDisplayName(
	notification: Pick<UiNotification, "symbol" | "api_key_id" | "data">,
	strategies: StrategyData[],
	nameByConfigId: Map<string, string>,
): string | null {
	const symbol = (notification.symbol || "").toUpperCase();
	if (!symbol) return null;
	const pool = strategies.filter((s) =>
		sameAccount(
			s.api_key_id ?? s.apiKeyId ?? null,
			notification.api_key_id,
		),
	);
	// Prefer STATIC exact-symbol matches over DYNAMIC catch-alls.
	const isStatic = (s: StrategyData) =>
		(s.symbol_selection_mode || "STATIC").toUpperCase() !== "DYNAMIC";
	const statics = pool.filter((s) => isStatic(s) && coversSymbol(s, symbol));
	const scoped =
		statics.length > 0
			? statics
			: pool.filter((s) => coversSymbol(s, symbol));
	for (const s of scoped) {
		const configId = s.config_id ?? s.id;
		if (!configId) continue;
		const custom = nameByConfigId.get(String(configId));
		if (custom && !SYSTEM_NAMES.has(custom)) return custom;
	}
	return null;
}

function escapeRegExp(text: string): string {
	return text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

/** Swaps the system strategy name in title/body for the custom one. */
export function applyStrategyDisplayName(
	title: string,
	body: string,
	systemName: string | null | undefined,
	displayName: string | null,
): { title: string; body: string } {
	if (!displayName || !systemName || displayName === systemName) {
		return { title, body };
	}
	const re = new RegExp(escapeRegExp(systemName), "g");
	return { title: title.replace(re, displayName), body: body.replace(re, displayName) };
}
