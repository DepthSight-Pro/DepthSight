// src/lib/exchanges.ts
//
// Exchange display metadata (labels, brand colors, glyphs).
// Moved here from the removed dashboardMock module — no mock data.

import binanceLogo from "@/content/logos/binance.svg";
import bingxLogo from "@/content/logos/bingx.svg";
import bitgetLogo from "@/content/logos/bitget.svg";
import bybitLogo from "@/content/logos/bybit.svg";
import gateLogo from "@/content/logos/gate.svg";
import okxLogo from "@/content/logos/okx.svg";
import weexLogo from "@/content/logos/weex.svg";

export type Exchange =
	| "binance"
	| "bybit"
	| "okx"
	| "bitget"
	| "weex"
	| "gate"
	| "bingx";

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
	if (
		raw === "binance" ||
		raw === "bybit" ||
		raw === "okx" ||
		raw === "bitget" ||
		raw === "weex" ||
		raw === "gate" ||
		raw === "bingx"
	) {
		return raw;
	}
	return null;
}
