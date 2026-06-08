// pwa/screens/ResearchScreen.tsx

import type React from "react";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Logo } from "../components/ui/logo";
import { api } from "../services/api";
import type { BacktestRunListItem } from "../types";

interface ResearchScreenProps {
	onViewResult: (runId: string) => void;
}

import { useSwipeable } from "react-swipeable";
import Tabs from "../components/Tabs";
import AnalyticsScreen from "./AnalyticsScreen";

const ResearchScreen: React.FC<ResearchScreenProps> = ({ onViewResult }) => {
	const [backtests, setBacktests] = useState<BacktestRunListItem[]>([]);
	const [loading, setLoading] = useState(true);
	const [error, setError] = useState<string | null>(null);
	const [currentPage, setCurrentPage] = useState(1);
	const [totalPages, setTotalPages] = useState(1);
	const [activeTab, setActiveTab] = useState(0); // 0: Backtests, 1: Analytics
	const pageSize = 5;
	const { t } = useTranslation("pwa-common");

	const handlePrevPage = () => setCurrentPage((prev) => Math.max(1, prev - 1));
	const handleNextPage = () =>
		setCurrentPage((prev) => Math.min(totalPages, prev + 1));

	const swipeHandlers = useSwipeable({
		onSwipedLeft: handleNextPage,
		onSwipedRight: handlePrevPage,
		preventScrollOnSwipe: true,
		trackMouse: true,
	});

	useEffect(() => {
		const fetchBacktests = async () => {
			setLoading(true);
			setError(null);
			try {
				const response = await api.getBacktests();
				setBacktests(response);
				setTotalPages(Math.max(1, Math.ceil(response.length / pageSize)));
				setCurrentPage(1);
			} catch (err) {
				console.error("Failed to fetch backtests:", err);
				setError(t("profile.failedToLoadPlans"));
			} finally {
				setLoading(false);
			}
		};
		fetchBacktests();
	}, [t]);

	const getStatusChip = (status: string) => {
		switch (status.toUpperCase()) {
			case "COMPLETED":
				return (
					<span className="px-3 py-1 text-xs font-medium text-[hsl(var(--primary-foreground))] bg-[hsl(var(--profit))] rounded-full">
						{t("research.status.completed")}
					</span>
				);
			case "RUNNING":
				return (
					<span className="px-3 py-1 text-xs font-medium text-black bg-[hsl(var(--warning))] rounded-full">
						{t("research.status.running")}
					</span>
				);
			case "PENDING":
				return (
					<span className="px-3 py-1 text-xs font-medium text-[hsl(var(--secondary-foreground))] bg-[hsl(var(--secondary))] rounded-full">
						{t("research.status.pending")}
					</span>
				);
			case "FAILED":
				return (
					<span className="px-3 py-1 text-xs font-medium text-[hsl(var(--destructive-foreground))] bg-[hsl(var(--destructive))] rounded-full">
						{t("research.status.failed")}
					</span>
				);
			default:
				return null;
		}
	};

	if (loading) {
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

	const startIndex = (currentPage - 1) * pageSize;
	const visibleBacktests = backtests.slice(startIndex, startIndex + pageSize);

	const backtestsContent = (
		<div {...swipeHandlers} className="animate-fadeIn">
			<div className="space-y-4">
				{visibleBacktests.length > 0 ? (
					visibleBacktests.map((run) => (
						<button
							key={run.id}
							onClick={() => onViewResult(run.id)}
							className="w-full bg-[hsl(var(--card))] rounded-xl p-4 shadow-sm text-left transition-all hover:shadow-md hover:border-[hsl(var(--primary))] border border-transparent disabled:opacity-50 disabled:cursor-not-allowed"
							disabled={run.status.toUpperCase() !== "COMPLETED"}
						>
							<div className="flex justify-between items-center">
								<div>
									<div className="font-medium text-[hsl(var(--card-foreground))]">
										{run.strategy_name}
									</div>
									<div className="text-sm text-[hsl(var(--muted-foreground))]">
										{run.symbol}
									</div>
								</div>
								{getStatusChip(run.status)}
							</div>
							{run.status.toUpperCase() === "COMPLETED" && (
								<div className="flex gap-5 mt-3 text-[hsl(var(--card-foreground))]">
									<div>
										<div className="text-xs text-[hsl(var(--muted-foreground))]">
											{t("research.netPnl")}
										</div>
										<div
											className={`font-medium ${(run.pnl ?? 0) >= 0 ? "text-[hsl(var(--profit))]" : "text-[hsl(var(--loss))]"}`}
										>
											{(run.pnl ?? 0) >= 0 ? "+" : ""}$
											{run.pnl?.toLocaleString(undefined, {
												minimumFractionDigits: 2,
												maximumFractionDigits: 2,
											}) ?? "N/A"}
										</div>
									</div>
									<div>
										<div className="text-xs text-[hsl(var(--muted-foreground))]">
											{t("research.winRate")}
										</div>
										<div className="font-medium">
											{(run.win_rate ?? 0).toFixed(2)}%
										</div>
									</div>
								</div>
							)}
							{run.status.toUpperCase() === "RUNNING" && (
								<div className="mt-3">
									<div className="text-xs text-[hsl(var(--muted-foreground))]">
										{t("research.inProgress")}
									</div>
									<div className="bg-[hsl(var(--secondary))] h-1 rounded-full mt-2 overflow-hidden relative">
										<div className="absolute top-0 left-0 bottom-0 w-1/2 bg-[hsl(var(--primary))] rounded-full animate-pulse"></div>
									</div>
								</div>
							)}
						</button>
					))
				) : (
					<p className="text-center text-sm text-[hsl(var(--muted-foreground))] py-8">
						{t("research.noBacktests")}
					</p>
				)}
			</div>

			{totalPages > 1 && (
				<div className="mt-4 flex items-center justify-between gap-3 rounded-xl bg-[hsl(var(--card))] px-4 py-3 shadow-sm">
					<button
						onClick={handlePrevPage}
						className="flex-1 rounded-lg bg-[hsl(var(--secondary))] px-3 py-2 text-sm text-[hsl(var(--secondary-foreground))] transition hover:opacity-90 disabled:opacity-50"
						disabled={currentPage === 1}
					>
						{t("backtestResultScreen.back")}
					</button>
					<div className="text-sm text-[hsl(var(--muted-foreground))] text-center">
						{t("backtestResultScreen.page")} {currentPage} / {totalPages}
					</div>
					<button
						onClick={handleNextPage}
						className="flex-1 rounded-lg bg-[hsl(var(--secondary))] px-3 py-2 text-sm text-[hsl(var(--secondary-foreground))] transition hover:opacity-90 disabled:opacity-50"
						disabled={currentPage === totalPages}
					>
						{t("backtestResultScreen.forward")}
					</button>
				</div>
			)}
		</div>
	);

	const tabs = [
		{ label: t("header.research"), content: backtestsContent },
		{ label: t("header.analytics", "Analytics"), content: <AnalyticsScreen /> },
	];

	return (
		<div className="p-4 pt-0">
			<Tabs tabs={tabs} activeTab={activeTab} setActiveTab={setActiveTab} />
			<div className="h-4"></div>
		</div>
	);
};

export default ResearchScreen;
