// src/lib/utils.ts

import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
	return twMerge(clsx(inputs));
}

export const estimateTickSize = (klines: any[]): number => {
	if (!klines || klines.length === 0) return 0.0001;
	let maxDecimals = 2;
	for (let i = 0; i < Math.min(klines.length, 10); i++) {
		const kline = klines[i];
		const closePrice = Array.isArray(kline) ? Number(kline[4]) : Number(kline.close);
		if (!isNaN(closePrice) && closePrice > 0) {
			const priceStr = closePrice.toString();
			if (priceStr.includes("e")) {
				const parts = priceStr.split("e-");
				const exp = parseInt(parts[1] || "2", 10);
				if (exp > maxDecimals) maxDecimals = exp;
			} else {
				const dotIndex = priceStr.indexOf(".");
				if (dotIndex !== -1) {
					const decimals = priceStr.length - dotIndex - 1;
					if (decimals > maxDecimals) {
						maxDecimals = decimals;
					}
				}
			}
		}
	}
	return Math.pow(10, -maxDecimals);
};
