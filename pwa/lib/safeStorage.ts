// pwa/lib/safeStorage.ts
// Crash-safe localStorage helpers. Any throw during render (e.g. corrupt
// value) unmounts the whole app into a black screen, so boot-time reads
// must never throw.

/** JSON read that falls back instead of throwing on corrupt values. */
export function readJson<T>(key: string, fallback: T): T {
	try {
		const raw = localStorage.getItem(key);
		if (!raw) return fallback;
		return JSON.parse(raw) as T;
	} catch (e) {
		console.error(`[storage] Corrupt value for key "${key}", using fallback`, e);
		return fallback;
	}
}

/** JSON write that never throws (e.g. quota exceeded on mobile). */
export function writeJson(key: string, value: unknown): void {
	try {
		localStorage.setItem(key, JSON.stringify(value));
	} catch (e) {
		console.error(`[storage] Failed to write key "${key}"`, e);
	}
}
