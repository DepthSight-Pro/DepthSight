// pwa/App.tsx

import React, { useState, useCallback, useEffect, useRef } from "react";
import {
	NotificationProvider,
	useNotifications,
} from "./contexts/NotificationContext";
import { Toaster, toast } from "react-hot-toast";
import {
	Screen,
	StrategyConfig,
	BacktestRun,
	DisplayStrategy,
	BacktestRequest,
	BacktestKpiResults,
	StrategyConfigDB,
	StrategyConfigData,
} from "./types";
import { getScreenTitles } from "./constants";
import {
	AreaChart,
	Area,
	XAxis,
	YAxis,
	Tooltip,
	CartesianGrid,
} from "recharts";
import { ICONS } from "./constants";

import Header from "./components/Header";
import BottomNav from "./components/BottomNav";
import FAB from "./components/FAB";
import SideMenu from "./components/SideMenu";
import BacktestModal from "./components/BacktestModal";
import LaunchStrategyModal from "./components/LaunchStrategyModal";
import { ShareBacktestDialog } from "./components/ShareBacktestDialog";
import AuthScreen from "./screens/AuthScreen";
import ConfirmEmailScreen from "./screens/ConfirmEmailScreen";
import ResetPasswordScreen from "./screens/ResetPasswordScreen";
import { useAuth } from "./contexts/AuthContext";
import { useAIChat } from "./contexts/AIChatContext";
import { api } from "./services/api";

import DashboardScreen from "./screens/DashboardScreen";
import StrategiesScreen from "./screens/StrategiesScreen";
import ResearchScreen from "./screens/ResearchScreen";
import NotificationsScreen from "./screens/NotificationsScreen";
import AIChatScreen from "./screens/AIChatScreen";
import EditorHybridScreen from "./screens/EditorHybridScreen";
import ProfileScreen from "./screens/ProfileScreen";
import SettingsScreen from "./screens/SettingsScreen";
import { AIChatProvider } from "./contexts/AIChatContext";
import { SymbolSelectionSettingsProvider } from "./contexts/SymbolSelectionSettingsContext";

import { I18nextProvider, useTranslation } from "react-i18next"; // Import I18nextProvider and useTranslation

interface BacktestResultScreenProps {
	data: BacktestRun | null;
	onRunLive: (data: BacktestRun) => void;
	onAnalyze: (backtestId: string) => void;
	onOpenInEditor: (data: BacktestRun) => void;
	onShare: () => void;
}

const KPICard: React.FC<{
	icon: React.ElementType;
	label: string;
	value: string | number;
	color?: string;
}> = ({ icon: Icon, label, value, color }) => (
	<div className="h-[110px] rounded-xl bg-[hsl(var(--card))] p-4 shadow-sm flex flex-col justify-between">
		<div className="flex items-center justify-between gap-3">
			<div className="w-10 h-10 rounded-full bg-[hsl(var(--secondary))] flex items-center justify-center">
				<Icon className="w-5 h-5 text-[hsl(var(--primary))]" />
			</div>
			<span className="text-xs font-medium text-[hsl(var(--muted-foreground))] whitespace-nowrap overflow-hidden text-ellipsis">
				{label}
			</span>
		</div>
		<div
			className={`text-xl font-semibold whitespace-nowrap overflow-hidden text-ellipsis ${
				color ? color : "text-[hsl(var(--card-foreground))]"
			}`}
		>
			{value}
		</div>
	</div>
);

