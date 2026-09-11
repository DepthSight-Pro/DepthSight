// pwa/components/BacktestModal.tsx

import type React from "react";
import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Calendar, Database, Loader2 } from "lucide-react";
import { type DisplayStrategy, hasProPlanAccess } from "../types";
import { useAuth } from "../contexts/AuthContext";
import { api } from "../services/api";

interface BacktestModalProps {
	isOpen: boolean;
	onClose: () => void;
	onSubmit: (details: {
		symbol: string;
		startDate: string;
		endDate: string;
		backtestEngine: "vector" | "kline";
	}) => void;
	strategy: DisplayStrategy | null;
}

const pad = (n: number) => (n < 10 ? `0${n}` : `${n}`);
const toYMD = (d: Date) =>
	`${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;

// Session-level memory cache to eliminate repeated network/disk calls in PWA
const historicalRangesCache = new Map<
	string,
	{ start: string; end: string; timeframes?: string[] } | null
>();

const BacktestModal: React.FC<BacktestModalProps> = ({
	isOpen,
	onClose,
	onSubmit,
	strategy,
}) => {
	const { t } = useTranslation("pwa-common");
	const { user } = useAuth();
	const userTier = user?.plan || "free";
	const hasPrecisionAccess = hasProPlanAccess(userTier) || user?.role === "admin";

	const [symbol, setSymbol] = useState("");
	const [startDate, setStartDate] = useState("");
	const [endDate, setEndDate] = useState("");
	const [backtestEngine, setBacktestEngine] = useState<"vector" | "kline">("vector");
	const [storageRange, setStorageRange] = useState<{
		start: string;
		end: string;
		timeframes?: string[];
	} | null>(null);
	const [isLoadingHistory, setIsLoadingHistory] = useState(false);

	useEffect(() => {
		const timer = setTimeout(() => {
			// Pre-fill symbol - use BTCUSDT as default or from strategy config
			if (strategy) {
				const configSymbol =
					strategy.config_data?.name?.split("•")[0].trim() || "BTCUSDT";
				setSymbol(configSymbol);
			} else {
				// Default to BTCUSDT when called from EditorScreen (no strategy)
				setSymbol("BTCUSDT");
			}
			// Set default dates
			const today = new Date().toISOString().split("T")[0];
			const oneMonthAgo = new Date(
				new Date().setMonth(new Date().getMonth() - 1),
			)
				.toISOString()
				.split("T")[0];
			setStartDate(oneMonthAgo);
			setEndDate(today);
			setBacktestEngine("vector");
		}, 0);
		return () => clearTimeout(timer);
	}, [strategy]);

	// Fetch available historical data coverage when symbol changes (checks session cache first)
	useEffect(() => {
		if (!symbol) {
			setStorageRange(null);
			return;
		}
		const clean = symbol.replace("/", "").replace(":", "").toUpperCase();
		if (historicalRangesCache.has(clean)) {
			setStorageRange(historicalRangesCache.get(clean) || null);
			return;
		}

		let isMounted = true;
		setIsLoadingHistory(true);
		api.getHistoricalRanges(symbol)
			.then((list) => {
				if (!isMounted) return;
				const match =
					list?.find(
						(item) =>
							item.symbol.replace("/", "").replace(":", "").toUpperCase() === clean,
					) || list?.[0];
				if (match?.klines_1m?.start_date && match?.klines_1m?.end_date) {
					const info = {
						start: match.klines_1m.start_date,
						end: match.klines_1m.end_date,
						timeframes: match.timeframes,
					};
					historicalRangesCache.set(clean, info);
					setStorageRange(info);
				} else {
					historicalRangesCache.set(clean, null);
					setStorageRange(null);
				}
			})
			.catch(() => {
				if (isMounted) setStorageRange(null);
			})
			.finally(() => {
				if (isMounted) setIsLoadingHistory(false);
			});
		return () => {
			isMounted = false;
		};
	}, [symbol]);

	const presets = useMemo(() => {
		const now = new Date();
		const todayYMD = toYMD(now);

		let anchorEnd = now;
		if (storageRange?.end) {
			const parsed = new Date(storageRange.end);
			if (!isNaN(parsed.getTime()) && parsed <= now) {
				anchorEnd = parsed;
			}
		}
		const anchorEndYMD = toYMD(anchorEnd);

		const storageStart = storageRange?.start;
		const storageEnd = storageRange?.end;

		// 1. All available
		const allFrom = storageStart || `${now.getFullYear() - 1}-01-01`;
		const allTo = storageEnd || todayYMD;

		// 2. This year
		const thisYearFrom = `${anchorEnd.getFullYear()}-01-01`;
		const clampedThisYearFrom =
			storageStart && storageStart > thisYearFrom ? storageStart : thisYearFrom;
		const thisYearTo = anchorEndYMD;

		// 3. Last year
		const lastYear = anchorEnd.getFullYear() - 1;
		const lastYearFrom = `${lastYear}-01-01`;
		const lastYearTo = `${lastYear}-12-31`;
		const clampLastYearFrom =
			storageStart && storageStart > lastYearFrom ? storageStart : lastYearFrom;
		const clampLastYearTo =
			storageEnd && storageEnd < lastYearTo ? storageEnd : lastYearTo;

		// 4. 6 months
		const sixMonthsAgo = new Date(anchorEnd);
		sixMonthsAgo.setMonth(sixMonthsAgo.getMonth() - 6);
		const sixMonthsFrom = toYMD(sixMonthsAgo);
		const clampSixMonthsFrom =
			storageStart && storageStart > sixMonthsFrom ? storageStart : sixMonthsFrom;

		// 5. 3 months
		const threeMonthsAgo = new Date(anchorEnd);
		threeMonthsAgo.setMonth(threeMonthsAgo.getMonth() - 3);
		const threeMonthsFrom = toYMD(threeMonthsAgo);
		const clampThreeMonthsFrom =
			storageStart && storageStart > threeMonthsFrom ? storageStart : threeMonthsFrom;

		// 6. 1 month
		const oneMonthAgo = new Date(anchorEnd);
		oneMonthAgo.setMonth(oneMonthAgo.getMonth() - 1);
		const oneMonthFrom = toYMD(oneMonthAgo);
		const clampOneMonthFrom =
			storageStart && storageStart > oneMonthFrom ? storageStart : oneMonthFrom;

		// 7. Last month (previous calendar month)
		const prevMonthYear =
			anchorEnd.getMonth() === 0
				? anchorEnd.getFullYear() - 1
				: anchorEnd.getFullYear();
		const prevMonth = anchorEnd.getMonth() === 0 ? 11 : anchorEnd.getMonth() - 1;
		const prevMonthStart = new Date(prevMonthYear, prevMonth, 1);
		const prevMonthEnd = new Date(prevMonthYear, prevMonth + 1, 0);
		const prevMonthFrom = toYMD(prevMonthStart);
		const prevMonthTo = toYMD(prevMonthEnd);
		const clampPrevMonthFrom =
			storageStart && storageStart > prevMonthFrom ? storageStart : prevMonthFrom;
		const clampPrevMonthTo =
			storageEnd && storageEnd < prevMonthTo ? storageEnd : prevMonthTo;

		return [
			{
				id: "all",
				labelKey: "backtestModal.presets.all",
				colSpan: "col-span-2",
				from: allFrom,
				to: allTo,
			},
			{
				id: "thisYear",
				labelKey: "backtestModal.presets.thisYear",
				colSpan: "col-span-1",
				from: clampedThisYearFrom,
				to: thisYearTo,
			},
			{
				id: "lastYear",
				labelKey: "backtestModal.presets.lastYear",
				colSpan: "col-span-1",
				from: clampLastYearFrom,
				to: clampLastYearTo,
			},
			{
				id: "sixMonths",
				labelKey: "backtestModal.presets.sixMonths",
				colSpan: "col-span-1",
				from: clampSixMonthsFrom,
				to: anchorEndYMD,
			},
			{
				id: "threeMonths",
				labelKey: "backtestModal.presets.threeMonths",
				colSpan: "col-span-1",
				from: clampThreeMonthsFrom,
				to: anchorEndYMD,
			},
			{
				id: "oneMonth",
				labelKey: "backtestModal.presets.oneMonth",
				colSpan: "col-span-1",
				from: clampOneMonthFrom,
				to: anchorEndYMD,
			},
			{
				id: "lastMonth",
				labelKey: "backtestModal.presets.lastMonth",
				colSpan: "col-span-1",
				from: clampPrevMonthFrom,
				to: clampPrevMonthTo,
			},
		];
	}, [storageRange]);

	if (!isOpen) return null;

	const handleSubmit = () => {
		if (symbol && startDate && endDate) {
			if (backtestEngine === "kline" && !hasPrecisionAccess) {
				alert(
					t(
						"backtestModal.klineProOnly",
						"Precision Engine (Kline) is available for Pro users only. Please upgrade to unlock institutional-grade testing.",
					),
				);
				return;
			}
			onSubmit({ symbol, startDate, endDate, backtestEngine });
		} else {
			alert(t("backtestModal.fillAllFields"));
		}
	};

	return (
		<>
			<div
				className={`fixed inset-0 bg-black/50 z-40 transition-opacity duration-300 ${isOpen ? "opacity-100 pointer-events-auto" : "opacity-0 pointer-events-none"}`}
				onClick={onClose}
				onKeyDown={(e) => {
					if (e.key === "Enter" || e.key === " ") {
						onClose();
					}
				}}
				role="button"
				tabIndex={0}
				aria-label={t("buttons.close")}
			></div>
			<div
				className={`fixed top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[90%] max-w-md max-h-[90vh] overflow-y-auto bg-[hsl(var(--card))] rounded-3xl shadow-[-4px_0_20px_rgba(0,0,0,0.1)] p-6 z-50 transition-all duration-300 ease-out ${isOpen ? "scale-100 opacity-100" : "scale-95 opacity-0"}`}
			>
				<h2 className="text-xl font-medium mb-1 text-[hsl(var(--card-foreground))]">
					{t("backtestModal.strategyBacktest")}
				</h2>
				<p className="text-sm text-[hsl(var(--muted-foreground))] mb-4">
					{strategy?.name}
				</p>

				{/* Symbol input */}
				<div className="mb-4">
					<label
						htmlFor="backtest-symbol"
						className="text-sm text-[hsl(var(--muted-foreground))] mb-2 block font-medium"
					>
						{t("backtestModal.symbol")}
					</label>
					<input
						id="backtest-symbol"
						type="text"
						className="w-full p-3 bg-[hsl(var(--secondary))] border border-[hsl(var(--border))] rounded-lg text-base text-[hsl(var(--foreground))] placeholder:text-[hsl(var(--muted-foreground))] outline-none transition-all focus:border-[hsl(var(--primary))] focus:ring-1 focus:ring-[hsl(var(--primary))]"
						value={symbol}
						onChange={(e) => setSymbol(e.target.value.toUpperCase())}
					/>
				</div>

				{/* Quick Presets Section */}
				<div className="mb-4 p-3 bg-[hsl(var(--secondary)/0.4)] border border-[hsl(var(--border))] rounded-xl space-y-2">
					<div className="flex items-center justify-between gap-1 text-xs">
						<div className="flex items-center gap-1.5 font-medium text-[hsl(var(--muted-foreground))]">
							<Calendar className="w-3.5 h-3.5 text-[hsl(var(--primary))] shrink-0" />
							<span className="text-[11px] font-semibold uppercase tracking-wider">
								{t("backtestModal.quickPresets")}
							</span>
						</div>

						{isLoadingHistory ? (
							<div className="flex items-center gap-1 text-[10px] text-[hsl(var(--muted-foreground))]">
								<Loader2 className="w-3 h-3 animate-spin" />
							</div>
						) : storageRange ? (
							<div className="flex items-center gap-1 text-[10px] bg-[hsl(var(--secondary))] text-[hsl(var(--secondary-foreground))] px-2 py-0.5 rounded-full border border-[hsl(var(--border))] font-mono">
								<Database className="w-2.5 h-2.5 text-[hsl(var(--primary))] shrink-0" />
								<span>
									{storageRange.start} — {storageRange.end}
								</span>
							</div>
						) : (
							<span className="text-[10px] text-[hsl(var(--muted-foreground)/0.7)]">
								{t("backtestModal.noHistory")}
							</span>
						)}
					</div>

					{/* 4-column compact preset buttons */}
					<div className="grid grid-cols-4 gap-1.5 pt-1">
						{presets.map((preset) => {
							const isActive =
								startDate === preset.from && endDate === preset.to;
							return (
								<button
									key={preset.id}
									type="button"
									className={`h-7 px-1 rounded-md text-[11px] font-medium leading-none transition-all truncate border ${
										preset.colSpan
									} ${
										isActive
											? "bg-[hsl(var(--primary))] text-[hsl(var(--primary-foreground))] border-[hsl(var(--primary))] shadow-xs font-semibold"
											: "bg-[hsl(var(--secondary))] text-[hsl(var(--secondary-foreground))] border-[hsl(var(--border))] hover:bg-[hsl(var(--secondary)/0.8)]"
									}`}
									onClick={() => {
										setStartDate(preset.from);
										setEndDate(preset.to);
									}}
									title={`${preset.from} — ${preset.to}`}
								>
									{t(preset.labelKey)}
								</button>
							);
						})}
					</div>
				</div>

				{/* Start and End date inputs */}
				<div className="grid grid-cols-2 gap-3 mb-4">
					<div>
						<label
							htmlFor="backtest-start-date"
							className="text-sm text-[hsl(var(--muted-foreground))] mb-1.5 block font-medium"
						>
							{t("backtestModal.startDate")}
						</label>
						<input
							id="backtest-start-date"
							type="date"
							className="w-full p-2.5 bg-[hsl(var(--secondary))] border border-[hsl(var(--border))] rounded-lg text-sm text-[hsl(var(--foreground))] outline-none transition-all focus:border-[hsl(var(--primary))] focus:ring-1 focus:ring-[hsl(var(--primary))]"
							value={startDate}
							onChange={(e) => setStartDate(e.target.value)}
						/>
					</div>
					<div>
						<label
							htmlFor="backtest-end-date"
							className="text-sm text-[hsl(var(--muted-foreground))] mb-1.5 block font-medium"
						>
							{t("backtestModal.endDate")}
						</label>
						<input
							id="backtest-end-date"
							type="date"
							className="w-full p-2.5 bg-[hsl(var(--secondary))] border border-[hsl(var(--border))] rounded-lg text-sm text-[hsl(var(--foreground))] outline-none transition-all focus:border-[hsl(var(--primary))] focus:ring-1 focus:ring-[hsl(var(--primary))]"
							value={endDate}
							onChange={(e) => setEndDate(e.target.value)}
						/>
					</div>
				</div>

				{/* Engine selector */}
				<div className="mb-4">
					<label
						htmlFor="backtest-engine"
						className="text-sm text-[hsl(var(--muted-foreground))] mb-2 block font-medium"
					>
						{t("backtestModal.backtestEngine", "Backtest Engine")}
					</label>
					<select
						id="backtest-engine"
						className="w-full p-3 bg-[hsl(var(--secondary))] border border-[hsl(var(--border))] rounded-lg text-base text-[hsl(var(--foreground))] outline-none transition-all focus:border-[hsl(var(--primary))] focus:ring-1 focus:ring-[hsl(var(--primary))]"
						value={backtestEngine}
						onChange={(e) => setBacktestEngine(e.target.value as "vector" | "kline")}
					>
						<option value="vector">{t("backtestModal.engineVector", "Vector (Fast)")}</option>
						<option value="kline">{t("backtestModal.engineKline", "Kline (Precision) [Pro]")}</option>
					</select>
				</div>

				{/* Action buttons */}
				<div className="flex gap-3 mt-6">
					<button
						type="button"
						className="flex-1 py-3 rounded-lg border-none text-sm font-medium bg-[hsl(var(--secondary))] text-[hsl(var(--secondary-foreground))] transition hover:opacity-90"
						onClick={onClose}
					>
						{t("buttons.cancel")}
					</button>
					<button
						type="button"
						className="flex-1 py-3 rounded-lg border-none text-sm font-medium bg-[hsl(var(--primary))] text-[hsl(var(--primary-foreground))] transition hover:opacity-90"
						onClick={handleSubmit}
					>
						{t("backtestModal.runBacktest")}
					</button>
				</div>
			</div>
		</>
	);
};

export default BacktestModal;
