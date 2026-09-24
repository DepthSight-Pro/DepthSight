// src/pages/Positions.tsx

import { formatDistanceToNow } from "date-fns";
import {
	AlertOctagon,
	ArrowDownRight,
	ArrowUpRight,
	Crosshair,
	Flame,
	LineChart,
	Pencil,
	RefreshCw,
	Shield,
	X,
} from "lucide-react";
import React, { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { useSearchParams } from "react-router-dom";
import { toast } from "sonner";
import { ExchangeBadge } from "@/components/layout/AccountSelector";
import { PageLayout } from "@/components/layout/PageLayout";
import { PositionChartModal } from "@/components/positions/PositionChartModal";
import { PositionSparkline } from "@/components/positions/PositionSparkline";
import {
	Badge,
	Bar,
	Btn,
	fmt,
	Panel,
	SectionLabel,
	Segmented,
	Stat,
	Td,
	Th,
	toneHex,
	toneText,
} from "@/components/ui/quant-ui";
import { usePortfolioMode } from "@/context/PortfolioModeContext";
import { useWebSocket } from "@/context/WebSocketProvider";
import { useLiveMarks } from "@/hooks/useLiveMarks";
import { applyLiveMarksToPositions } from "@/lib/livePnl";
import {
	useClosePosition,
	useConfig,
	useEmergencyStop,
	usePositions,
	useTradeHistory,
	useUpdatePositionSlTp,
} from "@/lib/api";
import { exchangeLabels, normalizeExchangeKey } from "@/lib/exchanges";
import { cn } from "@/lib/utils";
import { useAccountStore } from "@/stores/accountStore";
import type { PositionData } from "@/types/api";

const formatOpenedAgo = (entryTime: unknown): string => {
	if (!entryTime) return "Active";
	const date =
		typeof entryTime === "number"
			? new Date(entryTime > 1_000_000_000_000 ? entryTime : entryTime * 1000)
			: new Date(entryTime as string);
	if (Number.isNaN(date.getTime())) return "Active";
	return formatDistanceToNow(date, { addSuffix: false });
};

/** Raw position as served by the API: PositionData plus camelCase/legacy
 * aliases and fields (leverage, etc.) that the list normalizes. */
interface RawPosition extends PositionData {
	entryPrice?: number;
	markPrice?: number;
	unrealizedPnl?: number;
	side?: string;
	apiKeyId?: number | string;
	exchange_id?: string | null;
	stopLoss?: number;
	takeProfit?: number;
	liquidation_price?: number;
	liquidationPrice?: number;
	leverage?: number;
	strategy_name?: string;
	entryTime?: string | number;
}

export default function Positions() {
	const { t } = useTranslation(["positions", "common"]);
	const { mode } = usePortfolioMode();
	const { selectedApiKeyId, selectedMarketType } = useAccountStore();
	const [searchParams] = useSearchParams();

	const hookParams = useMemo(
		() => ({
			mode,
			apiKeyId: mode === "live" ? selectedApiKeyId : undefined,
			marketType: mode === "live" ? selectedMarketType : undefined,
		}),
		[mode, selectedApiKeyId, selectedMarketType],
	);

	const { readyState } = useWebSocket();
	const wsLive = readyState === 1;

	const {
		data: realPositions,
		isLoading,
		refetch,
	} = usePositions({ ...hookParams, refetchInterval: wsLive ? false : 5000 });

	// Live marks overlay (indicative; backend snapshot stays source of truth).
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

	const { mutate: closePosition, isPending: isClosing } = useClosePosition();
	const { mutate: updateSlTp, isPending: isUpdatingSlTp } =
		useUpdatePositionSlTp();
	const { mutate: emergencyStop, isPending: isStopping } = useEmergencyStop();

	const { data: recentTradesData } = useTradeHistory({
		mode,
		limit: 15,
		apiKeyId: mode === "live" ? selectedApiKeyId : undefined,
	});
	const recentTrades = useMemo(
		() => (recentTradesData?.trades || []).slice(0, 10),
		[recentTradesData],
	);

	// View state
	const [view, setView] = useState<"cards" | "table">("cards");
	const [sideF, setSideF] = useState<"all" | "LONG" | "SHORT">("all");
	const [symbolFilter, setSymbolFilter] = useState<string>("");
	const [confirmStop, setConfirmStop] = useState(false);

	// Normalized positions list (real positions only)
	const { data: appConfig } = useConfig();
	const apiKeysById = useMemo(() => {
		const map = new Map<number, string>();
		for (const k of appConfig?.apiKeys ?? []) {
			if (k?.id != null && k?.exchange) map.set(Number(k.id), String(k.exchange));
		}
		return map;
	}, [appConfig]);

	const positionsList = useMemo(() => {
		const src = livePositions ?? realPositions;
		if (!src || src.length === 0) return [];
		return src.map((p: RawPosition, idx: number) => {
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
			const apiKeyIdRaw = p.api_key_id ?? p.apiKeyId ?? null;
			const apiKeyId =
				apiKeyIdRaw != null && apiKeyIdRaw !== ""
					? Number(apiKeyIdRaw)
					: undefined;
			const exKey =
				normalizeExchangeKey(p.exchange ?? p.exchange_id) ??
				(apiKeyId != null && apiKeysById.has(apiKeyId)
					? normalizeExchangeKey(apiKeysById.get(apiKeyId))
					: null);
			const sl = p.stop_loss ?? p.stopLoss ?? null;
			const tp = p.take_profit ?? p.takeProfit ?? null;
			const liqRaw = Number(p.liquidation_price ?? p.liquidationPrice);
			const liqEstimated = !Number.isFinite(liqRaw) || liqRaw <= 0;
			const liq = !liqEstimated
				? liqRaw
				: side === "SHORT"
					? mark * 1.3
					: mark * 0.7;

			return {
				// Full passthrough for the chart modal (executions, SL/TP rails).
				...p,
				id: String(p.id || `real-${idx}`),
				symbol: p.symbol || "BTCUSDT",
				side,
				size,
				entry,
				mark,
				leverage: p.leverage || 5,
				pnl,
				pnlPct,
				sl,
				tp,
				strategy: p.strategy_name || p.strategy || "Quant Engine",
				strategy_name: p.strategy_name || p.strategy || "Quant Engine",
				exchange: exKey,
				exchange_id: p.exchange ?? p.exchange_id ?? exKey ?? null,
				openedAgo: formatOpenedAgo(p.entry_time ?? p.entryTime),
				entryTime: p.entry_time ?? p.entryTime ?? null,
				entry_time: p.entry_time ?? p.entryTime ?? null,
				liq,
				liqEstimated,
				apiKeyId,
				api_key_id: apiKeyId,
			};
		});
	}, [livePositions, realPositions, apiKeysById]);

	// Chart Modal state
	type PositionListItem = (typeof positionsList)[number];
	const [chartModalPos, setChartModalPos] =
		useState<PositionListItem | null>(null);
	const [isChartModalOpen, setIsChartModalOpen] = useState(false);

	// Filtered list based on side and search query
	const filteredList = useMemo(() => {
		return positionsList
			.filter((p) => sideF === "all" || p.side === sideF)
			.filter(
				(p) =>
					!symbolFilter ||
					p.symbol.toLowerCase().includes(symbolFilter.toLowerCase()) ||
					p.strategy.toLowerCase().includes(symbolFilter.toLowerCase()),
			);
	}, [positionsList, sideF, symbolFilter]);

	// Selected position
	const [sel, setSel] = useState<PositionListItem | null>(null);

	// Keep `sel` pointing at a live entry of `positionsList` (a `?symbol=`
	// URL match wins, then fall back to the first entry). Adjusted during
	// render instead of a setState-in-effect to avoid cascading renders.
	const targetSym = searchParams.get("symbol");
	const urlMatch = targetSym
		? positionsList.find(
				(p) => p.symbol.toLowerCase() === targetSym.toLowerCase(),
			)
		: undefined;
	let nextSel = sel;
	if (urlMatch) {
		nextSel = urlMatch;
	} else if (!sel && positionsList.length > 0) {
		nextSel = positionsList[0];
	} else if (sel) {
		const stillExists = positionsList.find((p) => p.id === sel.id);
		if (stillExists) {
			nextSel = stillExists;
		} else if (positionsList.length > 0) {
			nextSel = positionsList[0];
		}
	}
	if (nextSel !== sel) {
		setSel(nextSel);
	}

	// Inspector editable SL / TP inputs — reset when the selected position's
	// identity or stored levels change (adjust-during-render, keyed on the
	// same id/sl/tp values the old effect depended on).
	const [selSl, setSelSl] = useState<string>("");
	const [selTp, setSelTp] = useState<string>("");
	const slTpKey = sel ? `${sel.id}|${sel.sl ?? ""}|${sel.tp ?? ""}` : "";
	const [prevSlTpKey, setPrevSlTpKey] = useState(slTpKey);
	if (slTpKey !== prevSlTpKey) {
		setPrevSlTpKey(slTpKey);
		setSelSl(sel?.sl != null ? String(sel.sl) : "");
		setSelTp(sel?.tp != null ? String(sel.tp) : "");
	}

	// Aggregates
	const total = filteredList.reduce((a, b) => a + b.pnl, 0);
	const avgRoe =
		filteredList.reduce((a, b) => a + b.pnlPct, 0) / (filteredList.length || 1);
	const longs = filteredList
		.filter((p) => p.side === "LONG")
		.reduce((a, p) => a + p.size * p.mark, 0);
	const shorts = filteredList
		.filter((p) => p.side === "SHORT")
		.reduce((a, p) => a + p.size * p.mark, 0);
	const longShare = longs / (longs + shorts || 1);

	// Actions (all positions are real — no mock branches)
	const handleClose = (symbol: string, apiKeyId?: number) => {
		closePosition(
			{ symbol, apiKeyId },
			{
				onSuccess: () => {
					toast.success(`Position ${symbol} closed successfully`);
					refetch();
				},
			},
		);
	};

	const handleUpdateSlTp = () => {
		if (!sel) return;
		const parsedSl = selSl.trim() ? Number(selSl) : null;
		const parsedTp = selTp.trim() ? Number(selTp) : null;

		updateSlTp(
			{
				positionId: sel.id,
				stop_loss: parsedSl,
				take_profit: parsedTp,
			},
			{
				onSuccess: () => {
					toast.success(`Updated risk levels for ${sel.symbol}`);
					refetch();
				},
			},
		);
	};

	const handleEmergencyStop = () => {
		emergencyStop(undefined, {
			onSuccess: () => {
				setConfirmStop(false);
				toast.success("Emergency stop triggered. All positions liquidated.");
				refetch();
			},
			onError: () => {
				setConfirmStop(false);
			},
		});
	};

	return (
		<PageLayout title={t("positions:pageTitle", "Positions")} hideHeader>
			<div className="space-y-4">
				{/* 1. Top Summary Stat Strip */}
				<div className="grid gap-3 lg:grid-cols-[1fr_1fr_1.4fr_auto]">
					<Stat
						label="Net Unrealized"
						value={
							<span className={toneText(total)}>{fmt.usd(total, 2)}</span>
						}
						delta={avgRoe}
						deltaLabel="avg ROE"
						accent={toneHex(total)}
					/>
					<Stat
						label="Open / Max"
						value={
							<>
								{filteredList.length}
								<span className="text-white/30 text-base"> / 12</span>
							</>
						}
						accent="#0066ff"
						icon={<Crosshair size={14} />}
					/>
					<div className="glass rounded-2xl p-4 animate-fade-up">
						<div className="flex justify-between text-[11px] uppercase tracking-[0.12em] text-white/40">
							<span>Directional Bias</span>
							<span className="font-mono text-white/70">
								{(longShare * 100).toFixed(0)}% long
							</span>
						</div>
						<div className="mt-3 flex h-2.5 overflow-hidden rounded-full bg-white/5">
							<div
								className="bg-gradient-to-r from-emerald-500/60 to-emerald-400 shadow-[0_0_12px_#10e0a0aa]"
								style={{ width: `${longShare * 100}%` }}
							/>
							<div className="flex-1 bg-gradient-to-r from-rose-500 to-rose-500/60" />
						</div>
						<div className="mt-2 flex justify-between font-mono text-[11px]">
							<span className="text-emerald-400">
								L {fmt.usd(longs, 2)}
							</span>
							<span className="text-rose-400">
								S {fmt.usd(shorts, 2)}
							</span>
						</div>
					</div>

					<div className="glass rounded-2xl p-3 flex flex-col justify-between animate-fade-up border-rose-500/20">
						{!confirmStop ? (
							<button
								type="button"
								onClick={() => setConfirmStop(true)}
								className="group flex h-full min-w-[150px] flex-col items-center justify-center gap-1.5 rounded-xl border border-rose-500/30 bg-rose-500/5 px-4 text-rose-400 transition-all hover:bg-rose-500/15 hover:shadow-[0_0_30px_-8px_rgba(244,63,94,0.8)]"
							>
								<AlertOctagon
									size={20}
									className="group-hover:scale-110 transition-transform"
								/>
								<span className="text-[11px] font-bold uppercase tracking-[0.14em]">
									Emergency Stop
								</span>
								<span className="text-[9px] text-rose-400/60 font-mono">
									DELETE /portfolio/positions
								</span>
							</button>
						) : (
							<div className="flex h-full min-w-[150px] flex-col justify-center gap-2 px-1">
								<div className="text-center text-[11px] text-white">
									Close all {filteredList.length} positions?
								</div>
								<div className="flex gap-1.5">
									<Btn
										variant="danger"
										size="xs"
										className="flex-1"
										onClick={handleEmergencyStop}
										disabled={isStopping}
									>
										Confirm
									</Btn>
									<Btn
										variant="ghost"
										size="xs"
										onClick={() => setConfirmStop(false)}
									>
										Cancel
									</Btn>
								</div>
							</div>
						)}
					</div>
				</div>

				{/* 2. Filter & View Toolbar */}
				<div className="flex flex-wrap items-center gap-2">
					<Segmented
						size="sm"
						value={sideF}
						onChange={setSideF}
						options={[
							{ value: "all", label: "All" },
							{
								value: "LONG",
								label: <span className="text-emerald-400">Long</span>,
							},
							{
								value: "SHORT",
								label: <span className="text-rose-400">Short</span>,
							},
						]}
					/>
					<div className="relative">
						<input
							type="text"
							placeholder="Filter symbol..."
							value={symbolFilter}
							onChange={(e) => setSymbolFilter(e.target.value)}
							className="h-7.5 rounded-lg border border-white/10 bg-white/[0.03] px-2.5 text-[11px] text-white placeholder-white/30 outline-none transition-colors focus:border-white/20"
						/>
						{symbolFilter && (
							<button
								type="button"
								onClick={() => setSymbolFilter("")}
								className="absolute right-2 top-1/2 -translate-y-1/2 text-white/30 hover:text-white"
							>
								<X size={11} />
							</button>
						)}
					</div>
					<Btn
						variant="ghost"
						size="sm"
						icon={<RefreshCw size={11} className={isLoading ? "animate-spin" : ""} />}
						onClick={() => refetch()}
					>
						Refresh
					</Btn>
					<span
						className={`rounded-full border px-2 py-0.5 font-mono text-[10px] ${
							wsLive
								? "border-emerald-400/30 text-emerald-300"
								: "border-amber-400/30 text-amber-300"
						}`}
						title={
							wsLive
								? "Live ticks from exchange + push snapshots"
								: "Socket down — polling every 5s"
						}
					>
						{wsLive
							? `live${liveCount > 0 ? ` · ${liveCount}` : ""}`
							: "polling 5s"}
					</span>

					<div className="flex-1" />
					<Segmented
						size="sm"
						value={view}
						onChange={setView}
						options={[
							{ value: "cards", label: "Cards" },
							{ value: "table", label: "Table" },
						]}
					/>
				</div>

				{/* 3. Main Grid (Positions List + Inspector/Feed) */}
				<div className="grid gap-4 xl:grid-cols-[1fr_360px]">
					{/* Left: Position Cards or Table */}
					{view === "cards" ? (
					<div className="grid gap-3 md:grid-cols-2 2xl:grid-cols-3 content-start">
						{filteredList.length === 0 ? (
							<div className="glass rounded-2xl p-8 text-center text-[12px] text-white/35 md:col-span-2 2xl:col-span-3">
								{isLoading
									? "Loading positions…"
									: "No open positions — start a strategy to see live deals here."}
							</div>
						) : (
							filteredList.map((p) => {
								const lo = Math.min(
									p.sl ?? p.entry,
									p.entry,
									p.mark,
								);
								const hi = Math.max(
									p.tp ?? p.entry,
									p.entry,
									p.mark,
								);
								const pos = (v: number) =>
									Math.max(5, Math.min(95, ((v - lo) / (hi - lo || 1)) * 100));
								const active = sel?.id === p.id;

								return (
									<button
										key={p.id}
										type="button"
										onClick={() => setSel(p)}
										className={cn(
											"group glass relative rounded-2xl p-4 text-left transition-all hover:-translate-y-0.5 hover:border-white/15",
											active &&
												"border-cyan/50 shadow-[0_0_40px_-16px_rgba(0,212,255,0.6)]",
										)}
									>
										<div
											className="pointer-events-none absolute inset-x-0 top-0 h-px"
											style={{
												background: `linear-gradient(90deg, transparent, ${toneHex(p.pnl)}88, transparent)`,
											}}
										/>
										<div className="flex items-start justify-between">
											<div>
												<div className="flex items-center gap-2">
													<span className="text-[15px] font-semibold text-white">
														{p.symbol}
													</span>
													<Badge
														tone={p.side === "LONG" ? "profit" : "loss"}
													>
														{p.side} {p.leverage}x
													</Badge>
													<button
														type="button"
														onClick={(e) => {
															e.stopPropagation();
															setChartModalPos(p);
															setIsChartModalOpen(true);
														}}
														className="flex items-center gap-1 rounded-md px-1.5 py-0.5 text-[10px] text-white/40 hover:text-cyan hover:bg-cyan/10 border border-white/5 hover:border-cyan/30 transition-all ml-0.5"
														title="Open Deal Chart"
													>
														<LineChart size={11} />
														<span>Chart</span>
													</button>
												</div>
												<div className="mt-1 flex items-center gap-1.5 text-[10.5px] text-white/40">
													<ExchangeBadge exchange={p.exchange} size="xs" />
													<span>
														{(p.exchange
															? exchangeLabels[p.exchange]
															: null) ||
															p.exchange ||
															"?"} ·{" "}
														{p.openedAgo} · {p.strategy}
													</span>
												</div>
											</div>
											<div className="text-right font-mono">
												<div
													className={cn(
														"text-[16px] font-semibold",
														toneText(p.pnl),
													)}
												>
													{fmt.signed(p.pnl, 2)}
												</div>
												<div
													className={cn(
														"text-[11px] flex items-center justify-end gap-0.5",
														toneText(p.pnlPct),
													)}
												>
													{p.pnlPct > 0 ? (
														<ArrowUpRight size={11} />
													) : (
														<ArrowDownRight size={11} />
													)}
													{fmt.pct(p.pnlPct)}
												</div>
											</div>
										</div>

										<div className="mt-3 flex items-end justify-between">
											<PositionSparkline
												symbol={p.symbol}
												exchange={p.exchange}
												fallbackPrice={p.mark}
												width={150}
												height={36}
												baseline
											/>
											<div className="text-right font-mono text-[10.5px] text-white/50">
												<div>
													size <span className="text-white">{p.size}</span>
												</div>
											<div>
												liq{p.liqEstimated ? " (est.)" : ""}{" "}
												<span className="text-rose-400/80">
													{p.liq.toLocaleString()}
												</span>
											</div>
											</div>
										</div>

										{/* SL / entry / mark / TP visual rail */}
										<div className="mt-3 relative h-6">
											<div className="absolute inset-x-0 top-1/2 h-px bg-gradient-to-r from-rose-500/60 via-white/15 to-emerald-400/60" />
											{[
												{ v: p.sl, c: "#ff3b5c", l: "SL" },
												{ v: p.entry, c: "#8b93a7", l: "E" },
												{ v: p.tp, c: "#10e0a0", l: "TP" },
											].map(
												(m) =>
													m.v != null && (
														<div
															key={m.l}
															className="absolute -translate-x-1/2 flex flex-col items-center"
															style={{ left: `${pos(m.v)}%`, top: 0 }}
														>
															<span
																className="text-[8px] font-mono"
																style={{ color: m.c }}
															>
																{m.l}
															</span>
															<span
																className="h-2 w-px"
																style={{ background: m.c }}
															/>
														</div>
													),
											)}
											<div
												className="absolute -translate-x-1/2 top-1/2 -translate-y-1/2"
												style={{ left: `${pos(p.mark)}%` }}
											>
												<span className="block h-3 w-3 rounded-full border-2 border-obsidian bg-cyan shadow-[0_0_10px_#00d4ff]" />
											</div>
										</div>
									</button>
								);
							})
						)}
					</div>
					) : (
						<Panel noPad>
							<div className="overflow-x-auto">
								<table className="w-full">
									<thead className="border-b border-white/5">
										<tr>
											<Th>Symbol</Th>
											<Th>Side</Th>
											<Th right>Size</Th>
											<Th right>Entry</Th>
											<Th right>Mark</Th>
											<Th right>SL</Th>
											<Th right>TP</Th>
											<Th right>Liq</Th>
											<Th right>P&L</Th>
											<Th />
										</tr>
								</thead>
								<tbody>
									{filteredList.length === 0 ? (
										<tr>
											<td colSpan={10}>
												<div className="flex h-[100px] items-center justify-center px-3 py-2.5 text-center text-[12px] text-white/35">
													{isLoading
														? "Loading positions…"
														: "No open positions — start a strategy to see live deals here."}
												</div>
											</td>
										</tr>
									) : (
										filteredList.map((p) => (
											<tr
												key={p.id}
												onClick={() => setSel(p)}
												className={cn(
													"cursor-pointer border-b border-white/[0.03] hover:bg-white/[0.02]",
													sel?.id === p.id && "bg-cyan/[0.04]",
												)}
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
													{p.entry.toLocaleString()}
												</Td>
												<Td right mono>
													{p.mark.toLocaleString()}
												</Td>
												<Td right mono className="text-rose-400/80">
													{p.sl?.toLocaleString() ?? "—"}
												</Td>
												<Td right mono className="text-emerald-400/80">
													{p.tp?.toLocaleString() ?? "—"}
												</Td>
											<Td right mono className="text-white/40">
												{p.liq.toLocaleString()}
												{p.liqEstimated ? (
													<span className="text-white/25"> *</span>
												) : null}
											</Td>
												<Td
													right
													mono
													className={cn("font-semibold", toneText(p.pnl))}
												>
													{fmt.signed(p.pnl, 2)}
												</Td>
												<Td>
													<div className="flex items-center justify-end gap-1">
														<button
															type="button"
															onClick={(e) => {
																e.stopPropagation();
																setChartModalPos(p);
																setIsChartModalOpen(true);
															}}
															className="text-white/40 hover:text-cyan transition-colors p-1.5 rounded hover:bg-white/5"
															title="Open Deal Chart"
														>
															<LineChart size={13} />
														</button>
														<button
															type="button"
															onClick={(e) => {
																e.stopPropagation();
																handleClose(p.symbol, p.apiKeyId);
															}}
															className="text-white/30 hover:text-rose-400 transition-colors p-1.5 rounded hover:bg-white/5"
															title="Close Position"
														>
															<X size={13} />
														</button>
													</div>
											</Td>
										</tr>
										))
									)}
								</tbody>
								</table>
							</div>
						</Panel>
					)}

					{/* Right: Inspector & Trade Feed */}
					<div className="space-y-4">
						{sel ? (
							<Panel
								title={
									<span className="flex items-center gap-2">
										<ExchangeBadge exchange={sel.exchange} size="xs" />
										{sel.symbol}{" "}
										<Badge tone={sel.side === "LONG" ? "profit" : "loss"}>
											{sel.side} {sel.leverage}x
										</Badge>
									</span>
								}
								subtitle={`PATCH /positions/${sel.id}`}
								glow
							>
								<div className="grid grid-cols-2 gap-2.5">
									{[
										["Entry", sel.entry],
										["Mark", sel.mark],
										["Size", sel.size],
										["Notional", sel.size * sel.mark],
									].map(([l, v]) => (
										<div
											key={l as string}
											className="rounded-lg border border-white/5 bg-white/[0.02] p-2.5"
										>
											<div className="text-[10px] uppercase tracking-wider text-white/35">
												{l}
											</div>
											<div className="font-mono text-[13px] text-white">
												{(v as number).toLocaleString(undefined, {
													maximumFractionDigits: 2,
												})}
											</div>
										</div>
									))}
								</div>

								<div className="mt-4 space-y-3">
									<SectionLabel>Risk controls</SectionLabel>
									<div>
										<div className="mb-1 flex items-center justify-between text-[11px]">
											<span className="text-white/60">Stop Loss</span>
											<span className="font-mono text-rose-400">
												{selSl && !Number.isNaN(Number(selSl))
													? (((Number(selSl) - sel.mark) / sel.mark) * 100).toFixed(2) + "%"
													: "—"}
											</span>
										</div>
										<div className="flex items-center gap-2 rounded-lg border border-rose-500/20 bg-white/[0.02] px-2.5 py-1.5 focus-within:border-cyan/40">
											<Shield size={12} className="text-rose-400 shrink-0" />
											<input
												value={selSl}
												onChange={(e) => setSelSl(e.target.value)}
												placeholder="not set"
												className="flex-1 bg-transparent font-mono text-[12px] text-white outline-none"
											/>
											<Pencil size={11} className="text-white/30 shrink-0" />
										</div>
									</div>

									<div>
										<div className="mb-1 flex items-center justify-between text-[11px]">
											<span className="text-white/60">Take Profit</span>
											<span className="font-mono text-emerald-400">
												{selTp && !Number.isNaN(Number(selTp))
													? (((Number(selTp) - sel.mark) / sel.mark) * 100).toFixed(2) + "%"
													: "—"}
											</span>
										</div>
										<div className="flex items-center gap-2 rounded-lg border border-emerald-500/20 bg-white/[0.02] px-2.5 py-1.5 focus-within:border-cyan/40">
											<Shield size={12} className="text-emerald-400 shrink-0" />
											<input
												value={selTp}
												onChange={(e) => setSelTp(e.target.value)}
												placeholder="not set"
												className="flex-1 bg-transparent font-mono text-[12px] text-white outline-none"
											/>
											<Pencil size={11} className="text-white/30 shrink-0" />
										</div>
									</div>

									<div className="flex gap-2 pt-1">
										<Btn
											variant="primary"
											className="flex-1"
											onClick={handleUpdateSlTp}
											disabled={isUpdatingSlTp}
										>
											Update SL / TP
										</Btn>
										<Btn
											variant="danger"
											icon={<X size={12} />}
											onClick={() => handleClose(sel.symbol, sel.apiKeyId)}
											disabled={isClosing}
										>
											Close
										</Btn>
									</div>
									<Btn
										variant="outline"
										className="w-full mt-1.5"
										icon={<LineChart size={12} />}
										onClick={() => {
											setChartModalPos(sel);
											setIsChartModalOpen(true);
										}}
									>
										Open Deal Chart
									</Btn>
								</div>

								<div className="mt-4 rounded-xl border border-white/5 bg-gradient-to-br from-white/[0.03] to-transparent p-3">
								<div className="flex items-center gap-2 text-[11px] text-white/60">
									<Flame size={12} className="text-amber-400" />
									Liquidation buffer
									{sel.liqEstimated ? (
										<span className="text-[9px] text-white/30">
											(est.)
										</span>
									) : null}
								</div>
									<div className="mt-1 font-mono text-[18px] font-semibold text-white">
										{Math.abs(((sel.liq - sel.mark) / sel.mark) * 100).toFixed(1)}%
									</div>
									<Bar
										value={Math.min(
											1,
											Math.abs((sel.liq - sel.mark) / sel.mark) / 0.4,
										)}
										color="linear-gradient(90deg,#ff3b5c,#ffb547,#10e0a0)"
										className="mt-2"
									/>
								</div>
							</Panel>
						) : null}

					<Panel title="Trade Feed" subtitle="/trades · recent fills" noPad>
						<div className="divide-y divide-white/[0.03]">
							{recentTrades.length === 0 ? (
								<div className="flex h-[100px] items-center justify-center px-4 text-center text-[11px] text-white/35">
									No recent fills — closed trades will show up
									here.
								</div>
							) : (
								recentTrades.map((t) => {
									const isLong = t.direction === "LONG";
									const price = t.exit_price ?? t.entry_price ?? 0;
									return (
										<div
											key={t.id}
											className="flex items-center gap-3 px-4 py-2 text-[11.5px]"
										>
											<span
												className={cn(
													"w-12 font-bold text-[10px]",
													isLong
														? "text-emerald-400"
														: "text-rose-400",
												)}
											>
												{t.direction}
											</span>
											<span className="text-white flex-1">
												{t.symbol}
											</span>
											<span className="font-mono text-white/60">
												{(t.quantity ?? 0).toLocaleString()}
											</span>
											<span className="font-mono text-white/40">
												@ {Number(price).toLocaleString()}
											</span>
										</div>
									);
								})
							)}
						</div>
					</Panel>
					</div>
				</div>
			</div>

			{/* Position Deal Chart Modal (full passthrough: executions + SL/TP rails) */}
			{chartModalPos && (
				<PositionChartModal
					position={{
						id: String(chartModalPos.id),
						symbol: chartModalPos.symbol,
						strategy: chartModalPos.strategy || "Quant Engine",
						direction: (chartModalPos.side || chartModalPos.direction || "LONG").toUpperCase() as
							| "LONG"
							| "SHORT",
						size: Number(chartModalPos.size) || 0,
						entry_price:
							Number(chartModalPos.entry_price ?? chartModalPos.entry) || 0,
						mark_price:
							Number(
								chartModalPos.mark_price ??
									chartModalPos.mark ??
									chartModalPos.entry_price ??
									chartModalPos.entry,
							) || 0,
						pnl: Number(chartModalPos.pnl) || 0,
						pnl_percent: Number(chartModalPos.pnl_percent ?? chartModalPos.pnlPct) || 0,
						entry_time:
							chartModalPos.entry_time ||
							chartModalPos.entryTime ||
							new Date().toISOString(),
						stop_loss:
							chartModalPos.stop_loss ?? chartModalPos.sl != null
								? Number(chartModalPos.stop_loss ?? chartModalPos.sl)
								: undefined,
						take_profit:
							chartModalPos.take_profit ?? chartModalPos.tp != null
								? Number(chartModalPos.take_profit ?? chartModalPos.tp)
								: undefined,
						api_key_id: chartModalPos.api_key_id ?? chartModalPos.apiKeyId,
						exchange:
							chartModalPos.exchange ?? chartModalPos.exchange_id ?? null,
						executions: chartModalPos.executions ?? [],
						signal_details_json: chartModalPos.signal_details_json,
						partial_tp_orders: chartModalPos.partial_tp_orders,
						dca_orders: chartModalPos.dca_orders,
						market_type: "futures_usdtm",
					} as PositionData}
					isOpen={isChartModalOpen}
					onClose={() => setIsChartModalOpen(false)}
				onSave={(data) => {
					updateSlTp(
						{
							positionId: chartModalPos.id,
							stop_loss: data.stop_loss,
							take_profit: data.take_profit,
						},
						{
							onSuccess: () => {
								toast.success(
									`SL/TP updated for ${chartModalPos.symbol}`,
								);
								refetch();
								setIsChartModalOpen(false);
							},
						},
					);
				}}
				/>
			)}
		</PageLayout>
	);
}
