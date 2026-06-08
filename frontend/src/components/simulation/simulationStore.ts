// frontend/src/components/simulation/simulationStore.ts
// Zustand store for simulation state management

import { create } from "zustand";
import {
	BUILT_IN_VARIANTS,
	type CustomVariant,
	calculateVariantStatsFromInspector,
	calculateVariantStatsFromSimulator,
	type InspectorCell,
	type InspectorMatrixData,
	MAX_VARIANTS,
	type SimulationConfig,
	type SimulationResult,
	type SimulationView,
	STRATEGY_VARIANTS,
	type VariantStats,
} from "./types";

// Color palette for variants
const VARIANT_COLORS = [
	"#06B6D4", // Cyan
	"#8B5CF6", // Violet
	"#10B981", // Emerald
	"#F59E0B", // Amber
	"#EF4444", // Red
	"#EC4899", // Pink
	"#6366F1", // Indigo
	"#84CC16", // Lime
	"#14B8A6", // Teal
];

interface SimulationState {
	// View state
	currentView: SimulationView;
	setView: (view: SimulationView) => void;

	// Assets
	availableAssets: string[];
	selectedAssets: string[];
	setAvailableAssets: (assets: string[]) => void;
	toggleAsset: (asset: string) => void;
	selectAllAssets: () => void;
	clearAssets: () => void;

	// Variants
	selectedVariants: string[];
	toggleVariant: (variantId: string) => void;

	// Custom Variants
	customVariants: CustomVariant[];
	addCustomVariant: (variant: CustomVariant) => void;
	updateCustomVariant: (id: string, updates: Partial<CustomVariant>) => void;
	removeCustomVariant: (id: string) => void;
	duplicateVariant: (id: string) => void;
	getAllVariants: () => CustomVariant[];
	canAddVariant: () => boolean;

	// Strategy
	strategyJson: Record<string, unknown> | null;
	setStrategyJson: (strategy: Record<string, unknown> | null) => void;

	// Config
	config: SimulationConfig;
	updateConfig: (config: Partial<SimulationConfig>) => void;

	// Results
	inspectorResult: InspectorMatrixData | null;
	simulationResult: SimulationResult | null;
	setInspectorResult: (result: InspectorMatrixData | null) => void;
	setSimulationResult: (result: SimulationResult | null) => void;
	updateInspectorCell: (
		asset: string,
		variant: string,
		data: InspectorCell,
	) => void;
	initInspectorMatrix: (assets: string[], variants: string[]) => void;

	// Cached variant stats - calculated ONCE and used everywhere
	cachedInspectorStats: VariantStats[];
	cachedSimulatorStats: VariantStats[];
	recomputeVariantStats: () => void;
	getVariantStats: (source: "inspector" | "simulator") => VariantStats[];

	// Active asset for deep dive
	activeAsset: string | null;
	setActiveAsset: (asset: string | null) => void;

	// Comparison Source
	compareSource: "inspector" | "simulator" | null;
	setCompareSource: (source: "inspector" | "simulator" | null) => void;

	// Date Filtering
	startDate: string | null;
	endDate: string | null;
	setStartDate: (date: string | null) => void;
	setEndDate: (date: string | null) => void;

	// Loading & Progress
	isLoading: boolean;
	setLoading: (loading: boolean) => void;
	progress: number;
	setProgress: (progress: number) => void;

	// Display filter (for Portfolio tab variant selection)
	selectedDisplayVariant: string | null;
	setSelectedDisplayVariant: (variant: string | null) => void;

	// Selected trade for preview in DeepDive (set from Timeline click)
	selectedTradeForPreview: {
		id?: string;
		entryTime: number;
		exitTime: number;
		entryPrice?: number;
		exitPrice?: number;
		pnlPct: number;
		asset: string;
		variant?: string;
	} | null;
	setSelectedTradeForPreview: (
		trade: SimulationState["selectedTradeForPreview"],
	) => void;
}

