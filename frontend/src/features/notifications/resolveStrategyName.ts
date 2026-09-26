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
	"Quant Engine",
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
		if (configId) {
			const custom = nameByConfigId.get(String(configId));
			if (custom && !SYSTEM_NAMES.has(custom)) return custom;
		}
		if (s.name && !SYSTEM_NAMES.has(s.name) && s.name !== s.strategy_name) {
			return s.name;
		}
		if (s.name && !SYSTEM_NAMES.has(s.name)) {
			return s.name;
		}
	}
	return null;
}

/** Custom config name for an active position, or fallback to custom/system name. */
export function resolvePositionStrategyName(
	position: {
		symbol?: string | null;
		api_key_id?: number | string | null;
		config_id?: string | null;
		strategy?: string | null;
		strategy_name?: string | null;
	},
	strategies: StrategyData[] | undefined,
	nameByConfigId: Map<string, string>,
): string {
	if (position.config_id && nameByConfigId.get(String(position.config_id))) {
		const custom = nameByConfigId.get(String(position.config_id));
		if (custom && !SYSTEM_NAMES.has(custom)) return custom;
	}

	const symbol = (position.symbol || "").toUpperCase();
	if (symbol && strategies && strategies.length > 0) {
		const targetApiKey =
			position.api_key_id != null && position.api_key_id !== ""
				? Number(position.api_key_id)
				: null;
		const pool = strategies.filter((s) =>
			sameAccount(s.api_key_id ?? s.apiKeyId ?? null, targetApiKey),
		);
		const statics = pool.filter(
			(s) =>
				(s.symbol_selection_mode || "STATIC").toUpperCase() !== "DYNAMIC" &&
				coversSymbol(s, symbol),
		);
		const scoped =
			statics.length > 0
				? statics
				: pool.filter((s) => coversSymbol(s, symbol));
		for (const s of scoped) {
			const configId = s.config_id ?? s.id;
			if (configId) {
				const custom = nameByConfigId.get(String(configId));
				if (custom && !SYSTEM_NAMES.has(custom)) return custom;
			}
			if (s.name && !SYSTEM_NAMES.has(s.name) && s.name !== s.strategy_name) {
				return s.name;
			}
			if (s.name && !SYSTEM_NAMES.has(s.name)) {
				return s.name;
			}
		}
	}

	if (position.strategy_name && !SYSTEM_NAMES.has(position.strategy_name)) {
		return position.strategy_name;
	}
	if (position.strategy && !SYSTEM_NAMES.has(position.strategy)) {
		return position.strategy;
	}
	return position.strategy_name || position.strategy || "Quant Engine";
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
