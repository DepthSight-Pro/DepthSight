// Import directly from node_modules to avoid alias recursion
// @ts-expect-error - Direct import from node_modules for bundler recursion fix
import * as i18nModule from "../node_modules/i18next/dist/esm/i18next.js";

// Extracting the main instance
const i18n =
	(i18nModule as unknown as Record<string, unknown>).default || i18nModule;

// Re-export everything
// @ts-expect-error - Direct export from node_modules for bundler recursion fix
export * from "../node_modules/i18next/dist/esm/i18next.js";

// Forced export for react-i18next
export const keyFromSelector =
	((i18nModule as unknown as Record<string, unknown>).keyFromSelector as
		| ((s: unknown) => unknown)
		| undefined) || ((s: unknown) => s);

export default i18n;
