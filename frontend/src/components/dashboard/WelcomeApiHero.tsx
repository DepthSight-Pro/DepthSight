// src/components/dashboard/WelcomeApiHero.tsx

import React, { useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useNavigate } from "react-router-dom";
import {
	ArrowRight,
	Coins,
	Gift,
	Key,
	Lock,
	PencilRuler,
	Pickaxe,
	Rocket,
	Share2,
	ShieldCheck,
	TrendingUp,
	Users,
	Wallet,
	Zap,
} from "lucide-react";
import { ExchangeBadge } from "@/components/layout/AccountSelector";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

interface WelcomeApiHeroProps {
	onConnect: () => void;
	className?: string;
}

const SUPPORTED_EXCHANGES = [
	{ id: "binance", name: "Binance" },
	{ id: "bybit", name: "Bybit" },
	{ id: "okx", name: "OKX" },
	{ id: "bitget", name: "Bitget" },
	{ id: "weex", name: "WEEX" },
] as const;

export const WelcomeApiHero: React.FC<WelcomeApiHeroProps> = ({
	onConnect,
	className,
}) => {
	const { t } = useTranslation(["index", "common"]);
	const navigate = useNavigate();
	const [role, setRole] = useState<"trader" | "partner">("trader");

	return (
		<div
			className={cn(
				"relative overflow-hidden rounded-2xl border bg-gradient-to-br from-obsidian/95 via-obsidian/85 to-[#051120]/95 p-5 sm:p-7 backdrop-blur-2xl transition-all duration-300",
				role === "trader"
					? "border-cyan/30 shadow-[0_0_35px_-8px_rgba(0,212,255,0.25)]"
					: "border-amber-500/30 shadow-[0_0_35px_-8px_rgba(245,158,11,0.25)]",
				className,
			)}
		>
			{/* Ambient cyber glow orbs */}
			<div
				className={cn(
					"pointer-events-none absolute -top-24 -right-24 h-72 w-72 rounded-full blur-3xl transition-colors duration-500",
					role === "trader" ? "bg-cyan/15" : "bg-amber-500/15",
				)}
			/>
			<div className="pointer-events-none absolute -bottom-24 -left-24 h-72 w-72 rounded-full bg-azure/20 blur-3xl" />
			<div className="pointer-events-none absolute top-1/2 left-1/3 h-40 w-40 -translate-y-1/2 rounded-full bg-rose-500/10 blur-3xl" />

			{/* Subtle top edge neon line */}
			<div
				className={cn(
					"pointer-events-none absolute inset-x-0 top-0 h-px transition-colors duration-500",
					role === "trader"
						? "bg-gradient-to-r from-transparent via-cyan/60 to-transparent shadow-[0_0_12px_rgba(0,212,255,0.8)]"
						: "bg-gradient-to-r from-transparent via-amber-500/60 to-transparent shadow-[0_0_12px_rgba(245,158,11,0.8)]",
				)}
			/>

			<div className="relative z-10 flex flex-col gap-6">
				{/* Top Badges, Role Switcher & Meta */}
				<div className="flex flex-wrap items-center justify-between gap-3">
					<div className="flex flex-wrap items-center gap-2">
						{role === "trader" ? (
							<span className="inline-flex items-center gap-1.5 rounded-full border border-cyan/40 bg-cyan/10 px-3 py-1 font-mono text-[11px] font-semibold tracking-wide text-cyan uppercase shadow-sm">
								<span className="h-1.5 w-1.5 rounded-full bg-cyan animate-ping" />
								<span className="h-1.5 w-1.5 -ml-3 rounded-full bg-cyan shadow-[0_0_8px_#00d4ff]" />
								{t("index:welcomeHero.badge", "Quick Start")}
							</span>
						) : (
							<span className="inline-flex items-center gap-1.5 rounded-full border border-amber-500/40 bg-amber-500/10 px-3 py-1 font-mono text-[11px] font-semibold tracking-wide text-amber-300 uppercase shadow-sm">
								<span className="h-1.5 w-1.5 rounded-full bg-amber-400 animate-ping" />
								<span className="h-1.5 w-1.5 -ml-3 rounded-full bg-amber-400 shadow-[0_0_8px_#f59e0b]" />
								{t("index:welcomeHero.badgePartner", "Partner Program")}
							</span>
						)}

						<Link
							to="/mining"
							className="group inline-flex items-center gap-1.5 rounded-full border border-amber-500/30 bg-amber-500/10 hover:bg-amber-500/20 px-3 py-1 text-[11px] font-medium text-amber-400 transition-colors shadow-sm"
						>
							<span className="animate-pulse">🔥</span>
							<span>{t("index:welcomeHero.badgeAirdrop", "Airdrop Active")}</span>
							<ArrowRight className="h-3 w-3 opacity-60 transition-transform group-hover:translate-x-0.5" />
						</Link>
					</div>

					{/* Role Selector Tabs (Trader vs Partner) */}
					<div className="inline-flex items-center rounded-xl border border-white/10 bg-white/[0.04] p-1 backdrop-blur-md">
						<button
							type="button"
							onClick={() => setRole("trader")}
							className={cn(
								"flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs transition-all duration-200 cursor-pointer",
								role === "trader"
									? "bg-cyan/20 text-cyan border border-cyan/40 shadow-[0_0_15px_-3px_rgba(0,212,255,0.4)] font-semibold"
									: "text-white/60 hover:text-white hover:bg-white/[0.04] border border-transparent font-medium",
							)}
						>
							<TrendingUp className="h-3.5 w-3.5" />
							<span>{t("index:welcomeHero.roleTrader", "Trader")}</span>
						</button>
						<button
							type="button"
							onClick={() => setRole("partner")}
							className={cn(
								"flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs transition-all duration-200 cursor-pointer",
								role === "partner"
									? "bg-gradient-to-r from-amber-500/25 to-amber-600/20 text-amber-300 border border-amber-500/40 shadow-[0_0_15px_-3px_rgba(245,158,11,0.4)] font-semibold"
									: "text-white/60 hover:text-white hover:bg-white/[0.04] border border-transparent font-medium",
							)}
						>
							<Users className="h-3.5 w-3.5" />
							<span>{t("index:welcomeHero.rolePartner", "Partner")}</span>
							<span className="rounded-full bg-amber-500/20 border border-amber-500/40 px-1.5 py-0.2 font-mono text-[10px] font-bold text-amber-300">
								10%
							</span>
						</button>
					</div>

					<div className="hidden sm:flex items-center gap-1.5 text-[11px] text-white/50 font-mono">
						{role === "trader" ? (
							<>
								<Lock className="h-3.5 w-3.5 text-emerald-400" />
								<span>Non-custodial · No withdrawals required</span>
							</>
						) : (
							<>
								<ShieldCheck className="h-3.5 w-3.5 text-amber-400" />
								<span>{t("index:welcomeHero.partnerRiskFree", "Zero risk · No trading deposit required")}</span>
							</>
						)}
					</div>
				</div>

				{/* Headline & Description */}
				<div className="max-w-3xl space-y-2">
					<h2 className="text-xl sm:text-2xl lg:text-3xl font-bold tracking-tight text-white flex items-center gap-2.5">
						<span>
							{role === "trader"
								? t("index:welcomeHero.title", "Connect an Exchange & Start Trading")
								: t("index:welcomeHero.partnerTitle", "Earn 10% from Your Audience's Trade Mining")}
						</span>
					</h2>
					<p className="text-xs sm:text-sm text-white/70 leading-relaxed font-sans">
						{role === "trader"
							? t(
									"index:welcomeHero.description",
									"DepthSight connects to your exchange via secure API keys (read & trade only, no withdrawal permissions). Your funds remain safely in your own exchange account.",
								)
							: t(
									"index:welcomeHero.partnerDescription",
									"You don't need to connect an exchange or trade yourself. Simply connect your Web3 wallet (MetaMask), activate mining, and copy your referral link for your audience.",
								)}
					</p>
				</div>

				{/* Cards: Trader 4 steps vs Partner 3 steps */}
				{role === "trader" ? (
					<div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3 pt-1">
						{/* Step 1 */}
						<div className="group relative rounded-xl border border-white/10 bg-white/[0.03] hover:bg-white/[0.05] p-3.5 transition-all duration-200">
							<div className="flex items-center justify-between mb-2">
								<div className="flex h-8 w-8 items-center justify-center rounded-lg bg-cyan/15 text-cyan border border-cyan/30">
									<Key className="h-4 w-4" />
								</div>
								<span className="font-mono text-xs font-bold text-white/30 group-hover:text-cyan/70 transition-colors">
									01
								</span>
							</div>
							<div className="font-semibold text-xs text-white mb-1">
								{t("index:welcomeHero.step1Title", "Generate API Key")}
							</div>
							<div className="text-[11px] text-white/50 leading-relaxed">
								{t(
									"index:welcomeHero.step1Desc",
									"On Binance, Bybit, OKX, Bitget, or WEEX with read and trade permissions.",
								)}
							</div>
						</div>

						{/* Step 2 */}
						<div
							onClick={onConnect}
							className="group relative rounded-xl border border-white/10 bg-white/[0.03] hover:bg-white/[0.05] hover:border-azure/40 p-3.5 transition-all duration-200 cursor-pointer"
						>
							<div className="flex items-center justify-between mb-2">
								<div className="flex h-8 w-8 items-center justify-center rounded-lg bg-azure/20 text-azure border border-azure/40">
									<ShieldCheck className="h-4 w-4 text-cyan" />
								</div>
								<span className="font-mono text-xs font-bold text-white/30 group-hover:text-azure/70 transition-colors">
									02
								</span>
							</div>
							<div className="font-semibold text-xs text-white mb-1 group-hover:text-cyan transition-colors">
								{t("index:welcomeHero.step2Title", "Connect to DepthSight")}
							</div>
							<div className="text-[11px] text-white/50 leading-relaxed">
								{t(
									"index:welcomeHero.step2Desc",
									"Keys are Fernet-encrypted at rest and stored in secure multi-tenant isolation.",
								)}
							</div>
						</div>

						{/* Step 3 */}
						<div
							onClick={() => navigate("/mining")}
							className="group relative rounded-xl border border-white/10 bg-white/[0.03] hover:bg-white/[0.05] hover:border-amber-500/40 p-3.5 transition-all duration-200 cursor-pointer"
						>
							<div className="flex items-center justify-between mb-2">
								<div className="flex h-8 w-8 items-center justify-center rounded-lg bg-amber-500/15 text-amber-400 border border-amber-500/30">
									<Wallet className="h-4 w-4" />
								</div>
								<span className="font-mono text-xs font-bold text-white/30 group-hover:text-amber-400/70 transition-colors">
									03
								</span>
							</div>
							<div className="font-semibold text-xs text-white mb-1 group-hover:text-amber-300 transition-colors">
								{t("index:welcomeHero.step3Title", "Connect Wallet & Activate Mining")}
							</div>
							<div className="text-[11px] text-white/50 leading-relaxed">
								{t(
									"index:welcomeHero.step3Desc",
									"Connect your Web3 wallet (MetaMask) on the Mining tab to activate trade rebate rewards.",
								)}
							</div>
						</div>

						{/* Step 4 */}
						<div
							onClick={() => navigate("/editor")}
							className="group relative rounded-xl border border-white/10 bg-white/[0.03] hover:bg-white/[0.05] hover:border-emerald-500/40 p-3.5 transition-all duration-200 cursor-pointer"
						>
							<div className="flex items-center justify-between mb-2">
								<div className="flex h-8 w-8 items-center justify-center rounded-lg bg-emerald-500/15 text-emerald-400 border border-emerald-500/30">
									<Rocket className="h-4 w-4" />
								</div>
								<span className="font-mono text-xs font-bold text-white/30 group-hover:text-emerald-400/70 transition-colors">
									04
								</span>
							</div>
							<div className="font-semibold text-xs text-white mb-1 group-hover:text-emerald-300 transition-colors">
								{t("index:welcomeHero.step4Title", "Create & Deploy Strategy")}
							</div>
							<div className="text-[11px] text-white/50 leading-relaxed">
								{t(
									"index:welcomeHero.step4Desc",
									"Build your own trading algorithms in the visual editor and earn volume rewards with Trade Mining.",
								)}
							</div>
						</div>
					</div>
				) : (
					<div className="grid grid-cols-1 md:grid-cols-3 gap-3 pt-1">
						{/* Partner Step 1 */}
						<div
							onClick={() => navigate("/mining")}
							className="group relative rounded-xl border border-amber-500/20 bg-amber-500/[0.03] hover:bg-amber-500/[0.06] hover:border-amber-500/40 p-4 transition-all duration-200 cursor-pointer shadow-sm"
						>
							<div className="flex items-center justify-between mb-2.5">
								<div className="flex h-9 w-9 items-center justify-center rounded-lg bg-amber-500/15 text-amber-400 border border-amber-500/30">
									<Wallet className="h-4 w-4" />
								</div>
								<span className="font-mono text-xs font-bold text-amber-500/40 group-hover:text-amber-400 transition-colors">
									01
								</span>
							</div>
							<div className="font-semibold text-xs sm:text-sm text-white mb-1.5 group-hover:text-amber-300 transition-colors">
								{t("index:welcomeHero.partnerStep1Title", "Connect MetaMask Wallet")}
							</div>
							<div className="text-[11px] sm:text-xs text-white/60 leading-relaxed">
								{t(
									"index:welcomeHero.partnerStep1Desc",
									"Authenticate with your Web3 wallet on the Trade Mining tab to register your node.",
								)}
							</div>
						</div>

						{/* Partner Step 2 */}
						<div
							onClick={() => navigate("/mining")}
							className="group relative rounded-xl border border-cyan/20 bg-cyan/[0.03] hover:bg-cyan/[0.06] hover:border-cyan/40 p-4 transition-all duration-200 cursor-pointer shadow-sm"
						>
							<div className="flex items-center justify-between mb-2.5">
								<div className="flex h-9 w-9 items-center justify-center rounded-lg bg-cyan/15 text-cyan border border-cyan/30">
									<Zap className="h-4 w-4" />
								</div>
								<span className="font-mono text-xs font-bold text-cyan/40 group-hover:text-cyan transition-colors">
									02
								</span>
							</div>
							<div className="font-semibold text-xs sm:text-sm text-white mb-1.5 group-hover:text-cyan transition-colors">
								{t("index:welcomeHero.partnerStep2Title", "Activate Mining & Copy Link")}
							</div>
							<div className="text-[11px] sm:text-xs text-white/60 leading-relaxed">
								{t(
									"index:welcomeHero.partnerStep2Desc",
									"Turn on your node in one click and copy your unique personal referral link.",
								)}
							</div>
						</div>

						{/* Partner Step 3 */}
						<div
							onClick={() => navigate("/mining")}
							className="group relative rounded-xl border border-emerald-500/20 bg-emerald-500/[0.03] hover:bg-emerald-500/[0.06] hover:border-emerald-500/40 p-4 transition-all duration-200 cursor-pointer shadow-sm"
						>
							<div className="flex items-center justify-between mb-2.5">
								<div className="flex h-9 w-9 items-center justify-center rounded-lg bg-emerald-500/15 text-emerald-400 border border-emerald-500/30">
									<Share2 className="h-4 w-4" />
								</div>
								<span className="font-mono text-xs font-bold text-emerald-500/40 group-hover:text-emerald-400 transition-colors">
									03
								</span>
							</div>
							<div className="font-semibold text-xs sm:text-sm text-white mb-1.5 group-hover:text-emerald-300 transition-colors">
								{t("index:welcomeHero.partnerStep3Title", "Share & Earn 10%")}
							</div>
							<div className="text-[11px] sm:text-xs text-white/60 leading-relaxed">
								{t(
									"index:welcomeHero.partnerStep3Desc",
									"Receive 10% of all trade mining rewards earned by your referred users directly to your node balance.",
								)}
							</div>
						</div>
					</div>
				)}

				{/* Bottom Action Bar */}
				{role === "trader" ? (
					<div className="flex flex-col lg:flex-row items-start lg:items-center justify-between gap-4 pt-2 border-t border-white/10">
						{/* Action buttons */}
						<div className="flex flex-wrap items-center gap-2.5">
							<Button
								type="button"
								onClick={onConnect}
								className="rounded-xl bg-gradient-to-r from-azure to-cyan px-4 sm:px-5 py-2.5 text-xs sm:text-sm font-semibold text-white shadow-[0_0_25px_-4px_rgba(0,212,255,0.7)] hover:shadow-[0_0_30px_-2px_rgba(0,212,255,0.9)] hover:brightness-110 transition-all flex items-center gap-2 cursor-pointer"
							>
								<Key className="h-4 w-4" />
								<span>{t("index:welcomeHero.connectButton", "Connect API Key")}</span>
							</Button>

							<Button
								type="button"
								variant="outline"
								onClick={() => navigate("/editor")}
								className="rounded-xl border-white/15 bg-white/[0.04] px-3.5 py-2 text-xs font-medium text-white/80 hover:bg-white/[0.08] hover:text-white transition-colors flex items-center gap-1.5 cursor-pointer"
							>
								<PencilRuler className="h-3.5 w-3.5 text-cyan" />
								<span>{t("index:welcomeHero.editorButton", "Strategy Editor")}</span>
							</Button>

							<Button
								type="button"
								variant="outline"
								onClick={() => navigate("/mining")}
								className="rounded-xl border-amber-500/30 bg-amber-500/10 px-3.5 py-2 text-xs font-medium text-amber-300 hover:bg-amber-500/20 hover:text-amber-200 transition-colors flex items-center gap-1.5 cursor-pointer"
							>
								<Pickaxe className="h-3.5 w-3.5 text-amber-400" />
								<span>{t("index:welcomeHero.miningButton", "Trade Mining & Airdrop")}</span>
							</Button>
						</div>

						{/* Supported exchange badges */}
						<div className="flex items-center gap-2 text-xs text-white/40">
							<span className="hidden xl:inline text-[11px] font-mono">
								{t("index:welcomeHero.supportedExchanges", "Supported exchanges:")}
							</span>
							<div className="flex items-center gap-1.5">
								{SUPPORTED_EXCHANGES.map((ex) => (
									<div
										key={ex.id}
										className="flex items-center gap-1.5 rounded-lg border border-white/10 bg-white/[0.03] px-2 py-1 text-[11px] font-medium text-white/80"
									>
										<ExchangeBadge exchange={ex.id} size="xs" />
										<span className="font-mono">{ex.name}</span>
									</div>
								))}
							</div>
						</div>
					</div>
				) : (
					<div className="flex flex-col lg:flex-row items-start lg:items-center justify-between gap-4 pt-2 border-t border-white/10">
						{/* Partner Action buttons */}
						<div className="flex flex-wrap items-center gap-2.5">
							<Button
								type="button"
								onClick={() => navigate("/mining")}
								className="rounded-xl bg-gradient-to-r from-amber-500 via-amber-600 to-amber-500 px-4 sm:px-5 py-2.5 text-xs sm:text-sm font-semibold text-white shadow-[0_0_25px_-4px_rgba(245,158,11,0.7)] hover:shadow-[0_0_30px_-2px_rgba(245,158,11,0.9)] hover:brightness-110 transition-all flex items-center gap-2 cursor-pointer"
							>
								<Wallet className="h-4 w-4" />
								<span>
									{t("index:welcomeHero.partnerConnectButton", "Connect Wallet & Get Link")}
								</span>
							</Button>

							<Button
								type="button"
								variant="outline"
								onClick={() => navigate("/mining")}
								className="rounded-xl border-amber-500/30 bg-amber-500/10 px-3.5 py-2 text-xs font-medium text-amber-300 hover:bg-amber-500/20 hover:text-amber-200 transition-colors flex items-center gap-1.5 cursor-pointer"
							>
								<Pickaxe className="h-3.5 w-3.5 text-amber-400" />
								<span>{t("index:welcomeHero.partnerMiningButton", "Trade Mining & Referrals")}</span>
							</Button>
						</div>

						{/* Partner benefit tags */}
						<div className="flex flex-wrap items-center gap-2 text-xs">
							<div className="flex items-center gap-1.5 rounded-lg border border-amber-500/30 bg-amber-500/10 px-2.5 py-1 text-[11px] font-medium text-amber-300">
								<Gift className="h-3 w-3 text-amber-400" />
								<span>{t("index:welcomeHero.partnerHighlight1", "10% Referral Mining Boost")}</span>
							</div>
							<div className="flex items-center gap-1.5 rounded-lg border border-emerald-500/30 bg-emerald-500/10 px-2.5 py-1 text-[11px] font-medium text-emerald-300">
								<ShieldCheck className="h-3 w-3 text-emerald-400" />
								<span>
									{t("index:welcomeHero.partnerHighlight2", "No Trading or API Keys Required")}
								</span>
							</div>
							<div className="flex items-center gap-1.5 rounded-lg border border-cyan/30 bg-cyan/10 px-2.5 py-1 text-[11px] font-medium text-cyan">
								<Coins className="h-3 w-3 text-cyan" />
								<span>{t("index:welcomeHero.partnerHighlight3", "Rewards in $DEPTH Tokens")}</span>
							</div>
						</div>
					</div>
				)}
			</div>
		</div>
	);
};
