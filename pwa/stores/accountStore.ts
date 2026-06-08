// pwa/stores/accountStore.ts

import { create } from "zustand";
import { persist } from "zustand/middleware";

/**
 * Global account selection store for PWA.
 * Persists the selected API key ID across page refreshes.
 * 'all' means show data from all accounts (aggregated view).
 */
interface AccountState {
	selectedApiKeyId: number | "all";
	setSelectedApiKeyId: (id: number | "all") => void;
}

export const useAccountStore = create<AccountState>()(
	persist(
		(set) => ({
			selectedApiKeyId: "all",
			setSelectedApiKeyId: (id) => set({ selectedApiKeyId: id }),
		}),
		{
			name: "depthsight-pwa-selected-account",
		},
	),
);
