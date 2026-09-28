// frontend/src/services/liveMarks/fundingMath.ts
// Pure funding-spread math for the hedge widget (no I/O, easily testable).
// Rates are decimals: 0.0001 === +0.0100% per settlement period.

export const DEFAULT_INTERVAL_HOURS = 8;

/** Converts a per-settlement rate to an 8h-equivalent rate. */
export function normalizeRateTo8h(
	rate: number,
	intervalHours?: number | null,
): number {
	const hours =
		intervalHours && Number.isFinite(intervalHours) && intervalHours > 0
			? intervalHours
			: DEFAULT_INTERVAL_HOURS;
	return rate * (DEFAULT_INTERVAL_HOURS / hours);
}

/**
 * Net funding received per 8h for an OPPOSITE hedge (LONG legA + SHORT legB),
 * as a decimal fraction of notional. Positive => the pair earns funding.
 */
export function netFunding8h(
	rateA: number,
	rateB: number,
	intervalA?: number | null,
	intervalB?: number | null,
): number {
	return normalizeRateTo8h(rateB, intervalB) - normalizeRateTo8h(rateA, intervalA);
}

/** USD earned per 8h on the given notional at the net 8h rate. */
export function estimateFundingUsd8h(
	netRate8h: number,
	notionalUsd: number,
): number {
	return netRate8h * notionalUsd;
}

/**
 * Next settlement slot (ms) on a UTC-anchored grid.
 * Matches the standard 8h/4h/1h venue schedules (00:00, 08:00, 16:00 UTC...).
 */
export function nextGridSlotMs(
	intervalHours: number,
	nowMs: number = Date.now(),
): number {
	const step = Math.max(1, intervalHours) * 3600_000;
	return Math.floor(nowMs / step) * step + step;
}

/** ms -> "07:23:11" (clamped at zero). */
export function formatCountdown(remainingMs: number): string {
	const totalSec = Math.max(0, Math.floor(remainingMs / 1000));
	const h = Math.floor(totalSec / 3600);
	const m = Math.floor((totalSec % 3600) / 60);
	const s = totalSec % 60;
	const pad = (n: number) => String(n).padStart(2, "0");
	return `${pad(h)}:${pad(m)}:${pad(s)}`;
}

/** 0.0001 -> "+0.0100%", -0.0002 -> "-0.0200%". */
export function formatFundingPct(rate: number): string {
	const sign = rate > 0 ? "+" : rate < 0 ? "-" : "";
	return `${sign}${(Math.abs(rate) * 100).toFixed(4)}%`;
}

/** Signed USD with 2 decimals: +1.25 / -0.40. */
export function formatSignedUsd(value: number): string {
	const sign = value > 0 ? "+" : value < 0 ? "-" : "";
	return `${sign}$${Math.abs(value).toFixed(2)}`;
}
