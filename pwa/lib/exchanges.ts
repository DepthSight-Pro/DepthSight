// pwa/lib/exchanges.ts
export const normalizeExchangeKey = (raw?: string | null): string => {
	if (!raw) return "";
	return String(raw)
		.trim()
		.toLowerCase()
		.replace(/_(futures|spot|usdtm|swap|linear|usdm|testnet)$/, "")
		.replace(/_testnet$/, "");
};

const getBaseUrl = (): string => {
	const base = import.meta.env.BASE_URL || "/";
	return base.endsWith("/") ? base : `${base}/`;
};

const BASE_PATH = getBaseUrl();

export const exchangeLogos: Record<string, string> = {
	binance: `${BASE_PATH}logos/binance.svg`,
	bybit: `${BASE_PATH}logos/bybit.svg`,
	okx: `${BASE_PATH}logos/okx.svg`,
	bitget: `${BASE_PATH}logos/bitget.svg`,
	gate: `${BASE_PATH}logos/gate.svg`,
	gateio: `${BASE_PATH}logos/gate.svg`,
	gate_io: `${BASE_PATH}logos/gate.svg`,
	bingx: `${BASE_PATH}logos/bingx.svg`,
	weex: `${BASE_PATH}logos/weex.svg`,
	hyperliquid: `${BASE_PATH}logos/hyperliquid.svg`,
	hl: `${BASE_PATH}logos/hyperliquid.svg`,
};

export const exchangeLabels: Record<string, string> = {
	binance: "Binance",
	bybit: "Bybit",
	okx: "OKX",
	bitget: "Bitget",
	gate: "Gate.io",
	gateio: "Gate.io",
	gate_io: "Gate.io",
	bingx: "BingX",
	weex: "WEEX",
	hyperliquid: "Hyperliquid",
	hl: "Hyperliquid",
};

export const activeMiningExchanges = ["bybit", "okx", "weex", "bitget"];

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


