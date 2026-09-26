// pwa/components/ExchangeBadge.tsx
import React from "react";

const normalizeExchangeKey = (raw?: string | null): string => {
	if (!raw) return "";
	return String(raw)
		.trim()
		.toLowerCase()
		.replace(/_(futures|spot|usdtm|swap|linear|usdm|testnet)$/, "")
		.replace(/_testnet$/, "");
};

const exchangeLogos: Record<string, string> = {
	binance: "/logos/binance.svg",
	bybit: "/logos/bybit.svg",
	okx: "/logos/okx.svg",
	bitget: "/logos/bitget.svg",
	gate: "/logos/gate.svg",
	gateio: "/logos/gate.svg",
	bingx: "/logos/bingx.svg",
	weex: "/logos/weex.svg",
};

const exchangeLabels: Record<string, string> = {
	binance: "Binance",
	bybit: "Bybit",
	okx: "OKX",
	bitget: "Bitget",
	gate: "Gate.io",
	gateio: "Gate.io",
	bingx: "BingX",
	weex: "WEEX",
};

export const ExchangeBadge: React.FC<{
	exchange?: string | null;
	size?: "xs" | "sm" | "md" | "lg";
	className?: string;
}> = ({ exchange, size = "sm", className }) => {
	const ex = normalizeExchangeKey(exchange);
	const logo = ex ? exchangeLogos[ex] : undefined;
	const label = (ex ? exchangeLabels[ex] : null) || exchange || "?";

	const sizeClasses = {
		xs: "h-5 w-5 min-w-5 min-h-5",
		sm: "h-6 w-6 min-w-6 min-h-6",
		md: "h-7 w-7 min-w-7 min-h-7",
		lg: "h-9 w-9 min-w-9 min-h-9",
	}[size];

	const imgSizes = {
		xs: "h-3.5 w-3.5 max-h-3.5 max-w-3.5",
		sm: "h-4 w-4 max-h-4 max-w-4",
		md: "h-4.5 w-4.5 max-h-4.5 max-w-4.5",
		lg: "h-6 w-6 max-h-6 max-w-6",
	}[size];

	return (
		<span
			className={`relative inline-grid place-items-center rounded-full bg-white shrink-0 shadow-sm border border-black/10 overflow-hidden select-none leading-none ${sizeClasses} ${className || ""}`}
			title={label}
		>
			{logo ? (
				<img
					src={logo}
					alt={label}
					className={`m-auto block object-contain object-center pointer-events-none select-none shrink-0 ${imgSizes}`}
					onError={(e) => {
						(e.currentTarget as HTMLElement).style.display = "none";
					}}
				/>
			) : (
				<span className="text-[10px] font-bold text-slate-800">
					{label.slice(0, 2).toUpperCase()}
				</span>
			)}
		</span>
	);
};
