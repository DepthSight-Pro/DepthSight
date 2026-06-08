// pwa/components/BacktestModal.tsx

import type React from "react";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import type { DisplayStrategy } from "../types";

interface BacktestModalProps {
	isOpen: boolean;
	onClose: () => void;
	onSubmit: (details: {
		symbol: string;
		startDate: string;
		endDate: string;
	}) => void;
	strategy: DisplayStrategy | null;
}

const BacktestModal: React.FC<BacktestModalProps> = ({
	isOpen,
	onClose,
	onSubmit,
	strategy,
}) => {
	const { t } = useTranslation("pwa-common");
	const [symbol, setSymbol] = useState("");
	const [startDate, setStartDate] = useState("");
	const [endDate, setEndDate] = useState("");

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
		}, 0);
		return () => clearTimeout(timer);
	}, [strategy]);

	if (!isOpen) return null;

	const handleSubmit = () => {
		if (symbol && startDate && endDate) {
			onSubmit({ symbol, startDate, endDate });
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
				className={`fixed top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[90%] max-w-md bg-[hsl(var(--card))] rounded-3xl shadow-[-4px_0_20px_rgba(0,0,0,0.1)] p-6 z-50 transition-all duration-300 ease-out ${isOpen ? "scale-100 opacity-100" : "scale-95 opacity-0"}`}
			>
				<h2 className="text-xl font-medium mb-1 text-[hsl(var(--card-foreground))]">
					{t("backtestModal.strategyBacktest")}
				</h2>
				<p className="text-sm text-[hsl(var(--muted-foreground))] mb-5">
					{strategy?.name}
				</p>

				<div className="mb-4">
					<label
						htmlFor="backtest-symbol"
						className="text-sm text-[hsl(var(--muted-foreground))] mb-2 block"
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
				<div className="mb-4">
					<label
						htmlFor="backtest-start-date"
						className="text-sm text-[hsl(var(--muted-foreground))] mb-2 block"
					>
						{t("backtestModal.startDate")}
					</label>
					<input
						id="backtest-start-date"
						type="date"
						className="w-full p-3 bg-[hsl(var(--secondary))] border border-[hsl(var(--border))] rounded-lg text-base text-[hsl(var(--foreground))] placeholder:text-[hsl(var(--muted-foreground))] outline-none transition-all focus:border-[hsl(var(--primary))] focus:ring-1 focus:ring-[hsl(var(--primary))]"
						value={startDate}
						onChange={(e) => setStartDate(e.target.value)}
					/>
				</div>
				<div className="mb-4">
					<label
						htmlFor="backtest-end-date"
						className="text-sm text-[hsl(var(--muted-foreground))] mb-2 block"
					>
						{t("backtestModal.endDate")}
					</label>
					<input
						id="backtest-end-date"
						type="date"
						className="w-full p-3 bg-[hsl(var(--secondary))] border border-[hsl(var(--border))] rounded-lg text-base text-[hsl(var(--foreground))] placeholder:text-[hsl(var(--muted-foreground))] outline-none transition-all focus:border-[hsl(var(--primary))] focus:ring-1 focus:ring-[hsl(var(--primary))]"
						value={endDate}
						onChange={(e) => setEndDate(e.target.value)}
					/>
				</div>

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
