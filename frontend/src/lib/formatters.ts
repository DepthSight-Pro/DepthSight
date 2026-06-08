// src/lib/formatters.ts

export const formatCryptoPrice = (price: number | undefined | null): string => {
	if (price === undefined || price === null) return "N/A";
	if (price === 0) return "0.00";

	const absPrice = Math.abs(price);

	if (absPrice >= 1000) return price.toFixed(2); // BTC, ETH
	if (absPrice >= 10) return price.toFixed(3); // SOL, LINK (maybe 3 is good)
	if (absPrice >= 1) return price.toFixed(4); // XRP, MATIC
	if (absPrice >= 0.01) return price.toFixed(6); // DOGE, TRX
	return price.toFixed(8); // SHIB, PEPE
};
