// pwa/screens/DashboardScreen.tsx

import type { TFunction } from "i18next";
import type React from "react";
import { useEffect, useMemo, useState } from "react";
import { toast } from "react-hot-toast";
import { useTranslation } from "react-i18next";
import { useSwipeable } from "react-swipeable";
import {
	Area,
	AreaChart,
	CartesianGrid,
	ResponsiveContainer,
	Tooltip,
	XAxis,
	YAxis,
} from "recharts";
import { Logo } from "../components/ui/logo";
import { ICONS } from "../constants";
import { useLiveMarks } from "../hooks/useLiveMarks";
import { applyLiveMarksToPositions, readExchangeOf } from "../lib/livePnl";
import { api, hasUsableAuthToken } from "../services/api";
import { useAccountStore } from "../stores/accountStore";
import { useRealtimeStore } from "../stores/realtimeStore";
import type { PortfolioStatus } from "../types";

type PnlPeriod = "1d" | "7d" | "mtd";

interface EquityPoint {
	name: string;
	equity: number;
}

/** Thin raw [ts, balance] history to labeled equity points (desktop pattern). */
const transformEquityCurve = (
	equityCurve: [number, number][],
	period: PnlPeriod,
	maxPoints = 200,
): EquityPoint[] => {
	if (!equityCurve || equityCurve.length === 0) return [];
	const step = Math.max(1, Math.ceil(equityCurve.length / maxPoints));
	const out: EquityPoint[] = [];
	for (let i = 0; i < equityCurve.length; i += step) {
		const [ts, balance] = equityCurve[i];
		const d = new Date(ts);
		const name =
			period === "1d"
				? d.toLocaleTimeString(undefined, {
						hour: "2-digit",
						minute: "2-digit",
					})
				: d.toLocaleDateString(undefined, {
						day: "2-digit",
						month: "2-digit",
					});
		out.push({ name, equity: Number(balance) || 0 });
	}
	// Always end on the latest point.
	const [lastTs, lastBal] = equityCurve[equityCurve.length - 1];
	const lastD = new Date(lastTs);
	const lastName =
		period === "1d"
			? lastD.toLocaleTimeString(undefined, {
					hour: "2-digit",
					minute: "2-digit",
				})
			: lastD.toLocaleDateString(undefined, {
					day: "2-digit",
					month: "2-digit",
				});
	if (out.length === 0 || out[out.length - 1].name !== lastName) {
		out.push({ name: lastName, equity: Number(lastBal) || 0 });
	}
	return out;
};

/** Max drawdown in percent over equity values. */
const maxDrawdownPct = (values: number[]): number | null => {
	if (values.length < 2) return null;
	let peak = values[0];
	let maxDd = 0;
	for (const v of values) {
		if (v > peak) peak = v;
		if (peak > 0) maxDd = Math.min(maxDd, (v - peak) / peak);
	}
	return Math.abs(maxDd) * 100;
};

/** Backend serializes trade timestamps as ISO strings (like the web client). */
const toCloseMs = (v: unknown): number | null => {
	if (v === null || v === undefined) return null;
	if (typeof v === "number") return v > 1_000_000_000_000 ? v : v * 1000;
	const ms = new Date(v as string).getTime();
	return Number.isFinite(ms) ? ms : null;
};

/** Rebuild equity curve from closed trades when history is missing (desktop TotalPnl pattern). */
const rebuildEquityFromTrades = (
	trades: { timestamp_close: number | string; pnl: number }[],
	anchorEquity: number,
): [number, number][] => {
	const sorted = [...trades].sort(
		(a, b) => (toCloseMs(a.timestamp_close) ?? 0) - (toCloseMs(b.timestamp_close) ?? 0),
	);
	const periodPnl = sorted.reduce((s, t) => s + (Number(t.pnl) || 0), 0);
	let cumulative = anchorEquity > 0 ? anchorEquity - periodPnl : 0;
	const startTs =
		sorted.length > 0
			? (toCloseMs(sorted[0].timestamp_close) ?? Date.now())
			: Date.now();
	const out: [number, number][] = [[startTs, +cumulative.toFixed(2)]];
	for (const tr of sorted) {
		cumulative += Number(tr.pnl) || 0;
		out.push([toCloseMs(tr.timestamp_close) ?? startTs, +cumulative.toFixed(2)]);
	}
	return out;
};

