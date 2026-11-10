import React, { useState } from "react";
import {
	exchangeLabels,
	exchangeLogos,
	normalizeExchangeKey,
} from "../lib/exchanges";

export const ExchangeBadge: React.FC<{
	exchange?: string | null;
	size?: "xs" | "sm" | "md" | "lg";
	className?: string;
}> = ({ exchange, size = "sm", className }) => {
	const ex = normalizeExchangeKey(exchange);
	const logo = ex ? exchangeLogos[ex] : undefined;
	const label = (ex ? exchangeLabels[ex] : null) || exchange || "?";
	const [failedLogo, setFailedLogo] = useState<string | null>(null);

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

	const showImage = Boolean(logo && failedLogo !== logo);

	return (
		<span
			className={`relative inline-grid place-items-center rounded-full bg-white shrink-0 shadow-sm border border-black/10 overflow-hidden select-none leading-none ${sizeClasses} ${className || ""}`}
			title={label}
		>
			{showImage && logo ? (
				<img
					src={logo}
					alt={label}
					className={`m-auto block object-contain object-center pointer-events-none select-none shrink-0 ${imgSizes}`}
					onError={() => setFailedLogo(logo)}
					draggable={false}
				/>
			) : (
				<span className="text-[10px] font-bold text-slate-800 leading-none">
					{label.slice(0, 2).toUpperCase()}
				</span>
			)}
		</span>
	);
};