export const useSimulationStore = create<SimulationState>((set, get) => ({
	currentView: "matrix",
	setView: (view) => set({ currentView: view }),

	availableAssets: [],
	selectedAssets: [],
	setAvailableAssets: (assets) => set({ availableAssets: assets }),
	toggleAsset: (asset) =>
		set((state) => ({
			selectedAssets: state.selectedAssets.includes(asset)
				? state.selectedAssets.filter((a) => a !== asset)
				: [...state.selectedAssets, asset],
		})),
	selectAllAssets: () =>
		set((state) => ({ selectedAssets: [...state.availableAssets] })),
	clearAssets: () => set({ selectedAssets: [] }),

	selectedVariants: [
		"raw",
		"oracle_entry",
		"oracle_be",
		"hybrid_be",
		"oracle_partial",
	],
	toggleVariant: (variantId) =>
		set((state) => {
			if (state.selectedVariants.includes(variantId)) {
				return {
					selectedVariants: state.selectedVariants.filter(
						(v) => v !== variantId,
					),
				};
			}
			if (state.selectedVariants.length >= MAX_VARIANTS) return state;
			return { selectedVariants: [...state.selectedVariants, variantId] };
		}),

	// Custom Variants
	customVariants: [],

	addCustomVariant: (variant) =>
		set((state) => {
			// Allow up to 10 custom variants
			if (state.customVariants.length >= 10) return state;
			return { customVariants: [...state.customVariants, variant] };
		}),

	updateCustomVariant: (id, updates) =>
		set((state) => ({
			customVariants: state.customVariants.map((v) =>
				v.id === id ? { ...v, ...updates } : v,
			),
		})),

	removeCustomVariant: (id) =>
		set((state) => ({
			customVariants: state.customVariants.filter((v) => v.id !== id),
			selectedVariants: state.selectedVariants.filter((v) => v !== id),
		})),

	duplicateVariant: (id) =>
		set((state) => {
			const source = [...BUILT_IN_VARIANTS, ...state.customVariants].find(
				(v) => v.id === id,
			);
			if (!source || state.customVariants.length >= 10) return state;
			const newVariant: CustomVariant = {
				...source,
				id: `custom_${Date.now()}`,
				name: `${source.name} Copy`,
				isBuiltIn: false,
			};
			return { customVariants: [...state.customVariants, newVariant] };
		}),

	getAllVariants: () => [...BUILT_IN_VARIANTS, ...get().customVariants],

	canAddVariant: () => get().customVariants.length < 10, // Max 10 custom variants

	strategyJson: null,
	setStrategyJson: (strategy) => set({ strategyJson: strategy }),

	config: {
		initialCapital: 10000,
		maxConcurrentPositions: 5,
		baseRiskPct: 1.0,
		leverage: 5.0,
		adaptiveRisk: true,
		compounding: true,
	},
	updateConfig: (newConfig) =>
		set((state) => ({
			config: { ...state.config, ...newConfig },
		})),

	inspectorResult: null,
	simulationResult: null,

	// Set inspector result and auto-recompute stats
	setInspectorResult: (result) => {
		set({ inspectorResult: result });
		// Trigger recomputation after setting result
		get().recomputeVariantStats();
	},

	// Set simulation result and auto-recompute stats
	setSimulationResult: (result) => {
		set({ simulationResult: result });
		// Trigger recomputation after setting result
		get().recomputeVariantStats();
	},

	// Initialize empty matrix for incremental updates
	initInspectorMatrix: (assets, variants) =>
		set({
			inspectorResult: {
				matrix: Object.fromEntries(
					assets.map((asset) => [
						asset,
						Object.fromEntries(
							variants.map((v) => [
								v,
								{
									pnl_pct: 0,
									win_rate: 0,
									trades_count: 0,
									sharpe: 0,
									max_dd: 0,
									commission: 0,
								},
							]),
						),
					]),
				),
				assets,
				variants,
			},
		}),

	// Update single cell
	updateInspectorCell: (asset, variant, data) => {
		set((state) => {
			if (!state.inspectorResult) return state;
			return {
				inspectorResult: {
					...state.inspectorResult,
					matrix: {
						...state.inspectorResult.matrix,
						[asset]: {
							...state.inspectorResult.matrix[asset],
							[variant]: data,
						},
					},
				},
			};
		});
		get().recomputeVariantStats();
	},

	// Cached variant stats - calculated ONCE and used everywhere
	cachedInspectorStats: [],
	cachedSimulatorStats: [],

	// Recompute all variant stats from current data
	recomputeVariantStats: () => {
		const state = get();
		const { inspectorResult, simulationResult, selectedVariants, config } =
			state;

		// Compute Inspector stats
		let inspectorStats: VariantStats[] = [];
		if (
			inspectorResult?.matrix &&
			Object.keys(inspectorResult.matrix).length > 0
		) {
			inspectorStats = selectedVariants
				.map((variantId, idx) => {
					const variantDef = STRATEGY_VARIANTS.find((v) => v.id === variantId);
					const name = variantDef?.name || variantId;
					const color = VARIANT_COLORS[idx % VARIANT_COLORS.length];

					return calculateVariantStatsFromInspector(
						inspectorResult.matrix,
						variantId,
						name,
						color,
						config.initialCapital,
					);
				})
				.filter((s): s is VariantStats => s !== null && s.tradesCount > 0);
		}

		// Compute Simulator stats
		let simulatorStats: VariantStats[] = [];
		if (simulationResult?.trades && simulationResult.trades.length > 0) {
			const variantsToProcess =
				selectedVariants.length > 0
					? selectedVariants
					: [
							...new Set(
								simulationResult.trades.map((t) => t.strategy || "unknown"),
							),
						];

			simulatorStats = variantsToProcess
				.map((variantId, idx) => {
					const variantDef = STRATEGY_VARIANTS.find((v) => v.id === variantId);
					const name = variantDef?.name || variantId;
					const color = VARIANT_COLORS[idx % VARIANT_COLORS.length];

					return calculateVariantStatsFromSimulator(
						simulationResult.trades,
						variantId,
						name,
						color,
						config,
					);
				})
				.filter((s): s is VariantStats => s !== null && s.tradesCount > 0);
		}

		set({
			cachedInspectorStats: inspectorStats,
			cachedSimulatorStats: simulatorStats,
		});
	},

	// Get cached stats for a given source
	getVariantStats: (source) => {
		const state = get();
		return source === "simulator"
			? state.cachedSimulatorStats
			: state.cachedInspectorStats;
	},

	activeAsset: null,
	setActiveAsset: (asset) =>
		set({
			activeAsset: asset,
			currentView: asset ? "deepdive" : "matrix",
		}),

	compareSource: null,
	setCompareSource: (source) => set({ compareSource: source }),

	startDate: null,
	endDate: null,
	setStartDate: (date) => set({ startDate: date }),
	setEndDate: (date) => set({ endDate: date }),

	isLoading: false,
	setLoading: (loading) => set({ isLoading: loading }),

	progress: 0,
	setProgress: (progress) => set({ progress }),

	selectedDisplayVariant: null,
	setSelectedDisplayVariant: (variant) =>
		set({ selectedDisplayVariant: variant }),

	selectedTradeForPreview: null,
	setSelectedTradeForPreview: (trade) =>
		set({ selectedTradeForPreview: trade }),
}));
