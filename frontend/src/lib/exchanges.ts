// src/lib/exchanges.ts
//
// Exchange display metadata (labels, brand colors, glyphs).
// Moved here from the removed dashboardMock module — no mock data.

import binanceLogo from "@/content/logos/binance.svg";
import bingxLogo from "@/content/logos/bingx.svg";
import bitgetLogo from "@/content/logos/bitget.svg";
import bybitLogo from "@/content/logos/bybit.svg";
import gateLogo from "@/content/logos/gate.svg";
import hyperliquidLogo from "@/content/logos/hyperliquid.svg";
import okxLogo from "@/content/logos/okx.svg";
import weexLogo from "@/content/logos/weex.svg";

export type Exchange =
	| "binance"
	| "bybit"
	| "okx"
	| "bitget"
	| "weex"
	| "gate"
	| "bingx"
	| "hyperliquid";

export const exchangeMeta: Record<
	string,
	{ label: string; color: string; glyph: string }
> = {
	binance: { label: "Binance", color: "#F0B90B", glyph: "◆" },
	bybit: { label: "Bybit", color: "#F7A600", glyph: "▲" },
	okx: { label: "OKX", color: "#FFFFFF", glyph: "●" },
	bitget: { label: "Bitget", color: "#00F0FF", glyph: "■" },
	weex: { label: "WEEX", color: "#7C3AED", glyph: "⬣" },
	gate: { label: "Gate.io", color: "#3B82F6", glyph: "⬢" },
	bingx: { label: "BingX", color: "#06B6D4", glyph: "⬔" },
	hyperliquid: { label: "Hyperliquid", color: "#00D28E", glyph: "≋" },
};

/** Logo asset per exchange id (used by ExchangeBadge and account lists). */
export const exchangeLogos: Record<string, string> = {
	binance: binanceLogo,
	bybit: bybitLogo,
	okx: okxLogo,
	bitget: bitgetLogo,
	gate: gateLogo,
	bingx: bingxLogo,
	weex: weexLogo,
	hyperliquid: hyperliquidLogo,
};

/** Human-readable display name per exchange id. */
export const exchangeLabels: Record<string, string> = {
	binance: "Binance",
	bybit: "Bybit",
	okx: "OKX",
	bitget: "Bitget",
	gate: "Gate.io",
	bingx: "BingX",
	weex: "WEEX",
	hyperliquid: "Hyperliquid",
};

/**
 * Normalizes position/strategy/apiKey exchange names
 * ("bitget_futures", "Bybit_Testnet", "WEEX_USDTM"...) down to a base id.
 * Returns null for unknown/empty so callers can render "?" instead of
 * silently falling back to Binance.
 */
export function normalizeExchangeKey(
	exchange?: string | null,
): string | null {
	if (!exchange) return null;
	let raw = String(exchange).trim().toLowerCase();
	if (!raw) return null;
	raw = raw.replace(/_testnet$/, "");
	for (const suffix of [
		"_futures",
		"_usdtm",
		"_usdm",
		"_linear",
		"_swap",
		"_spot",
	]) {
		if (raw.endsWith(suffix)) {
			raw = raw.slice(0, -suffix.length);
			break;
		}
	}
	if (raw === "gateio" || raw === "gate_io") return "gate";
	if (raw === "hl") return "hyperliquid";
	if (
		raw === "binance" ||
		raw === "bybit" ||
		raw === "okx" ||
		raw === "bitget" ||
		raw === "weex" ||
		raw === "gate" ||
		raw === "bingx" ||
		raw === "hyperliquid"
	) {
		return raw;
	}
	return null;
}

/**
 * Returns true if the exchange uses a unified wallet/balance where
 * spot and futures accounts share the same equity/collateral pool
 * (e.g. Bybit UTA, OKX unified account, Hyperliquid L1 account).
 */
export function isUnifiedAccountExchange(exchange?: string | null): boolean {
	const norm = normalizeExchangeKey(exchange);
	return norm === "bybit" || norm === "okx" || norm === "hyperliquid";
}

/**
 * Exchanges that actively support trade mining with verified rebates/volume.
 * Note: Binance is trade-only (no mining). Hyperliquid is not activated for mining yet.
 */
export const activeMiningExchanges = ["bybit", "okx", "weex", "bitget"];

/**
 * Returns a formatted comma-separated list of active mining exchange labels
 * for multi-exchange campaigns (e.g. "Bybit, OKX, WEEX, Bitget").
 * Excludes Binance (trade only) and Hyperliquid (not yet activated for mining).
 */
export function getActiveExchangesList(eligible?: string[]): string {
	const priority = activeMiningExchanges;
	const set = new Set<string>();
	if (eligible && eligible.length > 0) {
		for (const ex of eligible) {
			const norm = normalizeExchangeKey(ex) || ex.toLowerCase();
			if (
				norm &&
				norm !== "all" &&
				norm !== "binance" &&
				norm !== "hyperliquid" &&
				norm !== "hl"
			) {
				set.add(norm);
			}
		}
	}
	if (set.size === 0) {
		for (const p of priority) set.add(p);
	}
	const sorted = Array.from(set).sort((a, b) => {
		const ia = priority.indexOf(a);
		const ib = priority.indexOf(b);
		if (ia !== -1 && ib !== -1) return ia - ib;
		if (ia !== -1) return -1;
		if (ib !== -1) return 1;
		return a.localeCompare(b);
	});
	return sorted
		.map((k) => exchangeLabels[k] || k.toUpperCase())
		.join(", ");
}

