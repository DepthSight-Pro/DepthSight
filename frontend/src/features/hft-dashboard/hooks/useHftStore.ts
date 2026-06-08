// src/features/hft-dashboard/hooks/useHftStore.ts

import { create } from "zustand";
import type {
	HftConfig,
	HftEquityUpdate,
	HftLogEvent,
	HftState,
	HftSystemStatus,
	OracleSymbol,
} from "../types/hft.types";

interface HftStoreActions {
	setConfig: (config: HftConfig) => void;
	updateStatus: (status: Partial<HftSystemStatus>) => void;
	addEquityPoint: (point: HftEquityUpdate) => void;
	setOracleSymbols: (symbols: OracleSymbol[]) => void;
	addLog: (log: HftLogEvent) => void;
	setConnectionStatus: (connected: boolean) => void;
	setEngineState: (running: boolean) => void;
	setApiKeyId: (id: number | null) => void;
	clearState: () => void;
}

export const useHftStore = create<HftState & HftStoreActions>((set) => ({
	config: null,
	status: {
		active_bots: 0,
		latency_ms: 0,
		server_load_cpu: 0,
		server_load_ram: 0,
		components: {},
		engine_active: false,
	},
	equityHistory: [],
	oracleSymbols: [],
	logs: [],
	isConnected: false,
	isEngineRunning: false,
	selectedApiKeyId: null,

	setConfig: (config) => set({ config }),

	updateStatus: (newStatus) =>
		set((state) => ({
			status: state.status
				? { ...state.status, ...newStatus }
				: (newStatus as HftSystemStatus),
			isEngineRunning: newStatus.engine_active ?? state.isEngineRunning,
		})),

	addEquityPoint: (point) =>
		set((state) => {
			// Keep last 1000 points to avoid memory issues
			const newHistory = [...state.equityHistory, point];
			if (newHistory.length > 1000) {
				newHistory.shift();
			}
			return { equityHistory: newHistory };
		}),

	setOracleSymbols: (symbols) => set({ oracleSymbols: symbols }),

	addLog: (log) =>
		set((state) => {
			const newLogs = [...state.logs, log];
			if (newLogs.length > 500) {
				// Keep last 500 logs
				newLogs.shift();
			}
			return { logs: newLogs };
		}),

	setConnectionStatus: (connected) => set({ isConnected: connected }),

	setEngineState: (running) => set({ isEngineRunning: running }),

	setApiKeyId: (id) => set({ selectedApiKeyId: id }),

	clearState: () =>
		set({
			config: null,
			status: {
				active_bots: 0,
				latency_ms: 0,
				server_load_cpu: 0,
				server_load_ram: 0,
				components: {},
				engine_active: false,
			},
			equityHistory: [],
			oracleSymbols: [],
			logs: [],
			isConnected: false,
			isEngineRunning: false,
			selectedApiKeyId: null,
		}),
}));
