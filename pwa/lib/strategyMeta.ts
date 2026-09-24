// pwa/lib/strategyMeta.ts
// Helpers to read strategy metadata saved in config blobs.
// The TF lives inside config_data (no dedicated column), under one of
// several keys depending on who saved it (editor / autopilot / webhook).

/** Resolve the candle timeframe from a strategy config blob, if present. */
export function resolveStrategyTimeframe(configData: unknown): string | null {
	if (!configData || typeof configData !== "object") return null;
	const cfg = configData as Record<string, unknown>;
	const entryTrigger = cfg.entryTrigger as Record<string, unknown> | undefined;
	const direct = [
		cfg.timeframe,
		cfg.candle_timeframe,
		cfg.entry_timeframe,
		entryTrigger?.timeframe,
	].find((v) => typeof v === "string" && (v as string).trim().length > 0);
	return typeof direct === "string" ? direct : null;
}