/** Full equity view (desktop pattern): curve + realized/fees/maxDD. */
const computeEquityView = (
	equityRes: [number, number][] | null,
	allTrades: {
		timestamp_close: number | string;
		pnl: number;
		commission?: number;
	}[],
	balance: number,
	periodStartMs: number,
	period: PnlPeriod,
): {
	points: EquityPoint[];
	realized: number;
	fees: number;
	maxDd: number | null;
} => {
	const periodTrades = (allTrades || []).filter((tr) => {
		const closeMs = toCloseMs(tr.timestamp_close);
		return closeMs !== null && closeMs >= periodStartMs;
	});
	const realized = periodTrades.reduce((s, tr) => s + (Number(tr.pnl) || 0), 0);
	const fees = periodTrades.reduce(
		(s, tr) => s + (Number(tr.commission) || 0),
		0,
	);
	let curve: [number, number][] = equityRes || [];
	if (curve.length <= 1) {
		// No history (e.g. live mode): rebuild from closed trades.
		curve = rebuildEquityFromTrades(
			periodTrades.map((tr) => ({
				timestamp_close: tr.timestamp_close,
				pnl: tr.pnl,
			})),
			balance,
		);
	}
	const values = curve.map(([, v]) => Number(v) || 0);
	return {
		points: values.length > 1 ? transformEquityCurve(curve, period) : [],
		realized,
		fees,
		maxDd: maxDrawdownPct(values),
	};
};

const PnlChart: React.FC<{
	data: EquityPoint[];
	positive: boolean;
	t: TFunction;
}> = ({ data, positive, t }) => {
	if (!data || data.length === 0) {
		return (
			<div className="h-52 flex items-center justify-center text-sm text-[hsl(var(--muted-foreground))]">
				{t("dashboard.noDataToDisplay")}
			</div>
		);
	}

	const stroke = positive ? "#00d4ff" : "#ff3b5c";
	const gradientId = positive ? "colorEquityUp" : "colorEquityDown";

	return (
		<div className="h-52 bg-[hsl(var(--secondary))] rounded-lg p-2">
			<ResponsiveContainer width="100%" height="100%">
				<AreaChart
					data={data}
					margin={{ top: 5, right: 20, left: -10, bottom: 5 }}
				>
					<defs>
						<linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
							<stop offset="5%" stopColor={stroke} stopOpacity={0.5} />
							<stop offset="95%" stopColor={stroke} stopOpacity={0} />
						</linearGradient>
					</defs>
					<CartesianGrid
						stroke="hsl(var(--border))"
						strokeDasharray="3 3"
						vertical={false}
					/>
					<XAxis
						dataKey="name"
						stroke="hsl(var(--muted-foreground))"
						fontSize={12}
						tickLine={false}
						axisLine={false}
						minTickGap={32}
					/>
					<YAxis
						stroke="hsl(var(--muted-foreground))"
						fontSize={12}
						tickLine={false}
						axisLine={false}
						tickFormatter={(value) => `$${value}`}
						domain={["auto", "auto"]}
					/>
					<Tooltip
						wrapperStyle={{ outline: "none", border: "none" }}
						contentStyle={{
							backgroundColor: "hsl(var(--popover))",
							border: "1px solid hsl(var(--border))",
							color: "hsl(var(--popover-foreground))",
							borderRadius: "var(--radius)",
							outline: "none",
						}}
						cursor={{ fill: "hsla(var(--primary), 0.2)" }}
						formatter={(value: number) => [
							`$${value.toFixed(2)}`,
							t("dashboard.equityCurve", "Equity"),
						]}
					/>
					<Area
						type="monotone"
						dataKey="equity"
						stroke={stroke}
						strokeWidth={2}
						fillOpacity={1}
						fill={`url(#${gradientId})`}
						dot={false}
					/>
				</AreaChart>
			</ResponsiveContainer>
		</div>
	);
};

