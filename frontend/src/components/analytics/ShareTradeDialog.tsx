// frontend/src/components/analytics/ShareTradeDialog.tsx

import { Check, Copy, Download, Loader2 } from "lucide-react";
import type React from "react";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import {
	Dialog,
	DialogContent,
	DialogDescription,
	DialogHeader,
	DialogTitle,
} from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { useToast } from "@/components/ui/use-toast";
import { useAuth } from "@/context/AuthContext";
import { useShareTrade } from "@/lib/api";
import { exchangeLabels, exchangeLogos, normalizeExchangeKey } from "@/lib/exchanges";
import { formatCryptoPrice } from "@/lib/formatters";
import type { TradeData } from "@/types/api";

const ExchangeIcon: React.FC<{ exchange?: string | null; className?: string }> = ({
	exchange,
	className = "w-3 h-3 sm:w-3.5 sm:h-3.5 object-contain block shrink-0",
}) => {
	const ex = normalizeExchangeKey(exchange) || "binance";
	const logo = exchangeLogos[ex];
	const label = exchangeLabels[ex] || exchange || "Exchange";
	if (logo) {
		return (
			<span className="w-4 h-4 sm:w-[18px] sm:h-[18px] rounded-full bg-white flex items-center justify-center p-0.5 shrink-0 shadow-sm border border-black/10 overflow-hidden">
				<img src={logo} alt={label} className={className} draggable={false} />
			</span>
		);
	}
	return <span className="text-xs">◆</span>;
};

interface ShareTradeDialogProps {
	open: boolean;
	onOpenChange: (open: boolean) => void;
	trade: TradeData | null;
}

