// frontend/src/pages/SharedTradePage.tsx

import { format, parseISO } from "date-fns";
import {
	AlertCircle,
	BarChart3,
	CheckCircle2,
	Clock,
	Coins,
	Gift,
	ShieldCheck,
} from "lucide-react";
import type React from "react";
import { useEffect, useMemo } from "react";
import { Helmet } from "react-helmet-async";
import { useTranslation } from "react-i18next";
import { Link, useLocation, useParams, useSearchParams } from "react-router-dom";
import { TradeChart } from "@/components/analytics/TradeChart";
import { AppLoader } from "@/components/shared/AppLoader";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Logo } from "@/components/ui/logo";
import { useSharedTradeData } from "@/lib/api";
import { exchangeLabels, exchangeLogos, normalizeExchangeKey } from "@/lib/exchanges";
import { formatCryptoPrice } from "@/lib/formatters";
import type { TradeData } from "@/types/api";

export const SharedTradePage: React.FC = () => {
	const { publicSlug } = useParams<{ publicSlug: string }>();
	const [searchParams] = useSearchParams();
	const location = useLocation();
	const { t } = useTranslation(["analytics", "common"]);

	const { data: sharedData, isLoading, isError, error } = useSharedTradeData(
		publicSlug || null,
	);

	// Capture referral code from URL query (?ref=...) or from the shared trade payload
	const refFromUrl = searchParams.get("ref");
	const effectiveRef = refFromUrl || sharedData?.referralCode || "";

	useEffect(() => {
		if (effectiveRef) {
			try {
				localStorage.setItem("depthsight_referral_code", effectiveRef);
				localStorage.setItem("depthsight_ref_source", `trade_${publicSlug}`);
			} catch {
				// Ignore storage errors in private browsing
			}
		}
	}, [effectiveRef, publicSlug]);

	const canonicalUrl = `${window.location.origin}${location.pathname}`;
	const ogImageUrl = `${window.location.origin}/og-image/trade/${publicSlug}.png`;

	// Convert shared trade data into TradeData shape for the chart component
	const adaptedTrade: TradeData | null = useMemo(() => {
		if (!sharedData) return null;
		const closeTime = typeof sharedData.timestampClose === "string" 
			? new Date(sharedData.timestampClose).getTime() 
			: Number(sharedData.timestampClose);
		const entryTime = sharedData.timestampEntry
			? typeof sharedData.timestampEntry === "string"
				? new Date(sharedData.timestampEntry).getTime()
				: Number(sharedData.timestampEntry)
			: closeTime - (sharedData.durationSeconds ? sharedData.durationSeconds * 1000 : 3600 * 1000);

		return {
			id: sharedData.id,
			trade_uuid: sharedData.tradeUuid,
			symbol: sharedData.symbol,
			direction: (sharedData.direction === "SHORT" ? "SHORT" : "LONG"),
			entry_price: sharedData.entryPrice,
			exit_price: sharedData.exitPrice,
			pnl: sharedData.pnl,
			quantity: sharedData.quantity,
			timestamp_entry: entryTime,
			timestamp_signal: entryTime,
			timestamp_close: closeTime,
			exit_reason: sharedData.exitReason,
			strategy: sharedData.strategyName,
			exchange: sharedData.exchange,
			trade_mode: "LIVE",
			max_floating_profit: sharedData.maxFloatingProfit,
			max_floating_loss: sharedData.maxFloatingLoss,
		};
	}, [sharedData]);

	if (isLoading) {
		return <AppLoader text={t("common:loading", "Loading trade execution...")} />;
	}

	if (isError || !sharedData) {
		return (
			<div className="min-h-screen bg-[#070a11] text-white flex items-center justify-center p-4">
				<Alert variant="destructive" className="max-w-md bg-red-950/40 border-red-500/30">
					<AlertCircle className="h-5 w-5" />
					<AlertTitle>{t("common:error", "Trade Not Found")}</AlertTitle>
					<AlertDescription>
						{error?.message || t("tradeHistory.notFoundDesc", "This trade report does not exist or access has been restricted by the author.")}
					</AlertDescription>
				</Alert>
			</div>
		);
	}

	const isProfit = (sharedData.pnlDisplayMode === "PERCENT" 
		? (sharedData.roiPct || 0) 
		: (sharedData.pnl || 0)) >= 0;

	const registerUrl = effectiveRef 
		? `/register?ref=${encodeURIComponent(effectiveRef)}` 
		: "/register";

	// Formatted duration
	const durationFormatted = (() => {
		if (!sharedData.durationSeconds) return "—";
		const hours = Math.floor(sharedData.durationSeconds / 3600);
		const minutes = Math.floor((sharedData.durationSeconds % 3600) / 60);
		if (hours > 0) return `${hours}h ${minutes}m`;
		return `${minutes}m`;
	})();

	const metaTitle = `DepthSight Real Trade: ${sharedData.symbol} (${sharedData.direction})`;
	const metaDesc = `Real trade execution on ${sharedData.symbol} closed via ${sharedData.exitReason || "Take Profit"}. View verified live execution on DepthSight Platform.`;

	return (
		<div className="min-h-screen bg-[#070a11] text-gray-100 flex flex-col antialiased">
			<Helmet>
				<title>{metaTitle}</title>
				<meta name="description" content={metaDesc} />
				<link rel="canonical" href={canonicalUrl} />
				<meta property="og:title" content={metaTitle} />
				<meta property="og:description" content={metaDesc} />
				<meta property="og:image" content={ogImageUrl} />
				<meta property="og:url" content={canonicalUrl} />
				<meta name="twitter:card" content="summary_large_image" />
				<meta name="twitter:image" content={ogImageUrl} />
			</Helmet>

			{/* Top Navbar */}
			<header className="sticky top-0 z-50 w-full border-b bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60">
				<div className="container mx-auto flex h-20 max-w-5xl items-center justify-between">
					<Link to="/" className="flex items-center gap-2">
						<Logo className="h-12" />
					</Link>
					<Button asChild>
						<Link to={registerUrl}>Start for free</Link>
					</Button>
				</div>
			</header>

			{/* Main Container */}
			<main className="flex-1 max-w-7xl w-full mx-auto p-4 sm:p-6 lg:p-8 space-y-6">
				
				{/* 1. Welcome Bonus Promo Banner */}
				<div className="relative overflow-hidden rounded-2xl border border-white/10 bg-[#090d16]/95 backdrop-blur p-4 sm:p-5 shadow-lg">
					<div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 relative z-10">
						<div className="flex items-center gap-3.5">
							<div className="w-11 h-11 rounded-xl bg-white/[0.04] border border-white/10 flex items-center justify-center text-primary shrink-0">
								<Gift className="w-5 h-5 text-primary" />
							</div>
							<div>
								<div className="flex items-center gap-2">
									<h2 className="text-sm sm:text-base font-semibold text-white">
										{t("tradeHistory.bonusBannerTitle", "Welcome Bonus: 1,000 DepthSight Tokens")}
									</h2>
									<span className="px-2 py-0.5 rounded-full text-[10px] font-mono bg-primary/10 text-primary border border-primary/20 uppercase font-semibold">
										{t("tradeHistory.exclusiveReward", "Special Invite")}
									</span>
								</div>
								<p className="text-xs text-muted-foreground mt-0.5">
									{t(
										"tradeHistory.bonusBannerDesc",
										"Sign up using this trade report link to automatically claim 1,000 DepthSight tokens and start automated algorithmic trading.",
									)}
								</p>
							</div>
						</div>

						<Button asChild className="shrink-0 font-medium">
							<Link to={registerUrl}>
								<Coins className="w-4 h-4 mr-1.5" />
								{t("tradeHistory.claimBonusBtn", "Claim 1,000 Tokens")}
							</Link>
						</Button>
					</div>
				</div>

				{/* 2. Hero Trade Summary Card */}
				<div className="rounded-3xl border border-white/10 bg-gradient-to-br from-[#0c111c] via-[#090d16] to-[#04060b] p-6 shadow-2xl relative overflow-hidden">
					<div
						className={`absolute -top-24 -left-24 w-80 h-80 rounded-full blur-[100px] pointer-events-none ${
							isProfit ? "bg-emerald-500/15" : "bg-red-500/15"
						}`}
					/>

					<div className="relative z-10 space-y-6">
						{/* Card Header Row */}
						<div className="flex flex-wrap items-center justify-between gap-3 border-b border-white/5 pb-4">
							<div className="flex items-center gap-3">
								<h1 className="font-display font-black text-3xl sm:text-4xl text-white tracking-tight">
									{sharedData.symbol}
								</h1>
								<span
									className={`px-3 py-1 rounded-lg text-xs font-black tracking-widest uppercase ${
										["LONG", "BUY"].includes(sharedData.direction.toUpperCase())
											? "bg-emerald-500/20 text-emerald-400 border border-emerald-500/40"
											: "bg-purple-500/20 text-purple-400 border border-purple-500/40"
									}`}
								>
									{sharedData.direction}
								</span>
								{sharedData.strategyName && (
									<span className="px-2.5 py-1 rounded-md text-xs font-mono text-cyan-400 bg-cyan-500/10 border border-cyan-500/20">
										⚡ {sharedData.strategyName}
									</span>
								)}
							</div>

							<div className="flex items-center gap-2 font-mono text-xs">
								<span className="flex items-center gap-1.5 px-3 py-1 rounded-full bg-emerald-500/10 text-emerald-400 border border-emerald-500/30 font-semibold tracking-wider uppercase">
									<ShieldCheck className="w-3.5 h-3.5 text-emerald-400" />
									Verified Real Execution
								</span>
								<span className="flex items-center gap-2 px-3 py-1 rounded-full bg-white/[0.04] text-gray-300 border border-white/10 font-semibold uppercase">
									{(() => {
										const norm = normalizeExchangeKey(sharedData.exchange);
										const logo = norm ? exchangeLogos[norm] : null;
										const label = (norm ? exchangeLabels[norm] : sharedData.exchange || "Binance").toUpperCase();
										return (
											<>
												{logo && (
													<span className="w-5 h-5 rounded-full bg-white flex items-center justify-center p-0.5 shrink-0 shadow-sm border border-black/10 overflow-hidden">
														<img src={logo} alt={label} className="w-3.5 h-3.5 object-contain" />
													</span>
												)}
												{label} USDT-M
											</>
										);
									})()}
								</span>
							</div>
						</div>

						{/* Hero Metric & Stat Grid */}
						<div className="grid grid-cols-1 lg:grid-cols-12 gap-6 items-center">
							
							{/* Left 5 cols: Big Highlighted PnL */}
							<div className="lg:col-span-5 space-y-1">
								<div className="text-xs font-mono uppercase tracking-wider text-gray-400 font-semibold">
									{sharedData.pnlDisplayMode === "USD"
										? "Net Realized Profit (USD)"
										: sharedData.pnlDisplayMode === "BOTH"
											? "Net Profit & ROI"
											: "Return on Investment (ROI)"}
								</div>
								<div className="flex items-baseline gap-3 flex-wrap">
									<span
										className={`font-mono text-4xl sm:text-5xl lg:text-6xl font-black tracking-tight leading-none ${
											isProfit ? "text-emerald-400" : "text-red-400"
										}`}
									>
										{sharedData.pnlDisplayMode === "USD"
											? `${(sharedData.pnl || 0) >= 0 ? "+" : ""}$${(sharedData.pnl || 0).toFixed(2)}`
											: `${(sharedData.roiPct || 0) >= 0 ? "+" : ""}${(sharedData.roiPct || 0).toFixed(2)}%`}
									</span>

									{sharedData.pnlDisplayMode === "BOTH" && sharedData.pnl !== undefined && (
										<span className="font-mono text-xl sm:text-2xl font-bold text-gray-400 leading-none">
											({sharedData.pnl >= 0 ? "+" : ""}${sharedData.pnl.toFixed(2)} USD)
										</span>
									)}
								</div>
								<p className="text-[11px] font-mono text-gray-500 pt-1">
									Closed on: {format(parseISO(sharedData.timestampClose), "dd.MM.yyyy HH:mm:ss")}
								</p>
							</div>

							{/* Right 7 cols: Key Parameters Grid */}
							<div className="lg:col-span-7 grid grid-cols-2 sm:grid-cols-4 gap-3">
								<div className="bg-white/[0.03] border border-white/5 rounded-2xl p-3.5 space-y-1">
									<div className="text-[10px] font-mono text-gray-400 uppercase">Entry Price</div>
									<div className="text-sm sm:text-base font-mono font-bold text-white">
										{sharedData.entryPrice ? `$${formatCryptoPrice(sharedData.entryPrice)}` : "—"}
									</div>
								</div>

								<div className="bg-white/[0.03] border border-white/5 rounded-2xl p-3.5 space-y-1">
									<div className="text-[10px] font-mono text-gray-400 uppercase">Exit Price</div>
									<div className="text-sm sm:text-base font-mono font-bold text-white">
										{sharedData.exitPrice ? `$${formatCryptoPrice(sharedData.exitPrice)}` : "—"}
									</div>
								</div>

								<div className="bg-white/[0.03] border border-white/5 rounded-2xl p-3.5 space-y-1">
									<div className="text-[10px] font-mono text-gray-400 uppercase">
										{sharedData.quantity ? "Position Size" : "Duration"}
									</div>
									<div className="text-sm sm:text-base font-mono font-bold text-white flex items-center gap-1.5">
										{sharedData.quantity ? (
											`${sharedData.quantity} ${sharedData.symbol.replace("USDT", "").replace("BUSD", "").replace("USDC", "").trim()}`
										) : (
											<>
												<Clock className="w-3.5 h-3.5 text-gray-400" />
												{durationFormatted}
											</>
										)}
									</div>
								</div>

								<div className="bg-white/[0.03] border border-white/5 rounded-2xl p-3.5 space-y-1">
									<div className="text-[10px] font-mono text-gray-400 uppercase">Exit Reason</div>
									<div className="text-sm sm:text-base font-mono font-bold text-emerald-400 truncate">
										{sharedData.exitReason || "Take Profit"}
									</div>
								</div>
							</div>

						</div>
					</div>
				</div>

				{/* 3. Interactive Candlestick Chart with Entry & Exit Execution */}
				<div className="rounded-3xl border border-white/10 bg-[#090d16] p-6 shadow-2xl space-y-4">
					<div className="flex flex-wrap items-center justify-between gap-3 border-b border-white/5 pb-3">
						<div className="flex items-center gap-2">
							<BarChart3 className="w-5 h-5 text-cyan-400" />
							<h3 className="font-semibold text-sm sm:text-base text-white">
								{t("tradeHistory.chartTitle", "Live Execution Chart & Markers")}
							</h3>
						</div>
						<span className="text-xs font-mono text-gray-400">
							Green Arrow = Entry • Red/Green Flag = Exit
						</span>
					</div>

					{adaptedTrade && (
						<div className="w-full">
							<TradeChart
								trades={[adaptedTrade]}
								symbol={sharedData.symbol}
								selectedTrade={adaptedTrade}
								exchange={sharedData.exchange}
							/>
						</div>
					)}
				</div>

				{/* 4. Bottom Call To Action / Platform Overview */}
				<div className="rounded-3xl border border-white/10 bg-gradient-to-br from-[#0e1424] via-[#090d16] to-[#060810] p-8 text-center space-y-5 shadow-2xl">
					<div className="max-w-2xl mx-auto space-y-2">
						<h3 className="text-xl sm:text-2xl font-display font-black text-white">
							Trade Smarter with DepthSight AI Platform
						</h3>
						<p className="text-xs sm:text-sm text-gray-400">
							Connect Binance, Bybit, OKX, Bitget, WEEX or Hyperliquid in 2 minutes. Build no-code visual strategies, run genetic optimizations, and automate your trading 24/7.
						</p>
					</div>

					{/* Supported Exchanges Strip */}
					<div className="flex flex-wrap items-center justify-center gap-2.5 sm:gap-4 py-1">
						{[
							{ id: "binance", name: "Binance" },
							{ id: "bybit", name: "Bybit" },
							{ id: "okx", name: "OKX" },
							{ id: "bitget", name: "Bitget" },
							{ id: "weex", name: "WEEX" },
							{ id: "hyperliquid", name: "Hyperliquid" },
						].map((ex) => {
							const logo = exchangeLogos[ex.id];
							return (
								<div
									key={ex.id}
									className="flex items-center gap-2 px-3 py-1.5 rounded-xl bg-white/[0.03] border border-white/5 hover:border-white/10 transition-colors"
								>
									{logo && (
										<span className="w-5 h-5 rounded-full bg-white flex items-center justify-center p-0.5 shrink-0 shadow-sm border border-black/10 overflow-hidden">
											<img
												src={logo}
												alt={ex.name}
												className="w-3.5 h-3.5 object-contain"
											/>
										</span>
									)}
									<span className="text-xs font-mono font-semibold text-gray-300">
										{ex.name}
									</span>
								</div>
							);
						})}
					</div>

					<div className="flex flex-wrap items-center justify-center gap-4 pt-2">
						<Button asChild size="lg">
							<Link to={registerUrl}>
								<Coins className="w-4 h-4 mr-2" />
								Get 1,000 Bonus Tokens & Start Free
							</Link>
						</Button>
					</div>

					<div className="flex items-center justify-center gap-6 text-[11px] font-mono text-gray-500 pt-2">
						<span className="flex items-center gap-1.5">
							<CheckCircle2 className="w-3.5 h-3.5 text-cyan-400" />
							Non-Custodial API
						</span>
						<span className="flex items-center gap-1.5">
							<CheckCircle2 className="w-3.5 h-3.5 text-cyan-400" />
							Paper Trading Included
						</span>
						<span className="flex items-center gap-1.5">
							<CheckCircle2 className="w-3.5 h-3.5 text-cyan-400" />
							Institutional Level Latency
						</span>
					</div>
				</div>

			</main>
		</div>
	);
};