const EquityChart: React.FC<{ data: { name: string; equity: number }[] }> = ({
	data,
}) => {
	const { t } = useTranslation("pwa-common");
	const [primaryColor, setPrimaryColor] = useState("hsl(217 91% 60%)");

	useEffect(() => {
		const colorValue = getComputedStyle(document.documentElement)
			.getPropertyValue("--primary")
			.trim();
		if (colorValue) {
			const newColor = `hsl(${colorValue})`;
			const timer = setTimeout(() => {
				setPrimaryColor((prev) => (prev !== newColor ? newColor : prev));
			}, 0);
			return () => clearTimeout(timer);
		}
	}, []);

	if (!data || data.length === 0) {
		return (
			<div className="h-56 flex items-center justify-center text-sm text-[hsl(var(--muted-foreground))]">
				{t("backtestResultScreen.noData")}
			</div>
		);
	}

	return (
		<div className="h-56 bg-[hsl(var(--card))] rounded-xl p-4 shadow-sm">
			<AreaChart
				width={300}
				height={200}
				data={data}
				margin={{ top: 5, right: 20, left: -10, bottom: 5 }}
			>
				<defs>
					<linearGradient id="colorEquity" x1="0" y1="0" x2="0" y2="1">
						<stop offset="5%" stopColor={primaryColor} stopOpacity={0.8} />
						<stop offset="95%" stopColor={primaryColor} stopOpacity={0} />
					</linearGradient>
				</defs>
				<CartesianGrid stroke="hsl(var(--border))" strokeDasharray="3 3" />
				<XAxis
					dataKey="name"
					type="category"
					stroke="hsl(var(--border))"
					fontSize={10}
					tickLine={false}
					axisLine={false}
				/>
				<YAxis
					stroke="hsl(var(--muted-foreground))"
					fontSize={10}
					tickLine={false}
					axisLine={false}
					tickFormatter={(value) => `$${Number(value).toLocaleString()}`}
				/>
				<Tooltip
					contentStyle={{
						backgroundColor: "hsl(var(--popover))",
						borderColor: "hsl(var(--border))",
						color: "hsl(var(--popover-foreground))",
						borderRadius: "var(--radius)",
					}}
					cursor={{
						stroke: primaryColor,
						strokeWidth: 1,
						strokeDasharray: "3 3",
					}}
					formatter={(value) => [
						`$${Number(value).toLocaleString()}`,
						"Equity",
					]}
				/>
				<Area
					type="monotone"
					dataKey="equity"
					stroke={primaryColor}
					fillOpacity={1}
					fill="url(#colorEquity)"
				/>
			</AreaChart>
		</div>
	);
};

