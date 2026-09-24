// src/components/layout/AccountSelector.tsx

import { Check, ChevronDown, Plus, Settings, Wallet, Zap } from "lucide-react";
import React, { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import { exchangeLabels, exchangeLogos, normalizeExchangeKey } from "@/lib/exchanges";
import { cn } from "@/lib/utils";
import type { AccountBalance, ApiKey } from "@/types/api";

export const ExchangeBadge: React.FC<{
	exchange?: string | null;
	size?: "xs" | "sm" | "md" | "lg" | "xl";
	className?: string;
	style?: React.CSSProperties;
}> = ({ exchange, size = "md", className, style }) => {
	const ex = normalizeExchangeKey(exchange);
	const logo = ex ? exchangeLogos[ex] : undefined;
	const label = (ex ? exchangeLabels[ex] : null) || exchange || "?";

	// Exact dimensions:
	// xs: 16x16px total. Inner box (minus 2x1px border) = 14x14px. Image = 10x10px -> exactly 2px padding on all 4 sides.
	// sm: 20x20px total. Inner box (minus 2x1px border) = 18x18px. Image = 12x12px -> exactly 3px padding on all 4 sides.
	// md: 26x26px total. Inner box (minus 2x1px border) = 24x24px. Image = 16x16px -> exactly 4px padding on all 4 sides.
	// lg: 28x28px total. Inner box (minus 2x1px border) = 26x26px. Image = 18x18px -> exactly 4px padding on all 4 sides.
	// xl: 40x40px total. Inner box (minus 2x1px border) = 38x38px. Image = 24x24px -> exactly 7px padding on all 4 sides.
	const sizeClasses = {
		xs: "h-4 w-4 min-w-4 min-h-4",
		sm: "h-5 w-5 min-w-5 min-h-5",
		md: "h-[26px] w-[26px] min-w-[26px] min-h-[26px]",
		lg: "h-7 w-7 min-w-7 min-h-7",
		xl: "h-10 w-10 min-w-10 min-h-10",
	}[size];

	const imgSizes = {
		xs: "h-2.5 w-2.5 max-h-2.5 max-w-2.5",
		sm: "h-3 w-3 max-h-3 max-w-3",
		md: "h-4 w-4 max-h-4 max-w-4",
		lg: "h-[18px] w-[18px] max-h-[18px] max-w-[18px]",
		xl: "h-[24px] w-[24px] max-h-[24px] max-w-[24px]",
	}[size];

	return (
		<span
			className={cn(
				"relative inline-grid place-items-center rounded-full bg-white shrink-0 shadow-sm border border-black/10 overflow-hidden select-none leading-none",
				sizeClasses,
				className,
			)}
			style={style}
			title={label}
		>
			{logo ? (
				<img
					src={logo}
					alt={label}
					className={cn(
						"m-auto block object-contain object-center pointer-events-none select-none shrink-0",
						imgSizes,
					)}
					draggable={false}
				/>
			) : (
				<span
					aria-label={label}
					className="m-auto block text-center font-semibold text-black/60 select-none"
					style={{ fontSize: 12, lineHeight: 1 }}
				>
					?
				</span>
			)}
		</span>
	);
};

interface AccountSelectorProps {
	accounts?: ApiKey[];
	balances?: Record<number, AccountBalance>;
	selectedAccountId: number | "all";
	onSelect: (accountId: number | "all") => void;
	className?: string;
	showBalances?: boolean;
}

export const AccountSelector: React.FC<AccountSelectorProps> = ({
	accounts = [],
	balances = {},
	selectedAccountId,
	onSelect,
	className,
	showBalances = true,
}) => {
	const { t } = useTranslation(["common", "account"]);
	const [isOpen, setIsOpen] = useState(false);
	const dropdownRef = useRef<HTMLDivElement>(null);

	// Close on click outside
	useEffect(() => {
		const handleClickOutside = (e: MouseEvent) => {
			if (dropdownRef.current && !dropdownRef.current.contains(e.target as Node)) {
				setIsOpen(false);
			}
		};
		document.addEventListener("mousedown", handleClickOutside);
		return () => document.removeEventListener("mousedown", handleClickOutside);
	}, []);

	// Process real accounts
	const displayAccounts = accounts.map((acc) => {
		const exKey = (acc.exchange || "binance").toLowerCase();
		const bal = balances[acc.id];
		
		const equity = bal ? (bal.totalEquity ?? bal.balance ?? 0) : 0;
		const pnl = bal ? (bal.unrealizedPnl ?? 0) : 0;
		const marketType = bal?.marketType === "spot" ? "spot" : "futures";

		return {
			id: acc.id,
			name: acc.name,
			exchange: exKey,
			equity,
			pnl,
			marketType,
			isActive: acc.isActive,
			status: acc.status || (acc.isActive ? "active" : "offline"),
			hasBalance: Boolean(bal),
		};
	});

	const totalEquity = displayAccounts.reduce((sum, a) => sum + a.equity, 0);
	const totalPnl = displayAccounts.reduce((sum, a) => sum + a.pnl, 0);
	const hasAnyBalances = displayAccounts.some((a) => a.hasBalance);

	const selected =
		selectedAccountId === "all"
			? null
			: displayAccounts.find((a) => a.id === selectedAccountId);

	const currentEquity = selected ? selected.equity : totalEquity;
	const currentPnl = selected ? selected.pnl : totalPnl;
	const currentHasBalance = selected ? selected.hasBalance : hasAnyBalances;

	// Extract unique active exchanges for compact overlapping display.
	// Derived on every render (no useMemo): displayAccounts is already rebuilt
	// on each render, so manual memoization here could never hit its cache and
	// it caused React Compiler to bail out of this component.
	const activeExchanges = (() => {
		if (selected) {
			return [{ id: `single-${selected.id}`, exchange: selected.exchange }];
		}
		const seen = new Set<string>();
		const result: { id: string; exchange: string }[] = [];
		for (const acc of displayAccounts) {
			const norm = normalizeExchangeKey(acc.exchange) || acc.exchange;
			if (norm && !seen.has(norm)) {
				seen.add(norm);
				result.push({ id: `ex-${norm}`, exchange: acc.exchange });
			}
		}
		if (result.length === 0 && displayAccounts.length > 0) {
			result.push({
				id: `acc-${displayAccounts[0].id}`,
				exchange: displayAccounts[0].exchange,
			});
		}
		return result;
	})();

	const formatUsd = (val: number) => {
		return `$${val.toLocaleString("en-US", {
			minimumFractionDigits: 0,
			maximumFractionDigits: 0,
		})}`;
	};

	const formatPnl = (val: number) => {
		const sign = val > 0 ? "+" : "";
		return `${sign}$${val.toLocaleString("en-US", {
			minimumFractionDigits: 0,
			maximumFractionDigits: 0,
		})}`;
	};

	// 1. When no active accounts exist: prompt user to connect an exchange
	if (displayAccounts.length === 0) {
		return (
			<div ref={dropdownRef} className={cn("relative", className)}>
				<button
					type="button"
					onClick={() => setIsOpen((prev) => !prev)}
					className={cn(
						"flex h-7 sm:h-8 items-center gap-1 sm:gap-2 rounded-lg border px-1.5 sm:px-2.5 transition-all text-left select-none shrink-0",
						isOpen
							? "border-cyan/40 bg-white/[0.08] shadow-[0_0_15px_-4px_rgba(0,212,255,0.45)]"
							: "border-white/10 bg-white/[0.03] hover:border-white/20 hover:bg-white/[0.06]",
					)}
				>
					<div className="flex h-5 w-5 items-center justify-center rounded-full bg-cyan/10 border border-cyan/30 text-cyan shrink-0">
						<Wallet size={11} />
					</div>
					<div className="hidden sm:block leading-none pr-0.5">
						<div className="text-[11.5px] font-semibold text-white">
							{t("common:selectAccount", "Connect Exchange")}
						</div>
						<div className="mt-0.5 text-[9.5px] text-white/40 font-mono">
							0 connected
						</div>
					</div>
					<ChevronDown
						size={13}
						className={cn(
							"text-white/40 transition-transform duration-200 shrink-0",
							isOpen && "rotate-180 text-white/80",
						)}
					/>
				</button>

				{isOpen && (
					<div className="absolute right-0 top-10 z-50 w-[300px] rounded-xl border border-white/10 bg-obsidian/95 p-3 shadow-2xl backdrop-blur-2xl animate-fade-up">
						<div className="flex items-center gap-2 pb-2 border-b border-white/5 text-[10px] uppercase font-semibold tracking-[0.16em] text-white/35">
							<span>Exchange Accounts</span>
						</div>
						<div className="py-4 text-center space-y-2">
							<div className="inline-flex h-9 w-9 items-center justify-center rounded-xl bg-white/[0.04] border border-white/10 text-white/50">
								<Wallet size={16} />
							</div>
							<div className="text-xs font-medium text-white/90">
								No exchange accounts connected
							</div>
							<p className="text-[11px] text-white/40 leading-relaxed max-w-[240px] mx-auto">
								Connect your Binance, Bybit, OKX, or Bitget API keys to trade and view live balances.
							</p>
						</div>
						<Link
							to="/settings"
							onClick={() => setIsOpen(false)}
							className="flex items-center justify-center gap-1.5 w-full py-2 rounded-lg bg-gradient-to-r from-azure to-cyan text-white text-xs font-semibold shadow-[0_0_15px_-3px_rgba(0,212,255,0.5)] hover:shadow-[0_0_20px_-2px_rgba(0,212,255,0.7)] transition-all"
						>
							<Plus size={13} />
							<span>Connect API Key</span>
						</Link>
					</div>
				)}
			</div>
		);
	}

	// 2. When real accounts exist
	return (
		<div ref={dropdownRef} className={cn("relative", className)}>
			{/* Trigger Button */}
			<button
				type="button"
				onClick={() => setIsOpen((prev) => !prev)}
				className={cn(
					"flex h-7 sm:h-8 items-center gap-1 sm:gap-2 rounded-lg border px-1.5 sm:px-2.5 transition-all text-left select-none shrink-0",
					isOpen
						? "border-cyan/40 bg-white/[0.08] shadow-[0_0_15px_-4px_rgba(0,212,255,0.45)]"
						: "border-white/10 bg-white/[0.03] hover:border-white/20 hover:bg-white/[0.06]",
				)}
			>
				{/* Real Exchange Logos: single badge or compact overlapping badges when multiple are selected */}
				{activeExchanges.length === 1 ? (
					<ExchangeBadge
						exchange={activeExchanges[0].exchange}
						size="sm"
						className="border-obsidian/80 shadow-sm"
					/>
				) : (
					<div className="flex shrink-0 items-center pl-0.5">
						{(activeExchanges.length <= 4
							? activeExchanges
							: activeExchanges.slice(0, 3)
						).map((item, index, arr) => (
							<ExchangeBadge
								key={item.id}
								exchange={item.exchange}
								size="sm"
								className={cn(
									"ring-2 ring-[#0b0d12] relative shadow-sm transition-transform duration-150 hover:scale-110 hover:z-30",
									index > 0 && "-ml-2.5",
								)}
								style={{
									zIndex: arr.length - index,
									marginLeft: index > 0 ? "-10px" : undefined,
								}}
							/>
						))}
						{activeExchanges.length > 4 && (
							<span
								className="-ml-2.5 relative inline-flex items-center justify-center rounded-full bg-white/[0.08] text-white/80 font-mono text-[9px] font-semibold h-5 w-5 min-w-5 min-h-5 ring-2 ring-[#0b0d12] border border-white/10 shrink-0"
								style={{ zIndex: 0, marginLeft: "-10px" }}
								title={`+${activeExchanges.length - 3} more exchanges`}
							>
								+{activeExchanges.length - 3}
							</span>
						)}
					</div>
				)}

				{/* Account Info */}
				<div className="hidden sm:block leading-none pr-0.5">
					<div className="text-[11.5px] font-semibold text-white truncate max-w-[120px]">
						{selected ? selected.name : t("common:allAccounts", "All Accounts")}
					</div>
					{showBalances && (
						<div className="mt-0.5 flex items-center gap-1.5 font-mono text-[10px]">
							<span className="text-white/70">
								{currentHasBalance ? formatUsd(currentEquity) : "—"}
							</span>
							{currentHasBalance && currentPnl !== 0 && (
								<span
									className={cn(
										"font-medium",
										currentPnl >= 0 ? "text-emerald-400" : "text-rose-400",
									)}
								>
									{formatPnl(currentPnl)}
								</span>
							)}
						</div>
					)}
				</div>

				<ChevronDown
					size={13}
					className={cn(
						"text-white/40 transition-transform duration-200 shrink-0",
						isOpen && "rotate-180 text-white/80",
					)}
				/>
			</button>

			{/* Cyber-Quant Glass Dropdown */}
			{isOpen && (
				<div className="absolute right-0 top-10 z-50 w-[320px] rounded-xl border border-white/10 bg-obsidian/95 p-1.5 shadow-2xl backdrop-blur-2xl animate-fade-up">
					<div className="px-2.5 pt-1.5 pb-2 text-[10px] uppercase font-semibold tracking-[0.16em] text-white/35 flex items-center justify-between">
						<span>Exchange Accounts</span>
						<span className="font-mono text-[9px] text-cyan/70">
							{displayAccounts.length} Connected
						</span>
					</div>

					{/* Aggregate View Option */}
					<button
						type="button"
						onClick={() => {
							onSelect("all");
							setIsOpen(false);
						}}
						className={cn(
							"flex w-full items-center gap-3 rounded-lg px-2.5 py-2 text-left transition-all hover:bg-white/5",
							selectedAccountId === "all" && "bg-white/[0.06] border border-cyan/30",
						)}
					>
						<div className="flex h-7 w-7 items-center justify-center rounded-lg bg-gradient-to-br from-cyan/20 to-azure/20 text-cyan shrink-0 border border-cyan/30">
							<Zap size={14} />
						</div>
						<div className="flex-1 min-w-0">
							<div className="flex items-center gap-1.5">
								<span className="text-[12px] font-semibold text-white">
									{t("common:allAccounts", "Aggregate View")}
								</span>
								{activeExchanges.length > 1 && (
									<div className="flex shrink-0 items-center">
										{activeExchanges.slice(0, 3).map((item, idx) => (
											<ExchangeBadge
												key={item.id}
												exchange={item.exchange}
												size="xs"
												className={cn("ring-1 ring-[#0b0d12]", idx > 0 && "-ml-2")}
												style={{ zIndex: 3 - idx, marginLeft: idx > 0 ? "-8px" : undefined }}
											/>
										))}
									</div>
								)}
							</div>
							<div className="text-[10px] text-white/40 truncate">
								{displayAccounts.length} accounts · multi-exchange
							</div>
						</div>
						{showBalances && (
							<div className="text-right font-mono shrink-0">
								<div className="text-[12px] font-medium text-white">
									{hasAnyBalances ? formatUsd(totalEquity) : "—"}
								</div>
								{hasAnyBalances && totalPnl !== 0 && (
									<div
										className={cn(
											"text-[10px] font-semibold",
											totalPnl >= 0 ? "text-emerald-400" : "text-rose-400",
										)}
									>
										{formatPnl(totalPnl)}
									</div>
								)}
							</div>
						)}
						{selectedAccountId === "all" && (
							<Check size={13} className="text-cyan ml-1 shrink-0" />
						)}
					</button>

					<div className="my-1.5 h-px bg-white/5" />

					{/* List of Connected API Keys */}
					<div className="max-h-[260px] overflow-y-auto space-y-0.5 pr-0.5">
					{displayAccounts.map((a) => {
						const nEx = normalizeExchangeKey(a.exchange);
						const logo = nEx ? exchangeLogos[nEx] : undefined;
						const label =
							(nEx ? exchangeLabels[nEx] : null) || a.exchange || "?";
						void logo;
							const isSel = selectedAccountId === a.id;
							return (
								<button
									key={a.id}
									type="button"
									onClick={() => {
										onSelect(a.id);
										setIsOpen(false);
									}}
									className={cn(
										"flex w-full items-center gap-3 rounded-lg px-2.5 py-2 text-left transition-all hover:bg-white/5",
										isSel && "bg-white/[0.06] border border-cyan/30",
									)}
								>
									<ExchangeBadge
										exchange={a.exchange}
										size="lg"
										className="rounded-lg"
									/>
									<div className="flex-1 min-w-0">
										<div className="flex items-center gap-1.5 text-[12px] font-medium text-white truncate">
											<span className="truncate">{a.name}</span>
											<span className="text-[8.5px] uppercase px-1 py-0.2 rounded bg-white/5 text-white/40 font-mono">
												{a.marketType}
											</span>
										</div>
										<div className="flex items-center gap-1.5 text-[10px] text-white/40">
											<span>{label}</span>
											<span
												className={cn(
													"h-1.5 w-1.5 rounded-full",
													a.isActive
														? "bg-emerald-400 shadow-[0_0_4px_#34d399]"
														: "bg-amber-400",
												)}
											/>
											<span>{a.isActive ? "active" : "offline"}</span>
										</div>
									</div>
									{showBalances && (
										<div className="text-right font-mono shrink-0">
											<div className="text-[12px] font-medium text-white">
												{a.hasBalance ? formatUsd(a.equity) : "—"}
											</div>
											{a.hasBalance && a.pnl !== 0 && (
												<div
													className={cn(
														"text-[10px] font-semibold",
														a.pnl >= 0 ? "text-emerald-400" : "text-rose-400",
													)}
												>
													{formatPnl(a.pnl)}
												</div>
											)}
										</div>
									)}
									{isSel && (
										<Check size={13} className="text-cyan ml-1 shrink-0" />
									)}
								</button>
							);
						})}
					</div>

					<div className="my-1.5 h-px bg-white/5" />

					{/* Manage API Keys Link */}
					<Link
						to="/settings"
						onClick={() => setIsOpen(false)}
						className="flex w-full items-center gap-2 rounded-lg px-2.5 py-1.5 text-[11px] font-medium text-cyan hover:bg-cyan/10 transition-colors"
					>
						<Settings size={13} />
						<span>Manage API keys</span>
					</Link>
				</div>
			)}
		</div>
	);
};

export default AccountSelector;