const DashboardScreen: React.FC = () => {
	const [mode, setMode] = useState<"live" | "paper">(() => {
		const savedMode = localStorage.getItem("dashboardMode") as "live" | "paper";
		return savedMode || "paper"; // Default is 'paper'
	});
	const [pnlPeriod, setPnlPeriod] = useState<PnlPeriod>("1d");
	const [portfolio, setPortfolio] = useState<PortfolioStatus | null>(null);
	const [equityPoints, setEquityPoints] = useState<EquityPoint[]>([]);
	const [periodStats, setPeriodStats] = useState<{
		realized: number;
		fees: number;
		maxDd: number | null;
	}>({ realized: 0, fees: 0, maxDd: null });
	const [loading, setLoading] = useState(true);
	const [error, setError] = useState<string | null>(null);
	const [isLiveModeAvailable, setIsLiveModeAvailable] = useState(false);
	const { t } = useTranslation("pwa-common");

	// Realtime engine pushes (merged per account in the shared store).
	const wsConnected = useRealtimeStore((s) => s.wsConnected);
	const portfolioSeq = useRealtimeStore((s) => s.portfolioSeq);
	const tradesSeq = useRealtimeStore((s) => s.tradesSeq);
	const storePositions = useRealtimeStore((s) => s.positionsByMode[mode]);
	const setStorePositions = useRealtimeStore((s) => s.setPositions);
	// Account-scoped view (web parity): a specific account shows only its
	// own positions; push-merged foreign rows never flash on screen.
	const selectedApiKeyId = useAccountStore((s) => s.selectedApiKeyId);
	const snapshotPositions = useMemo(() => {
		if (selectedApiKeyId === "all") return storePositions;
		return (storePositions ?? []).filter((p) => {
			const k = (p as unknown as Record<string, unknown>).api_key_id;
			return k !== null && k !== undefined && Number(k) === Number(selectedApiKeyId);
		});
	}, [storePositions, selectedApiKeyId]);

	// Live mark-prices straight from exchanges (zero backend load).
	const liveSymbols = useMemo(
		() =>
			(snapshotPositions ?? []).map((p) => ({
				symbol: String(p.symbol),
				exchange: readExchangeOf(p),
			})),
		[snapshotPositions],
	);
	const { marks: liveMarks } = useLiveMarks(liveSymbols);
	const positions = useMemo(
		() => applyLiveMarksToPositions(snapshotPositions, liveMarks) ?? [],
		[snapshotPositions, liveMarks],
	);

	useEffect(() => {
		const periodStartMs = (() => {
			const now = new Date();
			if (pnlPeriod === "1d") return now.getTime() - 86400 * 1000;
			if (pnlPeriod === "mtd")
				return new Date(now.getFullYear(), now.getMonth(), 1).getTime();
			return now.getTime() - 7 * 86400 * 1000;
		})();

		const fetchData = async () => {
			setLoading(true);
			setError(null);

			try {
				const config = await api.getConfig();
				const hasApiKeys = config?.apiKeys && config.apiKeys.length > 0;
				setIsLiveModeAvailable(hasApiKeys);

				// If live mode is selected but there are no keys, force switch to paper
				const currentMode = mode === "live" && !hasApiKeys ? "paper" : mode;
				if (mode !== currentMode) {
					setMode(currentMode);
					// The effect will be restarted with the new mode, so we interrupt the current execution
					return;
				}

				const [portfolioRes, positionsRes, equityRes, tradesRes] =
					await Promise.all([
						api.getPortfolio(currentMode),
						api.getPositions(currentMode),
						api.getPortfolioEquity(currentMode, pnlPeriod),
						api.getTrades({ mode: currentMode, limit: 1000 }),
					]);

				setPortfolio(portfolioRes || null);
				setStorePositions(currentMode, positionsRes || []);

				const view = computeEquityView(
					equityRes || [],
					(tradesRes?.trades || []).map((tr) => ({
						timestamp_close: tr.timestamp_close,
						pnl: tr.pnl,
						commission: tr.commission,
					})),
					portfolioRes?.balance ?? 0,
					periodStartMs,
					pnlPeriod,
				);
				setEquityPoints(view.points);
				setPeriodStats({
					realized: view.realized,
					fees: view.fees,
					maxDd: view.maxDd,
				});
			} catch (err) {
				console.error("Failed to fetch dashboard data:", err);
				setError(t("dashboard.failedToLoadData"));
				setPortfolio(null);
				setStorePositions(mode, []);
				setEquityPoints([]);
				setPeriodStats({ realized: 0, fees: 0, maxDd: null });
			} finally {
				setLoading(false);
			}
		};
		fetchData();
	}, [mode, pnlPeriod, t, setStorePositions, selectedApiKeyId]);

	// Portfolio push (per-controller) → refetch the aggregated REST view.
	useEffect(() => {
		if (portfolioSeq === 0) return;
		let cancelled = false;
		api
			.getPortfolio(mode)
			.then((res) => {
				if (!cancelled && res) setPortfolio(res);
			})
			.catch((err) => console.error("Failed to refresh portfolio:", err));
		return () => {
			cancelled = true;
		};
	}, [portfolioSeq, mode]);

	// Trades push (position closed) → refresh the equity curve only.
	useEffect(() => {
		if (tradesSeq === 0) return;
		let cancelled = false;
		const periodStartMs = (() => {
			const now = new Date();
			if (pnlPeriod === "1d") return now.getTime() - 86400 * 1000;
			if (pnlPeriod === "mtd")
				return new Date(now.getFullYear(), now.getMonth(), 1).getTime();
			return now.getTime() - 7 * 86400 * 1000;
		})();
		Promise.all([
			api.getPortfolioEquity(mode, pnlPeriod),
			api.getTrades({ mode, limit: 1000 }),
		])
			.then(([equityRes, tradesRes]) => {
				if (cancelled) return;
				const view = computeEquityView(
					equityRes || [],
					(tradesRes?.trades || []).map((tr) => ({
						timestamp_close: tr.timestamp_close,
						pnl: tr.pnl,
						commission: tr.commission,
					})),
					portfolio?.balance ?? 0,
					periodStartMs,
					pnlPeriod,
				);
				setEquityPoints(view.points);
				setPeriodStats({
					realized: view.realized,
					fees: view.fees,
					maxDd: view.maxDd,
				});
			})
			.catch((err) => console.error("Failed to refresh equity:", err));
		return () => {
			cancelled = true;
		};
	}, [tradesSeq, mode, pnlPeriod, portfolio]);

	// Fallback polling while the socket is down (realtime is push-driven).
	// Skipped without a usable token to avoid 401 storms when logged out.
	useEffect(() => {
		if (wsConnected) return;
		const id = setInterval(async () => {
			if (!hasUsableAuthToken()) return;
			try {
				const [portfolioRes, positionsRes] = await Promise.all([
					api.getPortfolio(mode),
					api.getPositions(mode),
				]);
				if (portfolioRes) setPortfolio(portfolioRes);
				setStorePositions(mode, positionsRes || []);
			} catch (err) {
				console.error("Failed fallback refresh:", err);
			}
		}, 5000);
		return () => clearInterval(id);
	}, [wsConnected, mode, setStorePositions]);

	const handleSetMode = (newMode: "live" | "paper") => {
		if (newMode === "live" && !isLiveModeAvailable) {
			toast.error(t("dashboard.connectApiKeysMessage"));
			return;
		}
		setMode(newMode);
		localStorage.setItem("dashboardMode", newMode);
	};

	const swipeHandlers = useSwipeable({
		onSwipedLeft: () => handleSetMode("paper"),
		onSwipedRight: () => handleSetMode("live"),
		preventScrollOnSwipe: true,
		trackMouse: true,
	});

	const handleClosePosition = async (symbol: string) => {
		if (!window.confirm(t("dashboard.confirmClosePosition", { symbol })))
			return;
		try {
			await api.closePosition(symbol);
			alert(t("dashboard.closePositionCommandSent", { symbol }));
			// Burst push removes it right away; poll once as a safety net.
			setTimeout(() => {
				api.getPositions(mode).then((res) => setStorePositions(mode, res || []));
			}, 2000);
		} catch (err) {
			console.error(err);
			alert(t("dashboard.errorClosingPosition", { symbol }));
		}
	};

	if (loading && !portfolio && !error) {
		return (
			<div className="flex justify-center items-center min-h-screen">
				<Logo size="lg" className="mb-8 animate-pulse" />
			</div>
		);
	}

	if (error) {
		return (
			<div className="p-4 text-center text-[hsl(var(--loss))]">{error}</div>
		);
	}

	const unrealizedPnl = positions.reduce((acc, pos) => acc + pos.pnl, 0);

	const hasEquity = equityPoints.length > 1;
	const firstEquity = hasEquity ? equityPoints[0].equity : 0;
	const lastEquity = hasEquity ? equityPoints[equityPoints.length - 1].equity : 0;
	const equityChgPct =
		hasEquity && firstEquity > 0 ? ((lastEquity - firstEquity) / firstEquity) * 100 : 0;
	const equityPositive = lastEquity >= firstEquity;

	return (
		<div {...swipeHandlers} className="p-4 animate-fadeIn">
			<div className="flex gap-1 p-1 bg-[hsl(var(--secondary))] rounded-lg mb-5">
				<button
					onClick={() => handleSetMode("live")}
					className={`flex-1 py-2 px-4 rounded-md transition-all text-sm font-medium ${mode === "live" ? "bg-[hsl(var(--card))] shadow text-[hsl(var(--card-foreground))]" : "bg-transparent text-[hsl(var(--muted-foreground))]"} ${!isLiveModeAvailable ? "opacity-60" : ""}`}
				>
					{t("dashboard.live")}
				</button>
				<button
					onClick={() => handleSetMode("paper")}
					className={`flex-1 py-2 px-4 rounded-md transition-all text-sm font-medium ${mode === "paper" ? "bg-[hsl(var(--card))] shadow text-[hsl(var(--card-foreground))]" : "bg-transparent text-[hsl(var(--muted-foreground))]"}`}
				>
					{t("dashboard.paper")}
				</button>
			</div>

			<div key={mode} className="animate-fadeIn">
				<div className="bg-gradient-to-br from-[hsl(var(--primary))] to-blue-800 text-[hsl(var(--primary-foreground))] p-5 rounded-2xl mb-5 shadow-lg">
					<div className="text-sm opacity-90">
						{t("dashboard.totalBalance")}
					</div>
					<div className="text-4xl font-light my-3">
						$
						{portfolio?.balance.toLocaleString(undefined, {
							minimumFractionDigits: 2,
							maximumFractionDigits: 2,
						}) || "0.00"}
					</div>
					<div className="flex gap-5 mt-4">
						<div className="flex-1">
							<div className="text-xs opacity-90">
								{t("dashboard.dailyPnl")}
							</div>
							<div className="text-lg font-medium">
								{(portfolio?.today_pnl ?? 0 >= 0) ? "+" : ""}$
								{portfolio?.today_pnl.toLocaleString() || "0"}
							</div>
						</div>
						<div className="flex-1">
							<div className="text-xs opacity-90">
								{t("dashboard.unrealizedPnl")}
							</div>
							<div className="text-lg font-medium">
								{unrealizedPnl >= 0 ? "+" : ""}$
								{unrealizedPnl.toLocaleString(undefined, {
									minimumFractionDigits: 2,
									maximumFractionDigits: 2,
								})}
							</div>
						</div>
					</div>
				</div>

				<div className="bg-[hsl(var(--card))] rounded-xl p-4 mb-5 shadow-sm">
					<div className="flex justify-between items-center mb-1">
						<div>
							<h3 className="text-base font-medium text-[hsl(var(--card-foreground))]">
								{t("dashboard.equityCurve", "Equity Curve")}
							</h3>
							{hasEquity && (
								<div className="text-xs text-[hsl(var(--muted-foreground))] font-mono mt-0.5">
									$
									{lastEquity.toLocaleString(undefined, {
										minimumFractionDigits: 2,
										maximumFractionDigits: 2,
									})}{" "}
									<span
										className={
											equityPositive
												? "text-[hsl(var(--profit))]"
												: "text-[hsl(var(--loss))]"
										}
									>
										{equityPositive ? "+" : ""}
										{equityChgPct.toFixed(2)}%
									</span>
								</div>
							)}
						</div>
						<div className="flex gap-1 text-xs bg-[hsl(var(--secondary))] p-1 rounded-md">
							<button
								onClick={() => setPnlPeriod("1d")}
								className={`px-2 py-1 rounded ${pnlPeriod === "1d" ? "bg-[hsl(var(--background))] text-[hsl(var(--foreground))]" : "text-[hsl(var(--muted-foreground))]"}`}
							>
								{t("dashboard.1d")}
							</button>
							<button
								onClick={() => setPnlPeriod("7d")}
								className={`px-2 py-1 rounded ${pnlPeriod === "7d" ? "bg-[hsl(var(--background))] text-[hsl(var(--foreground))]" : "text-[hsl(var(--muted-foreground))]"}`}
							>
								{t("dashboard.7d")}
							</button>
							<button
								onClick={() => setPnlPeriod("mtd")}
								className={`px-2 py-1 rounded ${pnlPeriod === "mtd" ? "bg-[hsl(var(--background))] text-[hsl(var(--foreground))]" : "text-[hsl(var(--muted-foreground))]"}`}
							>
								{t("dashboard.mtd")}
							</button>
						</div>
					</div>
					{loading ? (
						<div className="h-52 flex items-center justify-center text-sm text-[hsl(var(--muted-foreground))]">
							{t("dashboard.loadingChart")}
						</div>
					) : hasEquity ? (
						<>
							<PnlChart data={equityPoints} positive={equityPositive} t={t} />
							<div className="mt-3 grid grid-cols-3 gap-2 border-t border-[hsl(var(--border))] pt-3 text-center">
								<div>
									<div className="text-[10px] uppercase tracking-wider text-[hsl(var(--muted-foreground))]">
										{t("dashboard.realized", "Realized")}
									</div>
									<div
										className={`font-mono text-[13px] font-semibold ${periodStats.realized >= 0 ? "text-[hsl(var(--profit))]" : "text-[hsl(var(--loss))]"}`}
									>
										{periodStats.realized >= 0 ? "+" : ""}$
										{periodStats.realized.toLocaleString(undefined, {
											minimumFractionDigits: 2,
											maximumFractionDigits: 2,
										})}
									</div>
								</div>
								<div>
									<div className="text-[10px] uppercase tracking-wider text-[hsl(var(--muted-foreground))]">
										{t("dashboard.fees", "Fees")}
									</div>
									<div className="font-mono text-[13px] font-semibold text-[hsl(var(--muted-foreground))]">
										-$
										{periodStats.fees.toLocaleString(undefined, {
											minimumFractionDigits: 2,
											maximumFractionDigits: 2,
										})}
									</div>
								</div>
								<div>
									<div className="text-[10px] uppercase tracking-wider text-[hsl(var(--muted-foreground))]">
										{t("dashboard.maxDd", "Max DD")}
									</div>
									<div className="font-mono text-[13px] font-semibold text-[hsl(var(--loss))]">
										{periodStats.maxDd !== null
											? `${periodStats.maxDd.toFixed(1)}%`
											: "—"}
									</div>
								</div>
							</div>
						</>
					) : (
						<div className="h-52 flex items-center justify-center text-center text-sm text-[hsl(var(--muted-foreground))]">
							{t("dashboard.noEquityHistory", "No equity history yet — it appears after closed trades.")}
						</div>
					)}
				</div>

				<div className="bg-[hsl(var(--card))] rounded-xl p-4 shadow-sm">
					<div className="flex justify-between items-center mb-1">
						<h3 className="text-base font-medium text-[hsl(var(--card-foreground))]">
							{t("dashboard.activePositions")}
						</h3>
						<span
							className={`rounded-full border px-2 py-0.5 font-mono text-[10px] ${
								wsConnected
									? "border-emerald-400/30 text-emerald-600"
									: "border-amber-400/30 text-amber-600"
							}`}
						>
							{wsConnected
								? t("dashboard.realtimeLive", "live")
								: t("dashboard.realtimePolling", "polling")}
						</span>
					</div>
					<div className="divide-y divide-[hsl(var(--border))]">
						{positions.length > 0 ? (
							positions.map((pos) => (
								<div
									key={pos.id}
									className="flex justify-between items-center py-3"
								>
									<div>
										<div className="font-medium">{pos.symbol}</div>
										<div className="text-sm text-[hsl(var(--muted-foreground))]">
											{t("dashboard.size")}: {pos.size}
										</div>
									</div>
									<div className="flex items-center gap-4">
										<div className="text-right">
											<div
												className={`font-medium ${pos.pnl >= 0 ? "text-[hsl(var(--profit))]" : "text-[hsl(var(--loss))]"}`}
											>
												{t("dashboard.pnl")}: {pos.pnl >= 0 ? "+" : ""}
												{pos.pnl.toLocaleString(undefined, {
													minimumFractionDigits: 2,
													maximumFractionDigits: 2,
												})}
											</div>
											<div className="text-xs text-[hsl(var(--muted-foreground))]">
												{pos.pnl_percent >= 0 ? "+" : ""}
												{pos.pnl_percent.toFixed(2)}%
											</div>
										</div>
										<button
											onClick={() => handleClosePosition(pos.symbol)}
											className="w-8 h-8 rounded-full flex items-center justify-center transition bg-[hsl(var(--secondary))] hover:bg-[hsl(var(--accent))]"
											aria-label={t("dashboard.closePosition", {
												symbol: pos.symbol,
											})}
										>
											<ICONS.Close className="w-5 h-5 text-[hsl(var(--muted-foreground))]" />
										</button>
									</div>
								</div>
							))
						) : (
							<p className="text-center text-sm text-[hsl(var(--muted-foreground))] py-4">
								{t("dashboard.noActivePositions")}
							</p>
						)}
					</div>
				</div>
			</div>
		</div>
	);
};

export default DashboardScreen;