const BacktestResultScreen: React.FC<BacktestResultScreenProps> = ({
	data,
	onRunLive,
	onAnalyze,
	onOpenInEditor,
	onShare,
}) => {
	const { t } = useTranslation("pwa-common");
	const [tradePage, setTradePage] = useState(1);
	const tradesPerPage = 10;
	const tradeTouchRef = useRef<{ x: number; y: number } | null>(null);

	if (!data) {
		return (
			<div className="p-4 text-center">
				{t("backtestResultScreen.resultsNotFound")}
			</div>
		);
	}

	const kpis: BacktestKpiResults = data.kpi_results_json || {
		total_pnl: 0,
		win_rate: 0,
		max_drawdown: 0,
		sharpe_ratio: 0,
		trades: 0,
	};
	const trades = data.trades || [];

	const totalTradePages = Math.max(1, Math.ceil(trades.length / tradesPerPage));
	const tradeStartIndex = (tradePage - 1) * tradesPerPage;
	const visibleTrades = trades.slice(
		tradeStartIndex,
		tradeStartIndex + tradesPerPage,
	);

	const handlePrevTrades = () => setTradePage((prev) => Math.max(1, prev - 1));
	const handleNextTrades = () =>
		setTradePage((prev) => Math.min(totalTradePages, prev + 1));

	const handleTradesTouchStart = (event: React.TouchEvent<HTMLDivElement>) => {
		const touch = event.touches[0];
		tradeTouchRef.current = { x: touch.clientX, y: touch.clientY };
	};

	const handleTradesTouchEnd = (event: React.TouchEvent<HTMLDivElement>) => {
		if (!tradeTouchRef.current) return;
		const touch = event.changedTouches[0];
		const deltaX = touch.clientX - tradeTouchRef.current.x;
		const deltaY = touch.clientY - tradeTouchRef.current.y;
		tradeTouchRef.current = null;
		if (Math.abs(deltaX) < 40 || Math.abs(deltaX) < Math.abs(deltaY)) return;
		if (deltaX < 0) handleNextTrades();
		else handlePrevTrades();
	};

	const equityRaw = (() => {
		if (
			Array.isArray(data.equity_curve_json) &&
			data.equity_curve_json.length > 0
		)
			return data.equity_curve_json;
		const maybeExtended = data as BacktestRun & {
			equity_curve?: [string | number, number][];
		};
		if (
			Array.isArray(maybeExtended.equity_curve) &&
			maybeExtended.equity_curve.length > 0
		)
			return maybeExtended.equity_curve;
		const params = data.parameters_json as Record<string, unknown>;
		if (params) {
			const paramEquityJson = params?.equity_curve_json;
			if (Array.isArray(paramEquityJson) && paramEquityJson.length > 0)
				return paramEquityJson as [string | number, number][];
			const paramEquity = params?.equity_curve;
			if (Array.isArray(paramEquity) && paramEquity.length > 0)
				return paramEquity as [string | number, number][];
		}
		return [] as [string | number, number][];
	})();

	const equityCurve = equityRaw
		.filter(
			(point: unknown): point is [string | number, number] =>
				Array.isArray(point) && point.length >= 2,
		)
		.map(([timestamp, value]: [string | number, number]) => {
			return {
				name: new Date(timestamp).toLocaleDateString(undefined, {
					month: "short",
					day: "numeric",
				}),
				equity: typeof value === "number" ? value : Number(value) || 0,
			};
		});

	const pnl = kpis.total_pnl || 0;
	const pnlPositive = pnl >= 0;

	return (
		<div className="p-4 animate-fadeIn">
			<div className="bg-[hsl(var(--card))] rounded-xl p-4 mb-4 shadow-sm">
				<h2 className="text-lg font-medium text-[hsl(var(--card-foreground))]">
					{data.strategy_name}
				</h2>
				<p className="text-sm text-[hsl(var(--muted-foreground))]">
					{data.symbol} • {new Date(data.start_date).toLocaleDateString()} -{" "}
					{new Date(data.end_date).toLocaleDateString()}
				</p>
			</div>
			<div className="grid grid-cols-2 gap-3 mb-4">
				<KPICard
					icon={ICONS.Dollar}
					label={t("research.netPnl")}
					value={`$${pnl.toLocaleString()}`}
					color={
						pnlPositive
							? "text-[hsl(var(--profit))]"
							: "text-[hsl(var(--loss))]"
					}
				/>
				<KPICard
					icon={ICONS.Percent}
					label={t("research.winRate")}
					value={`${(kpis.win_rate || 0).toFixed(2)}%`}
				/>
				<KPICard
					icon={ICONS.TrendingDown}
					label={t("dashboard.maxDrawdown")}
					value={`${(kpis.max_drawdown || 0).toFixed(2)}%`}
					color="text-[hsl(var(--loss))]"
				/>
				<KPICard
					icon={ICONS.Star}
					label={t("dashboard.sharpeRatio")}
					value={(kpis.sharpe_ratio || 0).toFixed(2)}
				/>
			</div>
			<div className="mb-4">
				<h3 className="text-base font-medium text-[hsl(var(--foreground))] mb-2">
					{t("backtestResultScreen.equityChart")}
				</h3>
				<EquityChart data={equityCurve} />
			</div>
			<div className="grid grid-cols-2 gap-3 mb-4">
				<button
					onClick={() => data && onOpenInEditor(data)}
					className="py-3 rounded-full border border-[hsl(var(--primary))] text-sm font-medium text-[hsl(var(--primary))] transition hover:bg-[hsl(var(--accent))]"
				>
					{t("backtestResultScreen.openInEditor")}
				</button>
				<button
					onClick={() => data && onAnalyze(data.id)}
					className="py-3 rounded-full border border-[hsl(var(--primary))] text-sm font-medium text-[hsl(var(--primary))] transition hover:bg-[hsl(var(--accent))]"
				>
					{t("backtestResultScreen.analyzeWithAI")}
				</button>
				<button
					onClick={onShare}
					className="py-3 rounded-full border border-[hsl(var(--primary))] text-sm font-medium text-[hsl(var(--primary))] transition hover:bg-[hsl(var(--accent))]"
				>
					{t("backtestResultScreen.share")}
				</button>
				<button
					onClick={() => data && onRunLive(data)}
					className="col-span-2 py-3 rounded-full border-none text-sm font-medium bg-[hsl(var(--primary))] text-[hsl(var(--primary-foreground))] transition hover:opacity-90"
				>
					{t("backtestResultScreen.runLive")}
				</button>
			</div>
			<div
				onTouchStart={handleTradesTouchStart}
				onTouchEnd={handleTradesTouchEnd}
			>
				<h3 className="text-base font-medium text-[hsl(var(--foreground))] mb-2">
					{t("backtestResultScreen.trades")}
				</h3>
				<div className="bg-[hsl(var(--card))] rounded-xl shadow-sm overflow-hidden">
					<div className="divide-y divide-[hsl(var(--border))]">
						{visibleTrades.length > 0 ? (
							visibleTrades.map((trade) => {
								const tradePnlPositive = trade.pnl >= 0;
								return (
									<div
										key={trade.id}
										className="p-3 flex justify-between items-center"
									>
										<div>
											<div className="font-medium text-sm text-[hsl(var(--card-foreground))]">
												{trade.side === "LONG"
													? t("backtestResultScreen.buy")
													: t("backtestResultScreen.sell")}{" "}
												@ ${trade.entry_price.toLocaleString()}
											</div>
											<div className="text-xs text-[hsl(var(--muted-foreground))]">
												{t("backtestResultScreen.exit")} @ $
												{trade.exit_price.toLocaleString()}
											</div>
										</div>
										<div className="text-right">
											<div
												className={`font-medium text-sm ${tradePnlPositive ? "text-[hsl(var(--profit))]" : "text-[hsl(var(--loss))]"}`}
											>
												{tradePnlPositive ? "+" : ""}$
												{trade.pnl.toLocaleString(undefined, {
													minimumFractionDigits: 2,
													maximumFractionDigits: 2,
												})}
											</div>
											<div className="text-xs text-[hsl(var(--muted-foreground))]">
												{tradePnlPositive ? "+" : ""}
												{(trade.pnl_percent || 0).toFixed(2)}%
											</div>
										</div>
									</div>
								);
							})
						) : (
							<div className="p-4 text-center text-sm text-[hsl(var(--muted-foreground))]">
								{t("backtestResultScreen.tradesNotFound")}
							</div>
						)}
					</div>
				</div>
				{trades.length > tradesPerPage && (
					<div className="mt-3 flex items-center justify-between gap-3">
						<button
							onClick={handlePrevTrades}
							className="flex-1 rounded-lg bg-[hsl(var(--secondary))] px-3 py-2 text-sm text-[hsl(var(--secondary-foreground))] transition hover:opacity-90 disabled:opacity-50"
							disabled={tradePage === 1}
						>
							{t("backtestResultScreen.back")}
						</button>
						<div className="text-sm text-[hsl(var(--muted-foreground))] text-center">
							{t("backtestResultScreen.page")} {tradePage} / {totalTradePages}
						</div>
						<button
							onClick={handleNextTrades}
							className="flex-1 rounded-lg bg-[hsl(var(--secondary))] px-3 py-2 text-sm text-[hsl(var(--secondary-foreground))] transition hover:opacity-90 disabled:opacity-50"
							disabled={tradePage === totalTradePages}
						>
							{t("backtestResultScreen.forward")}
						</button>
					</div>
				)}
			</div>
		</div>
	);
};

