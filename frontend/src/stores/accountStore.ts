// src/stores/accountStore.ts

import { create } from "zustand";
import { persist } from "zustand/middleware";
import type { MarketScope } from "@/types/api";

/**
 * Global account selection store.
 * Persists the selected API key ID across page refreshes.
 * 'all' means show data from all accounts (aggregated view).
 */
interface AccountState {
	selectedApiKeyId: number | "all";
	selectedMarketType: MarketScope;
	setSelectedApiKeyId: (id: number | "all") => void;
	setSelectedMarketType: (marketType: MarketScope) => void;
}

export const useAccountStore = create<AccountState>()(
	persist(
		(set) => ({
			selectedApiKeyId: "all",
			selectedMarketType: "all",
			setSelectedApiKeyId: (id) => set({ selectedApiKeyId: id }),
			setSelectedMarketType: (marketType) =>
				set({ selectedMarketType: marketType }),
		}),
		{
			name: "depthsight-selected-account",
		},
	),
);
