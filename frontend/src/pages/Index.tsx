// src/pages/Index.tsx

import {
	Gauge,
	Layers,
	LineChart,
	Percent,
	RefreshCw,
	Target,
	Wallet,
} from "lucide-react";
import React, { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import {
	ExchangeBadge,
} from "@/components/layout/AccountSelector";
import { PageLayout } from "@/components/layout/PageLayout";
import { PositionChartModal } from "@/components/positions/PositionChartModal";
import { PositionSparkline } from "@/components/positions/PositionSparkline";
import {
	AreaChart,
	Badge,
	Bar,
	Btn,
	fmt,
	Heatmap,
	Panel,
	Radial,
	Segmented,
	Sparkline,
	Stat,
	Td,
	Th,
	toneHex,
	toneText,
} from "@/components/ui/quant-ui";
import { useAuth } from "@/context/AuthContext";
import { usePortfolioMode } from "@/context/PortfolioModeContext";
import { useWebSocket } from "@/context/WebSocketProvider";
import { useLiveMarks } from "@/hooks/useLiveMarks";
import {
	applyLiveMarksToPositions,
	overlayLiveStrategyPnl,
} from "@/lib/livePnl";
import {
	useConfig,
	useLogHistory,
	useMultiAccountBalances,
	usePortfolioEquity,
	usePortfolioStatus,
	usePositions,
	useStrategies,
	useStrategyConfigsList,
	useTradeHistory,
} from "@/lib/api";
import {
	cumulativePnlByStrategy,
	heatmapFromTrades,
	maxDrawdownPct,
	summarizeTrades,
} from "@/lib/analytics";
import { exchangeMeta, normalizeExchangeKey } from "@/lib/exchanges";
import { resolveStrategyTimeframe } from "@/lib/strategyMeta";
import { cn } from "@/lib/utils";
import { useAccountStore } from "@/stores/accountStore";
import { resolvePositionStrategyName } from "@/features/notifications/resolveStrategyName";
import type { AccountBalance, ApiKey, LogEntry, MarketScope, PositionData, StrategyData } from "@/types/api";

const normalizeMarketScope = (marketType?: string | null): MarketScope => {
	if (!marketType || marketType === "all") return "all";
	return String(marketType).toLowerCase().startsWith("spot")
		? "spot"
		: "futures_usdtm";
};

// --- View-model types for the dashboard ---

// Raw position from API/live feed — PositionData plus camelCase alias
// fields that some exchange connectors return alongside the canonical ones.
type IndexPosition = PositionData & {
	side?: string;
	entryPrice?: number;
	markPrice?: number;
	unrealizedPnl?: number;
	apiKeyId?: number;
	exchange_id?: string | null;
	leverage?: number;
	entryTime?: string | null;
	strategy_name?: string;
	sl?: number | string | null;
	tp?: number | string | null;
};

// Enriched position after local PnL overlay computations.
type VisiblePosition = IndexPosition & {
	entry: number;
	mark: number;
	pnlPct: number;
	meta: { label: string; color: string; glyph: string } | null;
};

// Enriched strategy for the "Active Bots" list.
type VisibleStrategy = {
	id: string;
	name: string;
	strategy_name: string;
	mode: "live" | "paper" | null;
	status: "IN_POSITION" | "RUNNING";
	exchange: string | null;
	apiKeyId: number | null;
	openPositions: number;
	timeframe: string;
	trades: number;
	winRate: number | null;
	pnl: number | null;
	equity: number[];
	configId: string | null;
};

const Index = () => {
	const { t } = useTranslation(["index", "common"]);
	const { mode } = usePortfolioMode();
	const { user } = useAuth();
	const { subscribe, unsubscribe, readyState } = useWebSocket();
	const wsLive = readyState === 1;
	const navigate = useNavigate();

	const { selectedApiKeyId, selectedMarketType } = useAccountStore();
	const { data: config } = useConfig();

	// --- Dashboard scope (Equity card + Equity Curve) ---
	// Follows the account/market selector: a specific API key scopes the
	// dashboard to that exchange (and its market), otherwise the selected
	// market type ("all" | "futures_usdtm" | "spot") is applied.
	const apiKeysList = useMemo(() => config?.apiKeys ?? [], [config]);
	const apiKeysById = useMemo(() => {
		const m = new Map<number, (typeof apiKeysList)[number]>();
		for (const k of apiKeysList) m.set(Number(k.id), k);
		return m;
	}, [apiKeysList]);
	const selectedScopeKey =
		selectedApiKeyId !== "all"
			? apiKeysList.find((k) => Number(k.id) === Number(selectedApiKeyId))
			: undefined;
	const scopeMarket: MarketScope = selectedScopeKey
		? normalizeMarketScope(
				(selectedScopeKey as { marketType?: string }).marketType,
			)
		: normalizeMarketScope(selectedMarketType);
	const scopeExchange =
		(selectedScopeKey?.exchange || "").toLowerCase() || null;
	const scopeActive = !!selectedScopeKey || scopeMarket !== "all";
	const scopeLabel = selectedScopeKey
		? selectedScopeKey.name || scopeExchange || "selected account"
		: scopeMarket === "all"
			? "all accounts"
			: scopeMarket === "spot"
				? "spot"
				: "futures";
	// True when a trade/balance belongs to the selected exchange + market scope.
	const matchesScope = useCallback(
		(item: {
			apiKeyId?: number | string | null;
			exchange?: string | null;
			marketType?: string | null;
		}) => {
			if (scopeExchange) {
				if (item.exchange)
					return item.exchange.toLowerCase() === scopeExchange;
				if (item.apiKeyId != null)
					return Number(item.apiKeyId) === Number(selectedApiKeyId);
				return true;
			}
			if (scopeMarket !== "all") {
				if (item.marketType)
					return normalizeMarketScope(item.marketType) === scopeMarket;
				if (item.apiKeyId != null) {
					const key = apiKeysById.get(Number(item.apiKeyId));
					if (key)
						return (
							normalizeMarketScope(
								(key as { marketType?: string }).marketType,
							) === scopeMarket
						);
				}
				return true;
			}
			return true;
		},
		[scopeExchange, scopeMarket, selectedApiKeyId, apiKeysById],
	);

	const { data: balances } = useMultiAccountBalances(scopeMarket);

	const hookParams = useMemo(
		() => ({
			mode,
			apiKeyId: mode === "live" ? selectedApiKeyId : undefined,
			marketType: mode === "live" ? selectedMarketType : undefined,
		}),
		[mode, selectedApiKeyId, selectedMarketType],
	);

	const { data: portfolioStatus } = usePortfolioStatus(hookParams);
	// Push-driven (WS snapshots); poll only when socket is down.
	const { data: realPositions, refetch: refetchPositions } = usePositions({
		...hookParams,
		refetchInterval: wsLive ? false : 5000,
	});
	const { data: realStrategies } = useStrategies({
		mode,
		apiKeyId: mode === "live" ? selectedApiKeyId : undefined,
		refetchInterval: wsLive ? false : 5000,
	});
	const { data: logHistory } = useLogHistory();
	// Saved configs (cached) to resolve real timeframes and user-defined names for Active Bots.
	const { data: savedConfigs } = useStrategyConfigsList();
	const timeframeByConfigId = useMemo(() => {
		const m = new Map<string, string>();
		for (const c of savedConfigs ?? []) {
			const tf = resolveStrategyTimeframe(
				(c as unknown as Record<string, unknown>).config_data,
			);
			if (tf) m.set(String(c.id), tf);
		}
		return m;
	}, [savedConfigs]);

	const nameByConfigId = useMemo(() => {
		const m = new Map<string, string>();
		for (const c of savedConfigs ?? []) {
			if (c.id && c.name) {
				m.set(String(c.id), c.name);
			}
		}
		return m;
	}, [savedConfigs]);

	// Position Chart Modal state
	const [chartPos, setChartPos] = useState<VisiblePosition | null>(null);
	const [isChartOpen, setIsChartOpen] = useState(false);

	// Period for Equity Curve
	const [period, setPeriod] = useState<"1d" | "7d" | "mtd">("7d");

	const [now] = useState(() => new Date());
	const periodStart = useMemo(() => {
		if (period === "7d") return new Date(now.getTime() - 7 * 86400 * 1000);
		if (period === "mtd")
			return new Date(now.getFullYear(), now.getMonth(), 1);
		return new Date(now.getTime() - 86400 * 1000);
	}, [period, now]);
	const statsStart = useMemo(
		() => new Date(now.getTime() - 30 * 86400 * 1000),
		[now],
	);
	const scopedApiKeyId = mode === "live" ? selectedApiKeyId : undefined;

	const { data: equityHistory, isLoading: isEquityLoading } =
		usePortfolioEquity(period, mode);
	const { data: periodTradesData } = useTradeHistory({
		mode,
		startDate: periodStart.toISOString(),
		endDate: now.toISOString(),
		limit: 10000,
		apiKeyId: scopedApiKeyId,
	});
	const { data: statsTradesData } = useTradeHistory({
		mode,
		startDate: statsStart.toISOString(),
		endDate: now.toISOString(),
		limit: 10000,
		apiKeyId: scopedApiKeyId,
	});

	const toCloseMs = (value: unknown): number | null => {
		if (value === undefined || value === null) return null;
		if (typeof value === "number") {
			const ms = value > 1_000_000_000_000 ? value : value * 1000;
			return Number.isFinite(ms) ? ms : null;
		}
		const ms = new Date(value as string).getTime();
		return Number.isFinite(ms) ? ms : null;
	};

	const historyValues = useMemo(
		() => (equityHistory || []).map(([, v]) => Number(v) || 0),
		[equityHistory],
	);
	const hasHistory = historyValues.length > 1;

	const periodTrades = useMemo(() => {
		const startMs = periodStart.getTime();
		const endMs = now.getTime();
		return (periodTradesData?.trades || []).filter((trade) => {
			const closeMs = toCloseMs(trade.timestamp_close);
			if (closeMs === null || closeMs < startMs || closeMs > endMs)
				return false;
			return matchesScope(trade);
		});
	}, [periodTradesData, periodStart, now, matchesScope]);
	const periodSummary = useMemo(
		() => summarizeTrades(periodTrades),
		[periodTrades],
	);
	// Stats window (30d) trades, scoped to the selected exchange + market.
	const scopedStatsTrades = useMemo(
		() => (statsTradesData?.trades || []).filter((t) => matchesScope(t)),
		[statsTradesData, matchesScope],
	);
	const statsSummary = useMemo(
		() => summarizeTrades(scopedStatsTrades),
		[scopedStatsTrades],
	);
	const heatmapRows = useMemo(
		() => heatmapFromTrades(scopedStatsTrades),
		[scopedStatsTrades],
	);
	const strategyEquity = useMemo(
		() => cumulativePnlByStrategy(scopedStatsTrades),
		[scopedStatsTrades],
	);

	// Real per-run stats for Active Bots ("Top Performing Strategies"):
	// the /strategies snapshot carries no trades/win-rate fields, so they are
	// computed from closed trades of THIS run — matched by config id (primary)
	// or strategy name (fallback) + api key, and only since the run started.
	const runStatsByInstanceId = useMemo(() => {
		const m = new Map<string, { trades: number; winRate: number | null }>();
		if (!realStrategies) return m;
		// Minimal shape of the /strategies snapshot fields used below.
	type StrategySnapshot = {
		id?: string;
		name?: string;
		strategy_name?: string;
		config_id?: string;
		api_key_id?: number | null;
		started_at?: string;
	};
	for (const s of realStrategies as unknown as StrategySnapshot[]) {
			const name = s.name || s.strategy_name || "";
			const startedMs = s.started_at
				? new Date(s.started_at).getTime()
				: null;
			const runTrades = scopedStatsTrades.filter((t) => {
				const pnl = Number(t.pnl);
				if (!Number.isFinite(pnl)) return false;
				if (t.strategy_config_id && s.config_id) {
					if (String(t.strategy_config_id) !== String(s.config_id))
						return false;
				} else if (t.strategy && name) {
					if (t.strategy !== name && t.strategy !== s.strategy_name)
						return false;
				} else {
					return false;
				}
				if (
					s.api_key_id != null &&
					t.api_key_id != null &&
					Number(t.api_key_id) !== Number(s.api_key_id)
				)
					return false;
				// Only trades closed after this instance started.
				if (startedMs != null && Number.isFinite(startedMs)) {
					const closeMs = toCloseMs(t.timestamp_close);
					if (closeMs != null && closeMs < startedMs) return false;
				}
				return true;
			});
			const wins = runTrades.filter((t) => (Number(t.pnl) || 0) > 0).length;
			m.set(String(s.id), {
				trades: runTrades.length,
				winRate:
					runTrades.length > 0
						? +((wins / runTrades.length) * 100).toFixed(1)
						: null,
			});
		}
		return m;
	}, [realStrategies, scopedStatsTrades]);

	// Active API keys from config
	const apiKeys = config?.apiKeys;
	const activeApiKeys = useMemo(() => {
		if (!apiKeys || apiKeys.length === 0) return [];
		const active = apiKeys.filter((k) => k.isActive && k.status !== "invalid");
		if (active.length > 0) return active;
		return apiKeys.filter((k) => k.status !== "invalid");
	}, [apiKeys]);

	// Balances record lookup
	const balanceAccounts = balances?.accounts;
	const balancesRecord = useMemo(() => {
		if (!balanceAccounts) return {};
		return balanceAccounts.reduce(
			(acc, bal) => {
				const existing = acc[bal.apiKeyId];
				if (existing) {
					acc[bal.apiKeyId] = {
						...existing,
						balance: existing.balance + bal.balance,
						availableBalance: existing.availableBalance + bal.availableBalance,
						unrealizedPnl: existing.unrealizedPnl + bal.unrealizedPnl,
						totalEquity: existing.totalEquity + bal.totalEquity,
					};
				} else {
					acc[bal.apiKeyId] = bal;
				}
				return acc;
			},
			{} as Record<number, AccountBalance>,
		);
	}, [balanceAccounts]);

	// Account allocation data (real API keys + balances only, no mocks)
	const accountList = useMemo(() => {
		if (!activeApiKeys || activeApiKeys.length === 0) return [];
		const totalEq =
			activeApiKeys.reduce((acc, k) => {
				const bal =
					balancesRecord[k.id]?.totalEquity ||
					balancesRecord[k.id]?.balance ||
					0;
				return acc + bal;
			}, 0) || 1;

		return activeApiKeys.map((k) => {
			const bal = balancesRecord[k.id];
			const eq = bal?.totalEquity || bal?.balance || 0;
			const pnl24 = bal?.unrealizedPnl || 0;
			const share = eq > 0 ? eq / totalEq : 1 / activeApiKeys.length;
			const exKey = (k.exchange || "binance").toLowerCase();
			const meta = exchangeMeta[exKey] || exchangeMeta.binance;

			return {
				id: k.id,
				name: k.name || meta.label,
				exchange: exKey,
				marketType: k.marketType || "futures",
				equity: eq,
				pnl24h: pnl24,
				share,
				status: k.status === "invalid" ? "error" : "ok",
				meta,
			};
		});
	}, [activeApiKeys, balancesRecord]);

	// Live mark-prices straight from exchanges (zero backend load).
	// Backend snapshot gives entry/qty/side; ticks only move mark/pnl locally.
	const liveSymbols = useMemo(
		() =>
			(realPositions || []).map((p: PositionData) => ({
				symbol: String(p.symbol),
				exchange: (p.exchange as string | null) ?? null,
			})),
		[realPositions],
	);
	const { marks: liveMarks, liveCount } = useLiveMarks(liveSymbols);
	const livePositions = useMemo(
		() => applyLiveMarksToPositions(realPositions, liveMarks),
		[realPositions, liveMarks],
	);

	// Open positions list (real positions only)
	const visiblePositions = useMemo(() => {
		const src = livePositions ?? realPositions;
		if (!src || src.length === 0) return [];
		return src.map((p: IndexPosition, idx: number): VisiblePosition => {
			const entry = Number(p.entry_price || p.entryPrice || 0);
			const mark = Number(p.mark_price || p.markPrice || entry);
			const size = Number(p.size || 0);
			const pnl = Number(p.pnl || p.unrealizedPnl || 0);
			const side = (p.side || p.direction || "LONG").toUpperCase() as
				| "LONG"
				| "SHORT";
			const pnlPct =
				entry > 0
					? ((mark - entry) / entry) * 100 * (side === "SHORT" ? -1 : 1)
					: 0;
			// Position payloads are untyped JSON: api_key_id may arrive as a
			// number or as a numeric string ("" when no key is bound).
			const apiKeyIdRaw = (p.api_key_id ?? p.apiKeyId ?? null) as
				| number
				| string
				| null;
			const apiKeyId =
				apiKeyIdRaw != null && apiKeyIdRaw !== ""
					? Number(apiKeyIdRaw)
					: undefined;
			const apiKeyEx =
				apiKeyId != null
					? config?.apiKeys?.find((k: ApiKey) => Number(k.id) === apiKeyId)
							?.exchange
					: null;
			const exKey =
				normalizeExchangeKey(p.exchange ?? p.exchange_id) ??
				normalizeExchangeKey(apiKeyEx);

			const displayStrategy = resolvePositionStrategyName(
				{
					symbol: p.symbol,
					api_key_id: apiKeyId,
					config_id: p.config_id,
					strategy: p.strategy,
					strategy_name: p.strategy_name,
				},
				realStrategies,
				nameByConfigId,
			);

			return {
				...p,
				id: p.id || `p-${idx}`,
				symbol: p.symbol || "BTCUSDT",
				side,
				direction: side,
				size,
				entry,
				mark,
				entry_price: entry,
				mark_price: mark,
				leverage: p.leverage || 5,
				pnl,
				pnlPct,
				pnl_percent: pnlPct,
				strategy: displayStrategy,
				strategy_name: displayStrategy,
				exchange: exKey,
				exchange_id: p.exchange ?? p.exchange_id ?? exKey ?? null,
				entryTime: p.entry_time ?? p.entryTime ?? null,
				entry_time: p.entry_time ?? p.entryTime ?? null,
				apiKeyId,
				api_key_id: apiKeyId,
				meta: (exKey && exchangeMeta[exKey]) || null,
			};
		});
	}, [livePositions, realPositions, config, realStrategies, nameByConfigId]);

	// Running strategies (real strategies only; equity sparkline is the
	// cumulative realized PnL built from closed trades, like Analytics).
	// Active = RUNNING/ACTIVE/IN_POSITION or open_positions > 0, then top by PnL.
	const visibleStrategies = useMemo(() => {
		if (!realStrategies || realStrategies.length === 0) return [];
		const isActive = (s: StrategyData) => {
			const st = String(s.status || "").toUpperCase();
			if (
				st === "RUNNING" ||
				st === "ACTIVE" ||
				st === "IN_POSITION" ||
				st === "IN-POSITION"
			)
				return true;
			return Number(s.open_positions ?? 0) > 0;
		};
		const active = realStrategies.filter(isActive);
		const sorted = [...active].sort(
			(a: StrategyData, b: StrategyData) => (Number(b.pnl) || 0) - (Number(a.pnl) || 0),
		);
		const base = sorted.map((s: StrategyData, idx: number): VisibleStrategy => {
			const winRateRaw = s.win_rate;
			const id = s.id || `s-${idx}`;
			const userCustomName =
				(s.config_id && nameByConfigId.get(String(s.config_id))) ||
				(s.id && nameByConfigId.get(String(s.id))) ||
				(s.name &&
				s.name !== "VisualBuilderStrategy" &&
				s.name !== "VisualBuilder" &&
				s.name !== s.strategy_name
					? s.name
					: undefined);
			const name = userCustomName || s.name || s.strategy_name || `Strategy #${idx + 1}`;
			const st = String(s.status || "RUNNING").toUpperCase();
			const status =
				st === "IN_POSITION" || st === "IN-POSITION"
					? ("IN_POSITION" as const)
					: ("RUNNING" as const);
			const runStats = runStatsByInstanceId.get(id);
			return {
				id,
				name,
				strategy_name: s.strategy_name ?? name,
				mode: s.mode ?? null,
				status,
				exchange:
					normalizeExchangeKey(s.exchange ?? s.exchange_id) ?? null,
				apiKeyId: s.api_key_id ?? s.apiKeyId ?? null,
				configId: s.config_id ? String(s.config_id) : null,
				openPositions: Number(s.open_positions ?? 0),
				timeframe:
					(s.config_id && timeframeByConfigId.get(String(s.config_id))) ||
					s.timeframe ||
					"15m",
				trades: runStats
					? runStats.trades
					: (s.trades_count ?? s.total_trades ?? 0),
				winRate:
					runStats && runStats.trades > 0
						? runStats.winRate
						: winRateRaw !== undefined && winRateRaw !== null
							? +(
									Number(winRateRaw) > 1
										? Number(winRateRaw)
										: Number(winRateRaw) * 100
								).toFixed(1)
							: null,
				pnl:
					s.total_pnl !== undefined && s.total_pnl !== null
						? Number(s.total_pnl)
						: s.pnl !== undefined && s.pnl !== null
							? Number(s.pnl)
							: null,
				equity:
					(s.config_id ? strategyEquity.get(String(s.config_id)) : undefined) ??
					strategyEquity.get(name) ??
					strategyEquity.get(s.strategy_name) ??
					strategyEquity.get(id) ??
					[],
			};
		});
		// Live overlay: rebase snapshot PnL by tick delta of its positions,
		// then re-sort so leaders float in realtime like Open Positions.
		const overlaid =
			overlayLiveStrategyPnl(base, realPositions, livePositions) ?? base;
		return [...overlaid].sort(
			(a: VisibleStrategy, b: VisibleStrategy) => (Number(b.pnl) || 0) - (Number(a.pnl) || 0),
		);
	}, [
		realStrategies,
		strategyEquity,
		realPositions,
		livePositions,
		timeframeByConfigId,
		nameByConfigId,
		runStatsByInstanceId,
	]);

	// Live Event Stream
	const [liveEvents, setLiveEvents] = useState<
		Array<{ t: string; level: string; src: string; msg: string }>
	>([]);

	const handleNewImportantLog = useCallback((payload: unknown) => {
		const newEvent = payload as LogEntry;
		if (!newEvent) return;
		const timeStr = new Date(
			newEvent.timestamp || Date.now(),
		).toLocaleTimeString();
		setLiveEvents((prev) =>
			[
				{
					t: timeStr,
					level: newEvent.level || "INFO",
					src: newEvent.component || "engine",
					msg: newEvent.message,
				},
				...prev,
			].slice(0, 30),
		);
	}, []);

	useEffect(() => {
		if (user) {
			const channel = `important_logs:${user.id}`;
			subscribe(channel, handleNewImportantLog);
			return () => {
				unsubscribe(channel, handleNewImportantLog);
			};
		}
	}, [user, subscribe, unsubscribe, handleNewImportantLog]);

	const displayedEvents = useMemo(() => {
		const history = (logHistory || []).slice(0, 30).map((e) => ({
			t: e.timestamp
				? new Date(e.timestamp).toLocaleTimeString()
				: now.toLocaleTimeString(),
			level: e.level || "INFO",
			src: e.component || "engine",
			msg: e.message,
		}));
		return [...liveEvents, ...history].slice(0, 20);
	}, [liveEvents, logHistory, now]);

	// KPI Aggregates (real data only, live marks overlay when available)
	// Equity is scoped to the selected exchange + market (account selector).
	const scopedBalanceAccounts = useMemo(
		() =>
			(balanceAccounts || []).filter((b) =>
				matchesScope({
					apiKeyId: b.apiKeyId,
					exchange: b.exchange,
					marketType: b.marketType,
				}),
			),
		[balanceAccounts, matchesScope],
	);

	const totalEquity = useMemo(() => {
		if (scopeActive) {
			// Scoped: only the selected exchange/market — no global fallback,
			// otherwise the card would show numbers from other accounts.
			return scopedBalanceAccounts.reduce(
				(sum, bal) => sum + (bal.totalEquity || bal.balance || 0),
				0,
			);
		}
		if (balances?.totalEquity && balances.totalEquity > 0) {
			return balances.totalEquity;
		}
		if (portfolioStatus?.balance) {
			const unPnl =
				portfolioStatus.total_unrealized_pnl ||
				portfolioStatus.totalUnrealizedPnl ||
				0;
			return portfolioStatus.balance + unPnl;
		}
		return 0;
	}, [scopeActive, scopedBalanceAccounts, balances, portfolioStatus]);

	const totalPnl = useMemo(() => {
		const src = livePositions ?? realPositions;
		if (src && src.length > 0) {
			return src.reduce(
				(acc: number, p: PositionData) => acc + (Number(p.pnl) || 0),
				0,
			);
		}
		if (balances?.totalUnrealizedPnl !== undefined) {
			return balances.totalUnrealizedPnl;
		}
		return 0;
	}, [livePositions, realPositions, balances]);

	const totalExposure = useMemo(() => {
		const src = livePositions ?? realPositions;
		if (src && src.length > 0) {
			return src.reduce((acc: number, p: PositionData) => {
				const size = Number(p.size) || 0;
				const price = Number(p.mark_price || p.entry_price) || 0;
				return acc + Math.abs(size * price);
			}, 0);
		}
		return 0;
	}, [livePositions, realPositions]);

	const winRate =
		statsSummary.totalTrades > 0 ? +statsSummary.winRate.toFixed(1) : null;

	// Equity curve: Redis history when available, otherwise rebuild from
	// closed trades (TotalPnl pattern). The backend only records history in
	// paper mode, so without this fallback live mode would stay empty.
	const fallbackEquity = useMemo(() => {
		// Redis equity history is stored per user+mode only (not scoped by
		// exchange/market), so when a scope filter is active the curve is
		// rebuilt from scoped closed trades instead (TotalPnl pattern).
		if ((hasHistory && !scopeActive) || periodTrades.length === 0) return [];
		const sorted = [...periodTrades].sort(
			(a, b) =>
				(toCloseMs(a.timestamp_close) ?? 0) -
				(toCloseMs(b.timestamp_close) ?? 0),
		);
		const periodPnl = sorted.reduce((s, t) => s + (Number(t.pnl) || 0), 0);
		const anchor = totalEquity > 0 ? totalEquity - periodPnl : 0;
		let cumulative = anchor;
		return [
			anchor,
			...sorted.map((t) => {
				cumulative += Number(t.pnl) || 0;
				return +cumulative.toFixed(2);
			}),
		];
	}, [hasHistory, scopeActive, periodTrades, totalEquity]);
	const equityValues =
		hasHistory && !scopeActive ? historyValues : fallbackEquity;
	const hasEquity = equityValues.length > 1;
	const first = hasEquity ? equityValues[0] : 0;
	const last = hasEquity ? equityValues[equityValues.length - 1] : 0;
	const chg = first > 0 ? ((last - first) / first) * 100 : 0;
	const maxDdPct = useMemo(
		() => (hasEquity ? maxDrawdownPct(equityValues) : null),
		[hasEquity, equityValues],
	);

	// Risk panel (real settings + open positions)
	const maxConcurrent = config?.riskManagement?.maxConcurrentTrades;
	const defaultSlPct = config?.riskManagement?.defaultStopLossPercent;
	const slotUsage =
		maxConcurrent && maxConcurrent > 0
			? visiblePositions.length / maxConcurrent
			: null;
	const exposureRatio = totalEquity > 0 ? totalExposure / totalEquity : 0;

	return (
		<PageLayout title={t("index:pageTitle", "Quant Command")} hideHeader>
			<div className="space-y-4">
				{/* 1. Top KPI Stat Strip */}
				<div className="grid grid-cols-2 gap-3 xl:grid-cols-5">
					<Stat
						label={t("index:portfolioOverview.equity", "Total Equity")}
						value={fmt.usd(totalEquity, 2)}
						delta={hasEquity ? chg : undefined}
						deltaLabel={hasEquity ? period : undefined}
						spark={hasEquity ? equityValues.slice(-40) : undefined}
						accent="#00d4ff"
						icon={<Wallet size={14} />}
					/>
					<Stat
						label={t("index:portfolioOverview.unrealizedPnl", "Unrealized P&L")}
						value={
							<span className={toneText(totalPnl)}>
								{fmt.usd(totalPnl, 2)}
							</span>
						}
						delta={(totalPnl / (totalEquity || 1)) * 100}
						deltaLabel="of equity"
						accent={toneHex(totalPnl)}
						icon={<Target size={14} />}
					/>
					<Stat
						label={t("index:portfolioOverview.marginUsage", "Exposure")}
						value={fmt.usd(totalExposure, 2)}
						delta={(totalExposure / (totalEquity || 1)) * 100 - 100}
						deltaLabel="vs eq"
						accent="#0066ff"
						icon={<Layers size={14} />}
					/>
					<Stat
						label="Win Rate · 30d"
						value={
							winRate !== null
								? `${winRate}% · ${statsSummary.totalTrades} trades`
								: "no trades yet"
						}
						accent="#10e0a0"
						icon={<Percent size={14} />}
					/>
					<Stat
						label="Sharpe · 30d"
						value={
							statsSummary.sharpeInsufficient
								? "need 2+ days"
								: statsSummary.sharpeRatio.toFixed(2)
						}
						accent="#00d4ff"
						icon={<Gauge size={14} />}
					/>
				</div>

				{/* 2. Middle Grid: Equity Curve & Account Allocation */}
				<div className="grid gap-4 xl:grid-cols-3">
					{/* Equity Curve Panel */}
					<Panel
						className="xl:col-span-2 overflow-visible"
						bodyClassName="overflow-visible"
						title={
							<span className="flex items-center gap-2">
								Equity Curve{" "}
								<Badge tone={mode === "live" ? "loss" : "cyan"} dot pulse>
									{mode}
								</Badge>
							</span>
						}
						subtitle={
							hasEquity
								? `${fmt.usd(last, 2)} · ${fmt.pct(chg)} over ${period.toUpperCase()} · ${scopeLabel}`
								: "no equity history yet"
						}
						actions={
							<Segmented
								size="xs"
								value={period}
								onChange={setPeriod}
								options={[
									{ value: "1d", label: "1D" },
									{ value: "7d", label: "7D" },
									{ value: "mtd", label: "MTD" },
								]}
							/>
						}
						glow
					>
						{isEquityLoading ? (
							<div className="flex h-[240px] items-center justify-center text-[12px] text-white/35">
								Loading equity…
							</div>
						) : hasEquity ? (
							<AreaChart
								data={equityValues}
								height={240}
								color={chg >= 0 ? "#00d4ff" : "#ff3b5c"}
							/>
						) : (
							<div className="flex h-[240px] items-center justify-center text-[12px] text-white/35">
								No equity history for this period yet — it appears
								after closed trades.
							</div>
						)}
						<div className="mt-3 grid grid-cols-4 gap-3 border-t border-white/5 pt-3">
							{[
								[
									"Realized",
									fmt.signed(periodSummary.totalPnl, 2),
									periodSummary.totalPnl >= 0
										? "text-emerald-400"
										: "text-rose-400",
								],
								[
									"Fees",
									periodSummary.totalCommission > 0
										? `-${fmt.usd(periodSummary.totalCommission, 2)}`
										: fmt.usd(0, 2),
									"text-white/60",
								],
								["Funding", "—", "text-white/35"],
								[
									"Max DD",
									maxDdPct !== null
										? `${maxDdPct.toFixed(1)}%`
										: "—",
									"text-rose-400",
								],
							].map(([l, v, c]) => (
								<div key={l}>
									<div className="text-[10px] uppercase tracking-wider text-white/35">
										{l}
									</div>
									<div className={cn("font-mono text-[13px] font-semibold", c)}>
										{v}
									</div>
								</div>
							))}
						</div>
					</Panel>

					{/* Account Allocation Panel */}
					<Panel
						title="Account Allocation"
						subtitle="Multi-exchange · equity share"
					>
						{accountList.length === 0 ? (
							<div className="flex h-[120px] items-center justify-center text-center text-[12px] text-white/35">
								No API keys connected yet — add one in Settings
								to see allocation.
							</div>
						) : (
							<div className="space-y-3">
								{accountList.map((a) => (
								<div
									key={a.id}
									className="flex items-center gap-3 rounded-xl border border-white/5 bg-white/[0.02] p-2.5 hover:border-white/10 transition-colors"
								>
									<Radial
										value={a.share}
										size={46}
										stroke={4}
										color={a.meta.color}
									>
										<ExchangeBadge exchange={a.exchange} size="md" />
									</Radial>
									<div className="flex-1 min-w-0">
										<div className="flex items-center gap-1.5 text-[12px] font-medium text-white truncate">
											{a.name}{" "}
											<span className="text-[9px] uppercase text-white/30">
												{a.marketType}
											</span>
										</div>
										<div className="text-[10px] text-white/40">
											{a.meta.label} · {(a.share * 100).toFixed(1)}% ·{" "}
											<span
												className={
													a.status === "ok"
														? "text-emerald-400"
														: "text-amber-400"
												}
											>
												{a.status}
											</span>
										</div>
									</div>
									<div className="text-right font-mono">
										<div className="text-[12px] text-white">
											{fmt.usd(a.equity, 2)}
										</div>
										<div className={cn("text-[10px]", toneText(a.pnl24h))}>
											{fmt.signed(a.pnl24h, 2)}
										</div>
									</div>
								</div>
							))}
							</div>
						)}
						<div className="mt-3 rounded-xl border border-cyan/15 bg-cyan/[0.04] p-3">
							<div className="flex items-center justify-between text-[10px] uppercase tracking-wider text-cyan/80">
								<span>
									{slotUsage !== null
										? "Position slots used"
										: "Exposure / equity"}
								</span>
								<span className="font-mono">
									{slotUsage !== null
										? `${Math.round(slotUsage * 100)}%`
										: `${Math.round(exposureRatio * 100)}%`}
								</span>
							</div>
							<Bar
								value={Math.max(
									0,
									Math.min(1, slotUsage ?? exposureRatio),
								)}
								className="mt-2"
							/>
							<div className="mt-1.5 text-[10px] text-white/40">
								{slotUsage !== null
									? `${visiblePositions.length} / ${maxConcurrent} max concurrent`
									: `${visiblePositions.length} open positions`}
								{defaultSlPct !== undefined && defaultSlPct !== null
									? ` · default SL ${defaultSlPct}%`
									: ""}
							</div>
						</div>
					</Panel>
				</div>

				{/* 3. Bottom Grid 1: Open Positions & Live Event Stream */}
				<div className="grid gap-4 xl:grid-cols-3">
					{/* Open Positions Panel */}
					<Panel
						title={t("index:activePositions.title", "Open Positions")}
						subtitle={`${visiblePositions.length} active · ${wsLive ? (liveCount > 0 ? "live ticks" : "live") : "polling 5s"} · indicative`}
						className="xl:col-span-2"
						noPad
						actions={
							<Btn
								size="xs"
								variant="ghost"
								icon={<RefreshCw size={11} />}
								onClick={() => refetchPositions()}
							>
								sync
							</Btn>
						}
					>
						<div className="overflow-x-auto">
							<table className="w-full">
								<thead className="border-b border-white/5">
									<tr>
										<Th>{t("index:activePositions.colSymbol", "Symbol")}</Th>
										<Th>{t("index:activePositions.colSide", "Side")}</Th>
										<Th right>{t("index:activePositions.colSize", "Size")}</Th>
										<Th right>
											{t("index:activePositions.colEntry", "Entry")} /{" "}
											{t("index:activePositions.colMark", "Mark")}
										</Th>
										<Th>Trend</Th>
										<Th right>{t("index:activePositions.colPnlUsd", "P&L")}</Th>
										<Th>
											{t("index:activePositions.colStrategy", "Strategy")}
										</Th>
										<Th right className="w-10">Chart</Th>
									</tr>
								</thead>
								<tbody>
									{visiblePositions.length === 0 ? (
										<tr>
											<td colSpan={8}>
												<div className="flex h-[120px] items-center justify-center px-3 py-2.5 text-center text-[12px] text-white/35">
													No open positions — start a
													strategy to see live deals here.
												</div>
											</td>
										</tr>
									) : (
										visiblePositions.map((p) => (
										<tr
											key={p.id}
											onClick={() =>
												navigate(
													`/positions?symbol=${encodeURIComponent(p.symbol)}`,
												)
											}
											className="border-b border-white/[0.03] hover:bg-white/[0.02] transition-colors cursor-pointer"
										>
											<Td>
												<span className="flex items-center gap-2">
													<ExchangeBadge exchange={p.exchange} size="xs" />
													<span className="font-semibold text-white">
														{p.symbol}
													</span>
													<span className="text-[10px] text-white/30">
														{p.leverage}x
													</span>
												</span>
											</Td>
											<Td>
												<Badge tone={p.side === "LONG" ? "profit" : "loss"}>
													{p.side}
												</Badge>
											</Td>
											<Td right mono>
												{p.size}
											</Td>
											<Td right mono>
												<span className="text-white/50">
													{p.entry.toLocaleString()}
												</span>{" "}
												<span className="text-white/25">→</span>{" "}
												{p.mark.toLocaleString()}
											</Td>
										<Td>
											<PositionSparkline
												symbol={p.symbol}
												exchange={p.exchange}
												fallbackPrice={p.mark}
												width={80}
												height={22}
											/>
										</Td>
											<Td right mono>
												<div
													className={cn("font-semibold", toneText(p.pnl))}
												>
													{fmt.signed(p.pnl, 2)}
												</div>
												<div
													className={cn("text-[10px]", toneText(p.pnlPct))}
												>
													{fmt.pct(p.pnlPct)}
												</div>
											</Td>
											<Td>
												<span className="text-foreground/80 dark:text-white/60 text-[11px] font-medium truncate max-w-[150px] block" title={p.strategy}>
													{p.strategy}
												</span>
											</Td>
											<Td right>
												<button
													type="button"
													onClick={(e) => {
														e.stopPropagation();
														setChartPos(p);
														setIsChartOpen(true);
													}}
													className="text-white/40 hover:text-cyan p-1.5 rounded-md hover:bg-white/5 transition-all inline-flex items-center justify-center"
													title="Open Deal Chart"
												>
													<LineChart size={14} />
												</button>
											</Td>
										</tr>
										))
									)}
								</tbody>
							</table>
						</div>
					</Panel>

					{/* Event Stream Panel */}
					<Panel
						title={t("index:liveEventFeed.title", "Event Stream")}
						subtitle="/logs/history · live tail"
						noPad
						actions={
							<Badge tone="profit" dot pulse>
								tail
							</Badge>
						}
					>
						<div className="max-h-[320px] overflow-y-auto font-mono text-[10.5px]">
							{displayedEvents.length === 0 ? (
								<div className="flex h-[120px] items-center justify-center px-4 text-center text-[11px] text-muted-foreground/60 dark:text-white/35">
									No events yet — engine logs will appear here.
								</div>
							) : (
								displayedEvents.map((e, i) => (
								<div
									key={i}
									className="flex flex-col sm:flex-row gap-1 sm:gap-2.5 border-b border-border/40 dark:border-white/[0.03] px-3.5 sm:px-4 py-2 hover:bg-muted/40 dark:hover:bg-white/[0.02] transition-colors"
								>
									<div className="flex items-center gap-2 shrink-0">
										<span className="text-muted-foreground/70 dark:text-white/30 shrink-0 text-[10px] sm:text-[10.5px]">{e.t}</span>
										<span
											className={cn(
												"shrink-0 w-10 font-semibold",
												e.level === "ERROR"
													? "text-rose-500 dark:text-rose-400"
													: e.level === "WARN"
														? "text-amber-500 dark:text-amber-400"
														: "text-cyan-600 dark:text-cyan/80",
											)}
										>
											{e.level}
										</span>
										<span className="text-muted-foreground/80 dark:text-white/35 shrink-0 whitespace-nowrap">
											[{e.src}]
										</span>
									</div>
									<span className="text-foreground/90 dark:text-white/80 flex-1 whitespace-pre-wrap break-words min-w-0 w-full sm:w-auto font-normal leading-relaxed">
										{e.msg}
									</span>
								</div>
								))
							)}
						</div>
					</Panel>
				</div>

				{/* 4. Bottom Grid 2: Strategy Return Heatmap & Active Bots */}
				<div className="grid gap-4 xl:grid-cols-3">
					{/* Strategy Return Heatmap */}
					<Panel
						title="Strategy Return Heatmap"
						subtitle="Hourly P&L% · 30d · all bots"
						className="xl:col-span-2"
					>
						{heatmapRows.length === 0 ? (
							<div className="flex h-[160px] items-center justify-center text-center text-[12px] text-white/35">
								Not enough closed trades yet — the heatmap
								builds from trade history.
							</div>
						) : (
							<Heatmap rows={heatmapRows} />
						)}
					</Panel>

					{/* Active Bots List */}
					<Panel
						title={t("index:topStrategies.title", "Active Bots")}
						subtitle={`/strategies · ${wsLive ? "live push" : "polling 5s"}`}
					>
						{visibleStrategies.length === 0 ? (
							<div className="flex h-[120px] items-center justify-center text-center text-[12px] text-white/35">
								No running strategies — launch one from the
								Strategies page.
							</div>
						) : (
							<div className="space-y-2">
								{visibleStrategies.map((s) => (
									<div
										key={s.id}
										onClick={() => navigate("/strategies")}
										className="flex items-center gap-3 rounded-lg border border-white/5 bg-white/[0.02] px-3 py-2 hover:border-white/10 transition-colors cursor-pointer"
									>
										<span className="relative flex h-2 w-2">
											<span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-50" />
											<span className="relative inline-flex h-2 w-2 rounded-full bg-emerald-400" />
										</span>
										<ExchangeBadge exchange={s.exchange} size="xs" />
										<div className="flex-1 min-w-0">
											<div
												className="truncate text-[12px] font-medium text-white"
												title={
													s.strategy_name && s.strategy_name !== s.name
														? `${s.name} (${s.strategy_name})`
														: s.name
												}
											>
												{s.name}{" "}
												<span className="text-[9px] uppercase text-emerald-400/80">
													{s.status === "IN_POSITION" ? "IN POSITION" : "RUNNING"}
													{s.openPositions > 0
														? ` · ${s.openPositions} pos`
														: ""}
												</span>
											</div>
											<div className="text-[10px] text-white/40">
												{s.timeframe} ·{" "}
												{s.trades > 0
													? `${s.trades} trades · WR ${
															s.winRate !== null ? `${s.winRate}%` : "—"
														}`
													: "no closed trades yet"}
											</div>
										</div>
									{s.equity.length >= 2 ? (
										<Sparkline
											data={s.equity.slice(-30)}
											width={60}
											height={20}
										/>
									) : (
										<span className="w-[60px] text-center font-mono text-[10px] text-white/25">
											—
										</span>
									)}
										<span
											className={cn(
												"font-mono text-[11px] font-semibold w-16 text-right",
												s.pnl !== null ? toneText(s.pnl) : "text-white/35",
											)}
										>
											{s.pnl !== null ? fmt.signed(s.pnl, 2) : "—"}
										</span>
									</div>
								))}
							</div>
						)}
					</Panel>
				</div>
			</div>

			{/* Position Deal Chart Modal (full passthrough: executions + SL/TP rails) */}
			{chartPos && (
				<PositionChartModal
					position={{
						id: String(chartPos.id),
						symbol: chartPos.symbol,
						strategy:
							chartPos.strategy || chartPos.strategy_name || "Quant Engine",
						direction: (
							chartPos.side ||
							chartPos.direction ||
							"LONG"
						).toUpperCase() as "LONG" | "SHORT",
						size: Number(chartPos.size) || 0,
						entry_price:
							Number(chartPos.entry_price ?? chartPos.entry) || 0,
						mark_price:
							Number(
								chartPos.mark_price ??
									chartPos.mark ??
									chartPos.entry_price ??
									chartPos.entry,
							) || 0,
						pnl: Number(chartPos.pnl) || 0,
						pnl_percent:
							Number(chartPos.pnl_percent ?? chartPos.pnlPct) || 0,
						entry_time:
							chartPos.entry_time ||
							chartPos.entryTime ||
							new Date().toISOString(),
						stop_loss:
							chartPos.stop_loss ?? chartPos.sl != null
								? Number(chartPos.stop_loss ?? chartPos.sl)
								: undefined,
						take_profit:
							chartPos.take_profit ?? chartPos.tp != null
								? Number(chartPos.take_profit ?? chartPos.tp)
								: undefined,
						api_key_id: chartPos.api_key_id ?? chartPos.apiKeyId,
						exchange:
							chartPos.exchange ?? chartPos.exchange_id ?? null,
						executions: chartPos.executions ?? [],
						signal_details_json: chartPos.signal_details_json,
						partial_tp_orders: chartPos.partial_tp_orders,
						dca_orders: chartPos.dca_orders,
						market_type: "futures_usdtm",
					} as PositionData}
					isOpen={isChartOpen}
					onClose={() => setIsChartOpen(false)}
					onSave={() => {
						refetchPositions();
						setIsChartOpen(false);
					}}
				/>
			)}
		</PageLayout>
	);
};

export default Index;