const MainAppLayout = () => {
	const { t } = useTranslation("pwa-common");
	const [theme, setTheme] = useState<"light" | "dark">("dark");
	const [activeScreen, setActiveScreen] = useState<Screen>(Screen.Dashboard);
	const [previousScreen, setPreviousScreen] = useState<Screen | null>(null);
	const { user } = useAuth();
	const { addNotification } = useNotifications();
	const { setBacktestId } = useAIChat();
	const screenTitles = getScreenTitles(t);
	const wsRef = useRef<WebSocket | null>(null);
	const reconnectTimeoutRef = useRef<number | null>(null);
	const effectRan = useRef(false);

	useEffect(() => {
		if (!user?.id) return;
		if (effectRan.current === true) return;
		effectRan.current = true;

		let isCleaningUp = false;
		const connectWebSocket = () => {
			const wsProtocol = window.location.protocol === "https" ? "wss:" : "ws:";
			const WS_URL =
				wsProtocol === "wss:" && import.meta.env.VITE_WS_URL
					? import.meta.env.VITE_WS_URL.replace("ws:", "wss:")
					: import.meta.env.VITE_WS_URL ||
						`${wsProtocol}//${window.location.host}`;

			const authTokenString = localStorage.getItem("authToken");
			if (!authTokenString) return;
			let accessToken: string;
			try {
				accessToken = JSON.parse(authTokenString).access_token;
			} catch (e) {
				console.error("Failed to parse auth token", e);
				return;
			}
			const websocket = new WebSocket(
				`${WS_URL}/ws?token=${encodeURIComponent(accessToken)}`,
			);
			wsRef.current = websocket;
			websocket.onopen = () => {
				websocket.send(
					JSON.stringify({ action: "subscribe", channel: `user:${user.id}` }),
				);
			};
			websocket.onmessage = (event) => {
				const message = JSON.parse(event.data);
				const eventType = message.payload?.event_type || message.event_type;
				const eventData = message.payload?.data || message.data;
				if (eventType === "achievement_unlocked") {
					const localizedName = t(`achievements.list.${eventData.id}.name`, {
						defaultValue: eventData.name,
					}) as string;
					const notif = {
						type: "achievement" as const,
						title: t("notification.achievementUnlocked") as string,
						subtitle: localizedName,
						icon: "🏆",
						bgColor: "bg-yellow-500",
						navigationData: { screen: "Profile" as const },
					};
					toast.success(notif.subtitle);
					addNotification(notif);
				} else if (eventType === "backtest_completed") {
					const notif = {
						type: "backtest" as const,
						title: t("notification.backtestCompleted") as string,
						subtitle: `${eventData.strategy_name}`,
						icon: "✓",
						bgColor: "bg-green-500",
						navigationData: {
							screen: "BacktestResult" as const,
							params: { backtestId: eventData.run_id || eventData.id },
						},
					};
					toast.success(notif.title);
					addNotification(notif);
				}
			};
			websocket.onclose = () => {
				if (!isCleaningUp)
					reconnectTimeoutRef.current = window.setTimeout(
						connectWebSocket,
						5000,
					);
			};
			websocket.onerror = (error) => console.error("WebSocket Error:", error);
		};
		connectWebSocket();

		return () => {
			isCleaningUp = true;
			if (reconnectTimeoutRef.current)
				clearTimeout(reconnectTimeoutRef.current);
			if (wsRef.current) wsRef.current.close();
			effectRan.current = false;
		};
	}, [user?.id, addNotification, t]);

	const [strategyToEdit, setStrategyToEdit] =
		useState<Partial<StrategyConfigDB> | null>(null);
	const [isMenuOpen, setIsMenuOpen] = useState(false);
	const [isBacktestModalOpen, setIsBacktestModalOpen] = useState(false);
	const [strategyForBacktest, setStrategyForBacktest] =
		useState<DisplayStrategy | null>(null);
	const [selectedBacktestId, setSelectedBacktestId] = useState<string | null>(
		null,
	);
	const [selectedBacktest, setSelectedBacktest] = useState<BacktestRun | null>(
		null,
	);
	const [isLaunchModalOpen, setIsLaunchModalOpen] = useState(false);
	const [backtestForLaunch, setBacktestForLaunch] =
		useState<BacktestRun | null>(null);
	const [isShareDialogOpen, setIsShareDialogOpen] = useState(false);

	useEffect(() => {
		document.documentElement.className = theme;
	}, [theme]);

	const handleBack = useCallback(() => {
		const fromScreen = activeScreen;
		const defaultBackMap: Partial<Record<Screen, Screen>> = {
			[Screen.BacktestResult]: Screen.Research,
			[Screen.Editor]: Screen.Strategies,
			[Screen.AIChat]: Screen.Dashboard,
			[Screen.Profile]: Screen.Dashboard,
			[Screen.Settings]: Screen.Dashboard,
		};
		const targetScreen =
			previousScreen || defaultBackMap[fromScreen] || Screen.Dashboard;

		setActiveScreen(targetScreen);
		setPreviousScreen(null);

		if (fromScreen === Screen.Editor) setStrategyToEdit(null);
	}, [activeScreen, previousScreen]);

	useEffect(() => {
		const fetchBacktestDetails = async () => {
			if (
				activeScreen === Screen.BacktestResult &&
				selectedBacktestId &&
				(!selectedBacktest || selectedBacktest.id !== selectedBacktestId)
			) {
				try {
					const result = await api.getBacktestDetails(selectedBacktestId);
					setSelectedBacktest(result);
				} catch {
					toast.error(t("backtestResultScreen.toast.failedToLoadDetails"));
					handleBack();
				}
			}
		};
		fetchBacktestDetails();
	}, [activeScreen, selectedBacktestId, selectedBacktest, t, handleBack]);

	const toggleTheme = useCallback(
		() => setTheme((current) => (current === "light" ? "dark" : "light")),
		[],
	);

	const handleNavigate = useCallback(
		(screen: Screen) => {
			setPreviousScreen(activeScreen);
			if (activeScreen === Screen.Editor) setStrategyToEdit(null);
			setActiveScreen(screen);
		},
		[activeScreen],
	);

	const openMenu = useCallback(() => setIsMenuOpen(true), []);
	const closeMenu = useCallback(() => setIsMenuOpen(false), []);

	const handleStrategyGenerated = useCallback(
		(config: Partial<StrategyConfig>) => {
			setStrategyToEdit(config);
			handleNavigate(Screen.Editor);
		},
		[handleNavigate],
	);

	const handleEditStrategy = useCallback(
		(strategy: DisplayStrategy) => {
			setStrategyToEdit(strategy as Partial<StrategyConfigDB>);
			handleNavigate(Screen.Editor);
		},
		[handleNavigate],
	);

	const handleNewStrategy = useCallback(() => {
		setStrategyToEdit(null);
		handleNavigate(Screen.Editor);
	}, [handleNavigate]);

	const handleInitiateBacktest = useCallback((strategy: DisplayStrategy) => {
		setStrategyForBacktest(strategy);
		setIsBacktestModalOpen(true);
	}, []);

	const handleRunBacktest = useCallback(
		async (details: { symbol: string; startDate: string; endDate: string }) => {
			if (!strategyForBacktest) return;
			try {
				const configData = strategyForBacktest.config_data as Record<
					string,
					unknown
				>;
				const config = (configData?.config_data || strategyForBacktest.config_data) as StrategyConfigData;
				const request: BacktestRequest = {
					strategy_name: strategyForBacktest.name,
					symbol: details.symbol,
					start_date: new Date(details.startDate).toISOString(),
					end_date: new Date(details.endDate).toISOString(),
					market_type: "futures",
					params: { config, initial_balance: 10000 },
				};
				await api.runBacktest(request);
				setIsBacktestModalOpen(false);
				setStrategyForBacktest(null);
				toast.success(t("backtestResultScreen.toast.backtestStarted"));
				handleNavigate(Screen.Research);
			} catch {
				toast.error(t("backtestResultScreen.toast.errorStartingBacktest"));
			}
		},
		[strategyForBacktest, handleNavigate, t],
	);

	const handleViewResult = useCallback(
		(runId: string) => {
			setSelectedBacktestId(runId);
			handleNavigate(Screen.BacktestResult);
		},
		[handleNavigate],
	);

	const handleRunLive = useCallback((data: BacktestRun) => {
		setBacktestForLaunch(data);
		setIsLaunchModalOpen(true);
	}, []);

	const handleAnalyzeWithAI = (backtestId: string) => {
		setBacktestId(backtestId);
		handleNavigate(Screen.AIChat);
	};

	const handleOpenInEditorFromBacktest = useCallback(
		(backtestRun: BacktestRun) => {
			const config =
				(backtestRun.parameters_json.config || backtestRun.parameters_json) as StrategyConfigData;
			setStrategyToEdit({
				name: `${backtestRun.strategy_name} (from backtest)`,
				config_data: config,
			});
			handleNavigate(Screen.Editor);
		},
		[handleNavigate],
	);

	const handleShare = () => {
		setIsShareDialogOpen(true);
	};

	const handleConfirmLaunch = useCallback(
		async (details: {
			mode: "live" | "paper";
			symbolSelectionMode: "STATIC" | "DYNAMIC";
			symbols?: string;
		}) => {
			if (!backtestForLaunch) return;
			try {
				const strategyName = `${backtestForLaunch.strategy_name} (from backtest)`;
				const configData =
					(backtestForLaunch.parameters_json.config ||
					backtestForLaunch.parameters_json) as StrategyConfigData;
				const savedStrategy = await api.saveStrategy({
					name: strategyName,
					description: `Strategy from backtest ${backtestForLaunch.id}`,
					config_data: configData
				});
				const symbolsArray =
					details.symbolSelectionMode === "STATIC" && details.symbols
						? details.symbols
								.split(",")
								.map((s) => s.trim())
								.filter(Boolean)
						: [];
				await api.startStrategy(
					savedStrategy.id,
					details.mode,
					details.symbolSelectionMode,
					symbolsArray.length > 0 ? symbolsArray : undefined,
				);
				toast.success(
					t("backtestResultScreen.toast.strategySavedAndLaunched", {
						strategyName,
					}),
				);
				setIsLaunchModalOpen(false);
				setBacktestForLaunch(null);
				handleNavigate(Screen.Strategies);
			} catch {
				toast.error(t("backtestResultScreen.toast.errorLaunchingStrategy"));
			}
		},
		[backtestForLaunch, handleNavigate, t],
	);

	const handleNotificationNavigate = useCallback(
		(screen: Screen, params?: { backtestId?: string }) => {
			if (screen === Screen.BacktestResult && params?.backtestId)
				setSelectedBacktestId(params.backtestId);
			handleNavigate(screen);
		},
		[handleNavigate],
	);

	const renderScreen = () => {
		switch (activeScreen) {
			case Screen.Dashboard:
				return <DashboardScreen />;
			case Screen.Strategies:
				return (
					<StrategiesScreen
						onInitiateBacktest={handleInitiateBacktest}
						onEditStrategy={handleEditStrategy}
					/>
				);
			case Screen.Research:
				return <ResearchScreen onViewResult={handleViewResult} />;
			case Screen.Notifications:
				return <NotificationsScreen onNavigate={handleNotificationNavigate} />;
			case Screen.AIChat:
				return <AIChatScreen onStrategyGenerated={handleStrategyGenerated} />;
			case Screen.Editor:
				return <EditorHybridScreen strategyToEdit={strategyToEdit} />;
			case Screen.BacktestResult:
				return (
					<BacktestResultScreen
						key={selectedBacktest?.id || "no-backtest"}
						data={selectedBacktest}
						onRunLive={handleRunLive}
						onAnalyze={handleAnalyzeWithAI}
						onOpenInEditor={handleOpenInEditorFromBacktest}
						onShare={handleShare}
					/>
				);
			case Screen.Profile:
				return <ProfileScreen />;
			case Screen.Settings:
				return <SettingsScreen />;
			default:
				return <DashboardScreen />;
		}
	};

	const showBottomNav = [
		Screen.Dashboard,
		Screen.Strategies,
		Screen.Research,
		Screen.Notifications,
	].includes(activeScreen);
	const showBackButton = ![
		Screen.Dashboard,
		Screen.Strategies,
		Screen.Research,
		Screen.Notifications,
	].includes(activeScreen);

	return (
		<div className="relative h-full w-full max-w-md flex flex-col bg-[hsl(var(--background))] shadow-2xl">
			<SideMenu
				isOpen={isMenuOpen}
				onClose={closeMenu}
				theme={theme}
				onToggleTheme={toggleTheme}
				onNavigate={handleNavigate}
			/>
			<Header
				title={screenTitles[activeScreen] || t("header.depthsightAI")}
				onMenuClick={openMenu}
				showBackButton={showBackButton}
				onBackClick={handleBack}
			/>
			<main className="flex-1 overflow-y-auto min-h-0">{renderScreen()}</main>
			{showBottomNav && (
				<BottomNav activeScreen={activeScreen} onNavigate={handleNavigate} />
			)}
			{activeScreen === Screen.Strategies && (
				<FAB onClick={handleNewStrategy} />
			)}
			<BacktestModal
				isOpen={isBacktestModalOpen}
				onClose={() => setIsBacktestModalOpen(false)}
				onSubmit={handleRunBacktest}
				strategy={strategyForBacktest}
			/>
			<LaunchStrategyModal
				isOpen={isLaunchModalOpen}
				onClose={() => {
					setIsLaunchModalOpen(false);
					setBacktestForLaunch(null);
				}}
				onSubmit={handleConfirmLaunch}
				strategy={
					backtestForLaunch
						? {
								id: backtestForLaunch.id,
								name: backtestForLaunch.strategy_name,
								config_data: (backtestForLaunch.parameters_json.config ||
									backtestForLaunch.parameters_json) as StrategyConfigData,
								symbol_selection_mode: "STATIC",
								symbols: [backtestForLaunch.symbol],
								created_at: backtestForLaunch.created_at,
								updated_at: backtestForLaunch.created_at,
								isRunning: false,
							}
						: null
				}
			/>
			{selectedBacktest && (
				<ShareBacktestDialog
					open={isShareDialogOpen}
					onOpenChange={setIsShareDialogOpen}
					runId={selectedBacktest.id}
				/>
			)}
		</div>
	);
};