export const ShareTradeDialog: React.FC<ShareTradeDialogProps> = ({
	open,
	onOpenChange,
	trade,
}) => {
	const { t } = useTranslation(["analytics", "common"]);
	const { toast } = useToast();
	const { user } = useAuth();

	// Defaults: Private mode by default
	const [pnlDisplayMode, setPnlDisplayMode] = useState<"PERCENT" | "USD" | "BOTH">("PERCENT");
	const [isStrategyNamePublic, setIsStrategyNamePublic] = useState(false);
	const [isQuantityPublic, setIsQuantityPublic] = useState(false);

	const [generatedUrl, setGeneratedUrl] = useState<string | null>(null);
	const [publicSlug, setPublicSlug] = useState<string | null>(null);
	const [hasCopied, setHasCopied] = useState(false);
	const [isDownloading, setIsDownloading] = useState(false);

	const { mutate: shareTrade, isPending } = useShareTrade();

	// Calculate ROI %
	const roiPct = (() => {
		if (!trade || !trade.entry_price || !trade.exit_price || trade.entry_price <= 0) return 0;
		const isLongSide = ["LONG", "BUY"].includes((trade.direction || "LONG").toUpperCase());
		if (isLongSide) {
			return ((trade.exit_price - trade.entry_price) / trade.entry_price) * 100;
		}
		return ((trade.entry_price - trade.exit_price) / trade.entry_price) * 100;
	})();

	const pnlUsd = trade?.pnl || 0;
	const isProfit = (pnlDisplayMode === "PERCENT" ? roiPct : pnlUsd) >= 0;
	const isLong = ["LONG", "BUY"].includes((trade?.direction || "LONG").toUpperCase());

	// Duration formatting
	const durationFormatted = (() => {
		if (!trade?.timestamp_close || !trade?.timestamp_entry) return "—";
		const start = typeof trade.timestamp_entry === "number" ? trade.timestamp_entry : new Date(trade.timestamp_entry).getTime();
		const close = typeof trade.timestamp_close === "number" ? trade.timestamp_close : new Date(trade.timestamp_close).getTime();
		const diffSec = Math.floor(Math.abs(close - start) / 1000);
		const hours = Math.floor(diffSec / 3600);
		const minutes = Math.floor((diffSec % 3600) / 60);
		if (hours > 0) return `${hours}h ${minutes}m`;
		return `${minutes}m`;
	})();

	const closeTimeFormatted = (() => {
		if (!trade?.timestamp_close) return "—";
		const d = new Date(trade.timestamp_close);
		if (Number.isNaN(d.getTime())) return String(trade.timestamp_close).slice(0, 16);
		const day = String(d.getDate()).padStart(2, "0");
		const month = String(d.getMonth() + 1).padStart(2, "0");
		const year = d.getFullYear();
		const hours = String(d.getHours()).padStart(2, "0");
		const mins = String(d.getMinutes()).padStart(2, "0");
		return `${day}.${month}.${year} ${hours}:${mins}`;
	})();

	const symbolRaw = trade?.symbol || "Asset";
	const baseAsset = symbolRaw.replace("USDT", "").replace("BUSD", "").replace("USDC", "").trim() || "COIN";

	// Generate trajectory curve points for preview exactly matching template
	const { previewAreaD, previewLineD, lastPtX, lastPtY } = (() => {
		if (isProfit) {
			const areaD = "M 0 65 Q 40 60 70 45 T 140 25 T 200 10 L 200 80 L 0 80 Z";
			const lineD = "M 0 65 Q 40 60 70 45 T 140 25 T 200 10";
			return { previewAreaD: areaD, previewLineD: lineD, lastPtX: 200, lastPtY: 10 };
		}
		const areaD = "M 0 15 Q 40 25 70 45 T 140 60 T 200 70 L 200 80 L 0 80 Z";
		const lineD = "M 0 15 Q 40 25 70 45 T 140 60 T 200 70";
		return { previewAreaD: areaD, previewLineD: lineD, lastPtX: 200, lastPtY: 70 };
	})();

	const ensureLink = (action: (url: string, slug: string) => void) => {
		if (!trade) return;
		if (generatedUrl && publicSlug) {
			action(generatedUrl, publicSlug);
			return;
		}

		shareTrade(
			{
				tradeId: trade.id,
				pnlDisplayMode,
				isStrategyNamePublic,
				isQuantityPublic,
				isPricesPublic: true,
			},
			{
				onSuccess: (data) => {
					setGeneratedUrl(data.shareUrl);
					setPublicSlug(data.publicSlug);
					action(data.shareUrl, data.publicSlug);
				},
				onError: (err) => {
					toast({
						title: t("common:error", "Error"),
						description: err.message,
						variant: "destructive",
					});
				},
			},
		);
	};

	const handleCopy = () => {
		ensureLink((url) => {
			navigator.clipboard.writeText(url).then(() => {
				setHasCopied(true);
				toast({
					title: t("common:copiedToClipboard", "Copied!"),
					description: url,
				});
				setTimeout(() => setHasCopied(false), 2000);
			});
		});
	};

	const handleTelegramShare = () => {
		ensureLink((url) => {
			const pnlText = pnlDisplayMode === "USD"
				? `${pnlUsd >= 0 ? "+" : ""}$${pnlUsd.toFixed(2)} USD`
				: pnlDisplayMode === "BOTH"
					? `${roiPct >= 0 ? "+" : ""}${roiPct.toFixed(2)}% (${pnlUsd >= 0 ? "+" : ""}$${pnlUsd.toFixed(2)} USD)`
					: `${roiPct >= 0 ? "+" : ""}${roiPct.toFixed(2)}% ROI`;
			const text = `DepthSight Real Trade on ${trade?.symbol} (${trade?.direction}): ${pnlText}!\nCheck verified execution & claim +1,000 DepthSight bonus tokens:`;
			const tgUrl = `https://t.me/share/url?url=${encodeURIComponent(url)}&text=${encodeURIComponent(text)}`;
			window.open(tgUrl, "_blank", "noopener,noreferrer");
		});
	};

	const handleTwitterShare = () => {
		ensureLink((url) => {
			const pnlText = pnlDisplayMode === "USD"
				? `${pnlUsd >= 0 ? "+" : ""}$${pnlUsd.toFixed(2)} USD`
				: pnlDisplayMode === "BOTH"
					? `${roiPct >= 0 ? "+" : ""}${roiPct.toFixed(2)}% (${pnlUsd >= 0 ? "+" : ""}$${pnlUsd.toFixed(2)} USD)`
					: `${roiPct >= 0 ? "+" : ""}${roiPct.toFixed(2)}% ROI`;
			const text = `Real trade execution on ${trade?.symbol} (${trade?.direction}): ${pnlText}! Verified on @depthsight.\nClaim +1,000 bonus tokens:`;
			const twUrl = `https://twitter.com/intent/tweet?text=${encodeURIComponent(text)}&url=${encodeURIComponent(url)}&hashtags=DepthSight,Crypto,Trading`;
			window.open(twUrl, "_blank", "noopener,noreferrer");
		});
	};

	const handleDownloadOgImage = () => {
		ensureLink(async (_url, slug) => {
			try {
				setIsDownloading(true);
				const res = await fetch(`/og-image/trade/${slug}.png`);
				if (!res.ok) throw new Error("Could not generate card image from server");
				const blob = await res.blob();
				const blobUrl = window.URL.createObjectURL(blob);
				const a = document.createElement("a");
				a.href = blobUrl;
				a.download = `depthsight-trade-${slug}.png`;
				document.body.appendChild(a);
				a.click();
				window.URL.revokeObjectURL(blobUrl);
				document.body.removeChild(a);
				toast({
					title: t("common:success", "Success"),
					description: t("tradeHistory.downloadSuccess", "Trade card downloaded as PNG"),
				});
			} catch (err: unknown) {
				const errorMsg = err instanceof Error ? err.message : "Failed to download image";
				toast({
					title: t("common:error", "Error"),
					description: errorMsg,
					variant: "destructive",
				});
			} finally {
				setIsDownloading(false);
			}
		});
	};

	const handleModeChange = (mode: "PERCENT" | "USD" | "BOTH") => {
		setPnlDisplayMode(mode);
		setGeneratedUrl(null);
		setPublicSlug(null);
	};

	const handleStrategyToggle = (checked: boolean) => {
		setIsStrategyNamePublic(checked);
		setGeneratedUrl(null);
		setPublicSlug(null);
	};

	const handleQuantityToggle = (checked: boolean) => {
		setIsQuantityPublic(checked);
		setGeneratedUrl(null);
		setPublicSlug(null);
	};

	if (!trade) return null;

	const refCode = user?.referralCode || user?.username || "DEPTHSIGHT";
	const normEx = normalizeExchangeKey(trade.exchange) || "binance";
	const exchangeLabel = (exchangeLabels[normEx] || trade.exchange || "Binance").toUpperCase();
	const exchangeDisplay = `${exchangeLabel} USDT-M`;

	return (
		<Dialog open={open} onOpenChange={onOpenChange}>
			<DialogContent className="max-w-3xl bg-[#070a11] border border-white/10 text-white shadow-2xl p-5 sm:p-6">
				<DialogHeader>
					<DialogTitle>{t("tradeHistory.shareTradeModalTitle", "Share Real Trade")}</DialogTitle>
					<DialogDescription>
						{t(
							"tradeHistory.shareTradeModalDesc",
							"Generate a stylish PnL card with full privacy control. Earn referrals and give +1,000 bonus tokens to guests!",
						)}
					</DialogDescription>
				</DialogHeader>

				<div className="space-y-3.5 py-1">
					{/* ============================================================== */}
					{/* EXACT 1200x630 TEMPLATE FROM trade_pnl_card_preview.html       */}
					{/* ============================================================== */}
					<div className="relative w-full aspect-[1200/630] rounded-2xl md:rounded-3xl overflow-hidden shadow-2xl border border-white/15 select-none bg-[#090d16]">
						{/* Background Ambient & Gradients */}
						<div className="absolute inset-0 bg-gradient-to-br from-[#0c111c] via-[#090d16] to-[#04060b]" />
						<div
							className={`absolute -top-16 -left-16 w-60 h-60 rounded-full blur-[70px] pointer-events-none transition-all duration-500 ${
								isProfit ? "bg-emerald-500/15" : "bg-red-500/15"
							}`}
						/>
						<div className="absolute -bottom-16 -right-16 w-60 h-60 rounded-full bg-cyan-500/10 blur-[70px] pointer-events-none" />

						{/* Main Strict Flex Container - Guaranteed to Fit */}
						<div className="relative h-full w-full p-[3.2%] flex flex-col justify-between z-10 box-border">

							{/* 1. HEADER ROW */}
							<div className="flex items-center justify-between gap-4 h-[18%]">
								{/* Official DepthSight Logo */}
								<div className="flex items-center">
									<svg viewBox="0 0 340 100" xmlns="http://www.w3.org/2000/svg" className="h-7 sm:h-9 md:h-11 w-auto" shapeRendering="geometricPrecision">
										<defs>
											<linearGradient id="prevLogoTechGrad" x1="0%" y1="0%" x2="100%" y2="100%">
												<stop offset="0%" stopColor="#00D4FF" />
												<stop offset="100%" stopColor="#0066FF" />
											</linearGradient>
											<filter id="prevLogoGlow">
												<feGaussianBlur stdDeviation="2.5" result="coloredBlur" />
												<feMerge>
													<feMergeNode in="coloredBlur" />
													<feMergeNode in="SourceGraphic" />
												</feMerge>
											</filter>
										</defs>
										<g transform="translate(5, 25)">
											<circle cx="25" cy="25" r="24" fill="none" stroke="url(#prevLogoTechGrad)" strokeWidth="2" opacity="0.8" />
											<circle cx="25" cy="25" r="18" fill="none" stroke="#00D4FF" strokeWidth="1" opacity="0.5" />
											<circle cx="25" cy="25" r="12" fill="none" stroke="#00D4FF" strokeWidth="1" opacity="0.4" />
											<path d="M 25 25 L 40 15 M 25 25 L 40 35 M 25 25 L 10 15 M 25 25 L 10 35" stroke="#0066FF" strokeWidth="1" opacity="0.4" />
											<circle cx="25" cy="25" r="8" fill="url(#prevLogoTechGrad)" filter="url(#prevLogoGlow)" />
											<circle cx="25" cy="25" r="4" fill="#FFFFFF" opacity="0.9" />
											<path d="M 25 5 L 25 10 M 25 40 L 25 45 M 5 25 L 10 25 M 40 25 L 45 25" stroke="url(#prevLogoTechGrad)" strokeWidth="2" strokeLinecap="round" />
										</g>
										<text x="90" y="54" dominantBaseline="middle" fontFamily="Montserrat, Helvetica, Arial, sans-serif" fontSize="38">
											<tspan fontWeight="700" fill="#FFFFFF">Depth</tspan>
											<tspan fill="url(#prevLogoTechGrad)" fontWeight="300">Sight</tspan>
										</text>
									</svg>
								</div>

								{/* Badges: Verified Live Trade + Exchange with logo */}
								<div className="flex items-center gap-2 font-mono text-[9px] sm:text-[11px]">
									<span className="flex items-center gap-1.5 px-2.5 py-0.5 sm:py-1 rounded-full bg-emerald-500/10 text-emerald-400 border border-emerald-500/30 font-semibold tracking-wider uppercase">
										<span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
										Live Trade
									</span>
									<span className="flex items-center gap-1.5 px-2.5 py-0.5 sm:py-1 rounded-full bg-white/[0.04] text-gray-300 border border-white/10 font-semibold tracking-wider uppercase">
										<ExchangeIcon exchange={trade.exchange} className="w-4 h-4 object-contain inline-block shrink-0" />
										{exchangeDisplay}
									</span>
								</div>
							</div>

							{/* 2. HERO MIDDLE SECTION */}
							<div className="grid grid-cols-12 gap-3 items-center my-auto h-[48%]">
								{/* Left 8 cols: Pair + Side Badge + Strategy Badge + Big Numbers */}
								<div className="col-span-8 flex flex-col justify-center space-y-1">
									<div className="flex items-center flex-wrap gap-2">
										<span className="font-display text-xl sm:text-3xl md:text-4xl font-black tracking-tight text-white leading-none">
											{symbolRaw.includes("USDT") ? `${symbolRaw.replace("USDT", "")} / USDT` : symbolRaw}
										</span>
										<span className={`px-2 py-0.5 rounded-md text-[10px] font-black tracking-widest uppercase ${
											isLong
												? "bg-emerald-500/20 text-emerald-400 border border-emerald-500/40"
												: "bg-purple-500/20 text-purple-400 border border-purple-500/40"
										}`}>
											{trade.direction}
										</span>
										{isStrategyNamePublic && (trade.strategy || trade.strategy_config_id) && (
											<span className="px-2 py-0.5 rounded-md text-[10px] font-mono text-cyan-400 bg-cyan-500/10 border border-cyan-500/20 truncate max-w-[200px]">
												⚡ {trade.strategy || trade.strategy_config_id}
											</span>
										)}
									</div>

									<div className="pt-1">
										<div className="text-[10px] uppercase font-mono tracking-wider text-gray-400 font-semibold">
											{pnlDisplayMode === "USD"
												? "Net Realized Profit"
												: pnlDisplayMode === "BOTH"
													? "Net Profit & ROI"
													: "Return on Investment (ROI)"}
										</div>

										<div className="flex items-baseline gap-2.5 flex-wrap">
											<span className={`font-mono text-2xl sm:text-4xl md:text-[46px] font-black tracking-tight leading-none ${
												isProfit ? "text-emerald-400" : "text-red-400"
											}`}>
												{pnlDisplayMode === "USD"
													? `${pnlUsd >= 0 ? "+" : ""}$${pnlUsd.toFixed(2)}`
													: `${roiPct >= 0 ? "+" : ""}${roiPct.toFixed(2)}%`}
											</span>
											{pnlDisplayMode === "BOTH" && (
												<span className="font-mono text-sm sm:text-xl font-bold text-gray-400 leading-none">
													({pnlUsd >= 0 ? "+" : ""}${pnlUsd.toFixed(2)} USD)
												</span>
											)}
										</div>
									</div>
								</div>

								{/* Right 4 cols: Trajectory Sparkline Curve */}
								<div className="col-span-4 flex items-center justify-end">
									<div className="w-full max-w-[190px] aspect-[16/10] rounded-xl bg-white/[0.02] border border-white/5 p-2 flex flex-col justify-between relative overflow-hidden">
										<div className="text-[8px] font-mono text-gray-400 flex justify-between">
											<span>EXECUTION</span>
											<span className={`font-bold uppercase ${isProfit ? "text-emerald-400" : "text-red-400"}`}>
												{trade.exit_reason || (isProfit ? "TAKE PROFIT" : "STOP LOSS")}
											</span>
										</div>

										<svg className="w-full h-11 sm:h-14 overflow-visible" viewBox="0 0 200 80">
											<defs>
												<linearGradient id="previewTrajGrad" x1="0" y1="0" x2="0" y2="1">
													<stop offset="0%" stopColor={isProfit ? "#10b981" : "#ef4444"} stopOpacity="0.35" />
													<stop offset="100%" stopColor={isProfit ? "#10b981" : "#ef4444"} stopOpacity="0" />
												</linearGradient>
											</defs>
											<path d={previewAreaD} fill="url(#previewTrajGrad)" />
											<path d={previewLineD} fill="none" stroke={isProfit ? "#10b981" : "#ef4444"} strokeWidth="2.5" strokeLinecap="round" />
											<circle cx={lastPtX} cy={lastPtY} r="3.5" fill={isProfit ? "#34d399" : "#f87171"} className="animate-ping" />
											<circle cx={lastPtX} cy={lastPtY} r="3.5" fill={isProfit ? "#10b981" : "#ef4444"} />
										</svg>

										<div className="flex items-center justify-between text-[8px] font-mono text-gray-400 pt-0.5 border-t border-white/5">
											<span>In: ${formatCryptoPrice(trade.entry_price)}</span>
											<span>Out: ${formatCryptoPrice(trade.exit_price)}</span>
										</div>
									</div>
								</div>
							</div>

							{/* 3. BOTTOM ROW: METRICS + REFERRAL QR BLOCK */}
							<div className="grid grid-cols-12 gap-2 pt-2 border-t border-white/10 items-center h-[26%]">
								{/* Key Trade Metrics (3 columns) */}
								<div className="col-span-8 grid grid-cols-3 gap-1.5 sm:gap-2">
									<div className="bg-white/[0.03] rounded-lg p-1.5 sm:p-2 border border-white/5 flex flex-col justify-center">
										<div className="text-[8px] sm:text-[9px] font-mono text-gray-400 uppercase">Вход / Выход</div>
										<div className="text-[10px] sm:text-xs font-mono font-bold text-white mt-0.5 truncate">
											${formatCryptoPrice(trade.entry_price)} → ${formatCryptoPrice(trade.exit_price)}
										</div>
									</div>

									<div className="bg-white/[0.03] rounded-lg p-1.5 sm:p-2 border border-white/5 flex flex-col justify-center">
										<div className="text-[8px] sm:text-[9px] font-mono text-gray-400 uppercase">Длительность</div>
										<div className="text-[10px] sm:text-xs font-mono font-bold text-white mt-0.5">
											{durationFormatted}
										</div>
									</div>

									<div className="bg-white/[0.03] rounded-lg p-1.5 sm:p-2 border border-white/5 flex flex-col justify-center transition-all">
										<div className="text-[8px] sm:text-[9px] font-mono text-gray-400 uppercase">
											{isQuantityPublic ? "Объем позиции" : "Закрыта по"}
										</div>
										<div className={`text-[10px] sm:text-xs font-mono font-bold mt-0.5 truncate ${
											isQuantityPublic ? "text-cyan-400" : isProfit ? "text-emerald-400" : "text-red-400"
										}`}>
											{isQuantityPublic ? `${trade.quantity || "—"} ${baseAsset}` : trade.exit_reason || "Take Profit"}
										</div>
									</div>
								</div>

								{/* High-Conversion Referral & QR Code Block */}
								<div className="col-span-4 bg-gradient-to-r from-cyan-500/10 to-blue-500/10 rounded-lg p-1.5 sm:p-2 border border-cyan-500/30 flex items-center justify-between gap-1.5">
									<div className="flex flex-col justify-center min-w-0">
										<div className="text-[7px] sm:text-[8px] font-mono text-cyan-300 font-bold uppercase tracking-wider truncate flex items-center gap-1">
											<span className="w-1.5 h-1.5 rounded-full bg-cyan-400" />
											Торгуй на DepthSight
										</div>
										<div className="text-[9px] sm:text-[10px] font-mono font-extrabold text-white truncate mt-0.5">
											Реф: <span className="text-cyan-400">{refCode}</span>
										</div>
										<div className="text-[7px] sm:text-[8px] font-mono text-gray-400 truncate mt-0.5">
											+1,000 бонусных токенов
										</div>
									</div>

									{/* QR Code */}
									<div className="shrink-0 w-8 h-8 sm:w-9 sm:h-9 bg-white rounded p-0.5 shadow-md flex items-center justify-center">
										<svg viewBox="0 0 29 29" className="w-full h-full text-black" fill="currentColor">
											<rect x="2" y="2" width="7" height="7" fill="black" />
											<rect x="3" y="3" width="5" height="5" fill="white" />
											<rect x="4" y="4" width="3" height="3" fill="black" />
											<rect x="20" y="2" width="7" height="7" fill="black" />
											<rect x="21" y="3" width="5" height="5" fill="white" />
											<rect x="22" y="4" width="3" height="3" fill="black" />
											<rect x="2" y="20" width="7" height="7" fill="black" />
											<rect x="3" y="21" width="5" height="5" fill="white" />
											<rect x="4" y="22" width="3" height="3" fill="black" />
											<rect x="11" y="4" width="2" height="2" />
											<rect x="15" y="4" width="2" height="2" />
											<rect x="11" y="8" width="4" height="2" />
											<rect x="12" y="12" width="5" height="5" />
											<rect x="4" y="12" width="3" height="3" />
											<rect x="20" y="11" width="2" height="4" />
											<rect x="23" y="13" width="3" height="3" />
											<rect x="11" y="20" width="3" height="4" />
											<rect x="16" y="22" width="4" height="3" />
											<rect x="22" y="22" width="4" height="4" />
										</svg>
									</div>
								</div>
							</div>

							{/* 4. FOOTER URL & DATE */}
							<div className="flex items-center justify-between text-[8px] sm:text-[9px] font-mono text-gray-500 pt-1">
								<span className="text-cyan-400/90 font-medium tracking-wide">
									app.depthsight.pro/t/{publicSlug ? publicSlug.slice(0, 12) : "trade-id"}
								</span>
								<span>Закрыта: {closeTimeFormatted}</span>
							</div>
						</div>
					</div>

					{/* Controls: Mode Selector & Toggles */}
					<div className="bg-white/[0.02] border border-white/5 rounded-xl p-3 space-y-2.5">
						<div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2">
							<Label className="text-xs font-semibold text-gray-300">
								{t("tradeHistory.pnlModeLabel", "PnL Display Mode")}
							</Label>
							<div className="flex items-center bg-black/60 p-0.5 rounded-lg border border-white/10 text-xs">
								<button
									type="button"
									onClick={() => handleModeChange("PERCENT")}
									className={`px-3 py-1 rounded-md transition-all font-medium ${
										pnlDisplayMode === "PERCENT"
											? "bg-cyan-500 text-black font-bold shadow-xs"
											: "text-gray-400 hover:text-white"
									}`}
								>
									{t("tradeHistory.modePercent", "% Only (Private)")}
								</button>
								<button
									type="button"
									onClick={() => handleModeChange("USD")}
									className={`px-3 py-1 rounded-md transition-all font-medium ${
										pnlDisplayMode === "USD"
											? "bg-cyan-500 text-black font-bold shadow-xs"
											: "text-gray-400 hover:text-white"
									}`}
								>
									{t("tradeHistory.modeUsd", "$ (USD)")}
								</button>
								<button
									type="button"
									onClick={() => handleModeChange("BOTH")}
									className={`px-3 py-1 rounded-md transition-all font-medium ${
										pnlDisplayMode === "BOTH"
											? "bg-cyan-500 text-black font-bold shadow-xs"
											: "text-gray-400 hover:text-white"
									}`}
								>
									{t("tradeHistory.modeBoth", "Both (% & $)")}
								</button>
							</div>
						</div>

						<div className="grid grid-cols-1 sm:grid-cols-2 gap-3 pt-2 border-t border-white/5 text-xs">
							<div className="flex items-center justify-between gap-2">
								<div className="space-y-0.5">
									<Label className="text-xs text-gray-300">
										{t("tradeHistory.showStrategyName", "Show Strategy Name")}
									</Label>
									<p className="text-[10px] text-gray-500">
										{t("tradeHistory.showStrategyDesc", "Include algorithm or preset tag")}
									</p>
								</div>
								<Switch
									checked={isStrategyNamePublic}
									onCheckedChange={handleStrategyToggle}
								/>
							</div>

							<div className="flex items-center justify-between gap-2">
								<div className="space-y-0.5">
									<Label className="text-xs text-gray-300">
										{t("tradeHistory.showQuantity", "Show Position Size")}
									</Label>
									<p className="text-[10px] text-gray-500">
										{t("tradeHistory.showQuantityDesc", "Keep hidden to protect portfolio size")}
									</p>
								</div>
								<Switch
									checked={isQuantityPublic}
									onCheckedChange={handleQuantityToggle}
								/>
							</div>
						</div>
					</div>

					{/* Generated Link Input (if available) */}
					{generatedUrl && (
						<div className="space-y-1 animate-fade-up">
							<div className="flex items-center justify-between text-[11px] font-mono">
								<span className="text-emerald-400 font-semibold flex items-center gap-1">
									<Check className="w-3 h-3" />
									{t("tradeHistory.shareReadyLabel", "Public Link Generated")}
								</span>
								<span className="text-gray-400">
									{t("tradeHistory.refAttached", "Referral code: ")}
									<b className="text-cyan-400">{refCode}</b>
								</span>
							</div>
							<div className="flex items-center gap-2">
								<input
									type="text"
									readOnly
									value={generatedUrl}
									className="flex-1 bg-black/60 border border-white/10 rounded-lg px-3 py-1.5 text-xs font-mono text-gray-200 outline-none"
								/>
							</div>
						</div>
					)}

					{/* Prominent Action / Share Buttons */}
					<div className="grid grid-cols-2 sm:grid-cols-4 gap-2 pt-1">
						{/* 1. Telegram */}
						<Button
							type="button"
							onClick={handleTelegramShare}
							disabled={isPending}
							className="bg-[#229ED9] hover:bg-[#1e8cc0] text-white font-bold text-xs h-9 shadow-md flex items-center justify-center gap-1.5"
						>
							<svg className="w-3.5 h-3.5 fill-current" viewBox="0 0 24 24">
								<path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm4.64 6.8c-.15 1.58-.8 5.42-1.13 7.19-.14.75-.42 1-.68 1.03-.58.05-1.02-.38-1.58-.75-.88-.58-1.38-.94-2.23-1.5-.99-.65-.35-1.01.22-1.59.15-.15 2.71-2.48 2.76-2.69a.2.2 0 00-.05-.18c-.06-.05-.14-.03-.21-.02-.09.02-1.49.95-4.22 2.79-.4.27-.76.41-1.08.4-.36-.01-1.04-.2-1.55-.37-.63-.2-1.12-.31-1.08-.66.02-.18.27-.36.74-.55 2.92-1.27 4.86-2.11 5.83-2.51 2.78-1.16 3.35-1.36 3.73-1.36.08 0 .27.02.39.12.1.08.13.19.14.27-.01.06.01.24 0 .38z"/>
							</svg>
							Telegram
						</Button>

						{/* 2. Twitter / X */}
						<Button
							type="button"
							onClick={handleTwitterShare}
							disabled={isPending}
							className="bg-black hover:bg-neutral-900 border border-white/20 text-white font-bold text-xs h-9 shadow-md flex items-center justify-center gap-1.5"
						>
							<svg className="w-3.5 h-3.5 fill-current" viewBox="0 0 24 24">
								<path d="M18.244 2.25h3.308l-7.227 8.26 8.502 11.24H16.17l-5.214-6.817L4.99 21.75H1.68l7.73-8.835L1.254 2.25H8.08l4.713 6.231zm-1.161 17.52h1.833L7.084 4.126H5.117z"/>
							</svg>
							Twitter / X
						</Button>

						{/* 3. Copy Link */}
						<Button
							type="button"
							variant="outline"
							onClick={handleCopy}
							disabled={isPending}
							className="border-cyan-500/40 text-cyan-400 hover:bg-cyan-500/10 font-bold text-xs h-9 flex items-center justify-center gap-1.5"
						>
							{hasCopied ? (
								<>
									<Check className="w-3.5 h-3.5 text-emerald-400" />
									{t("common:copied", "Copied!")}
								</>
							) : (
								<>
									<Copy className="w-3.5 h-3.5" />
									{t("common:copyLink", "Copy Link")}
								</>
							)}
						</Button>

						{/* 4. Download PNG Card */}
						<Button
							type="button"
							variant="outline"
							onClick={handleDownloadOgImage}
							disabled={isPending || isDownloading}
							className="border-white/10 text-gray-200 hover:bg-white/10 font-medium text-xs h-9 flex items-center justify-center gap-1.5"
						>
							{isDownloading ? (
								<>
									<Loader2 className="w-3.5 h-3.5 animate-spin text-cyan-400" />
									{t("common:saving", "Saving...")}
								</>
							) : (
								<>
									<Download className="w-3.5 h-3.5" />
									PNG Card
								</>
							)}
						</Button>
					</div>
				</div>
			</DialogContent>
		</Dialog>
	);
};