const App: React.FC = () => {
	const { user, isLoading } = useAuth();
	const [confirmToken, setConfirmToken] = useState<string | null>(null);
	const [resetToken, setResetToken] = useState<string | null>(null);
	const { i18n } = useTranslation();

	// Sync HTML lang attribute
	useEffect(() => {
		document.documentElement.lang = i18n.language;
	}, [i18n.language]);

	// Check for email confirmation or reset password token in URL
	useEffect(() => {
		const path = window.location.pathname;
		console.log("[App] Current path:", path);

		// Match /confirm-email/{token}
		const confirmMatch = path.match(/(?:\/pwa)?\/confirm-email\/([^/]+)/);
		if (confirmMatch && confirmMatch[1]) {
			console.log(
				"[App] Found confirmation token in URL:",
				confirmMatch[1].substring(0, 10) + "...",
			);
			const timer = setTimeout(() => {
				setConfirmToken(confirmMatch[1]);
			}, 0);
			return () => clearTimeout(timer);
		}
		console.log("[App] No confirmation token found in URL");

		// Match /reset-password/{token}
		const resetMatch = path.match(/(?:\/pwa)?\/reset-password\/([^/]+)/);
		if (resetMatch && resetMatch[1]) {
			console.log(
				"[App] Found reset password token in URL:",
				resetMatch[1].substring(0, 10) + "...",
			);
			const timer = setTimeout(() => {
				setResetToken(resetMatch[1]);
			}, 0);
			return () => clearTimeout(timer);
		}
	}, []);

	// While loading, return null.
	// React will not render anything, and the screen will keep
	// the perfect HTML loader from index.html.
	if (isLoading) {
		return null;
	}

	// If there's a confirmation token, show confirmation screen
	// Note: We need AuthProvider here to use setAuthToken
	if (confirmToken && !isLoading) {
		return (
			<I18nextProvider i18n={i18n}>
				<div className="h-full w-full flex justify-center overflow-hidden">
					<ConfirmEmailScreen
						token={confirmToken}
						onComplete={() => {
							console.log(
								"[App] Confirmation complete, clearing token and URL",
							);
							setConfirmToken(null);
							const basePath = import.meta.env.BASE_URL || "/";
							window.history.replaceState({}, "", basePath);
						}}
					/>
					<Toaster
						toastOptions={{
							style: {
								background: "hsl(var(--card))",
								color: "hsl(var(--card-foreground))",
								border: "1px solid hsl(var(--border))",
							},
						}}
					/>
				</div>
			</I18nextProvider>
		);
	}

	// If there's a reset password token, show reset screen
	if (resetToken && !isLoading) {
		return (
			<I18nextProvider i18n={i18n}>
				<div className="h-full w-full flex justify-center overflow-hidden">
					<ResetPasswordScreen
						token={resetToken}
						onComplete={() => {
							console.log("[App] Reset complete, clearing token and URL");
							setResetToken(null);
							const basePath = import.meta.env.BASE_URL || "/";
							window.history.replaceState({}, "", basePath);
						}}
					/>
					<Toaster
						toastOptions={{
							style: {
								background: "hsl(var(--card))",
								color: "hsl(var(--card-foreground))",
								border: "1px solid hsl(var(--border))",
							},
						}}
					/>
				</div>
			</I18nextProvider>
		);
	}

	return (
		<I18nextProvider i18n={i18n}>
			<div className="h-full w-full flex justify-center overflow-hidden">
				{user ? (
					<NotificationProvider>
						<AIChatProvider>
							<SymbolSelectionSettingsProvider>
								<MainAppLayout />
							</SymbolSelectionSettingsProvider>
						</AIChatProvider>
					</NotificationProvider>
				) : (
					<AuthScreen />
				)}
				<Toaster
					toastOptions={{
						style: {
							background: "hsl(var(--card))",
							color: "hsl(var(--card-foreground))",
							border: "1px solid hsl(var(--border))",
						},
					}}
				/>
			</div>
		</I18nextProvider>
	);
};

export default App;
