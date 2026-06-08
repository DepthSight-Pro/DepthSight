// src/components/research/CombinationsPerformanceTable.tsx

import { ArrowDown, ArrowUp } from "lucide-react";
import type React from "react";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Badge } from "@/components/ui/badge";
import {
	Card,
	CardContent,
	CardDescription,
	CardHeader,
	CardTitle,
} from "@/components/ui/card";
import {
	Table,
	TableBody,
	TableCell,
	TableHead,
	TableHeader,
	TableRow,
} from "@/components/ui/table";
import type { BacktestTrade } from "@/types/api";

type CombinationData = {
	combination: string[];
	pnl: number;
	winRate: number;
	totalTrades: number;
};

type SortConfig = {
	key: keyof Omit<CombinationData, "combination">; // Sorting by combination is not very useful
	direction: "asc" | "desc";
};

// --- New, "smart" parsing function ---

// List of "simple" foundations that can be counted if they are not in a group.
const SIMPLE_FOUNDATION_TYPES = new Set([
	"volume_confirmation",
	"trend_direction",
	"classic_pattern",
	"round_level",
]);

const getTriggeredFoundations = (trace: Record<string, unknown>): string[] => {
	const foundations = new Set<string>();

	const traverse = (node: Record<string, unknown>) => {
		if (!node || typeof node !== "object") {
			return;
		}

		const nodeId = node.id as string | undefined;
		const nodeType = node.type as string | undefined;
		const nodeResult = node.result as boolean | undefined;

		// RULE 1: If this is a weighted group (ID starts with 'w_') and it triggered,
		// we add its ID and do NOT descend into its child elements.
		if (nodeId?.startsWith("w_") && nodeResult === true) {
			foundations.add(nodeId);
			return; // Critically important! Stopping recursion for this branch.
		}

		// RULE 2: If this is a simple foundation from our list and it triggered,
		// we add its ID.
		if (
			nodeType &&
			SIMPLE_FOUNDATION_TYPES.has(nodeType) &&
			nodeResult === true
		) {
			if (nodeId) {
				foundations.add(nodeId);
			}
			return; // Also stop the descent.
		}

		// If the node is not a meaningful foundation, continue the traversal.
		if (Array.isArray(node.children)) {
			for (const child of node.children as Record<string, unknown>[]) {
				traverse(child);
			}
		}
	};

	traverse(trace);

	return Array.from(foundations);
};

export const CombinationsPerformanceTable: React.FC<{
	trades: BacktestTrade[];
}> = ({ trades }) => {
	const { t } = useTranslation(["research"]);
	const [sortConfig, setSortConfig] = useState<SortConfig>({
		key: "pnl",
		direction: "desc",
	});

	const combinationsData = useMemo<CombinationData[]>(() => {
		if (!trades || trades.length === 0) {
			return [];
		}

		const combinationsMap = new Map<
			string,
			{ pnl: number; winCount: number; totalCount: number }
		>();

		trades.forEach((trade) => {
			let decisionTrace: Record<string, unknown> = {};
			try {
				if (typeof trade.decision_trace_json === "string") {
					decisionTrace = JSON.parse(trade.decision_trace_json || "{}");
				} else if (
					typeof trade.decision_trace_json === "object" &&
					trade.decision_trace_json !== null
				) {
					decisionTrace = trade.decision_trace_json;
				}
			} catch (parseError) {
				console.error("Failed to parse decision_trace_json", parseError);
			}

			const triggeredFoundations = getTriggeredFoundations(decisionTrace);

			if (triggeredFoundations.length > 0) {
				const sortedCombination = [...triggeredFoundations].sort();
				const combinationKey = sortedCombination.join(",");

				const entry = combinationsMap.get(combinationKey) || {
					pnl: 0,
					winCount: 0,
					totalCount: 0,
				};

				entry.pnl += trade.pnl;
				entry.totalCount += 1;
				if (trade.pnl > 0) {
					entry.winCount += 1;
				}

				combinationsMap.set(combinationKey, entry);
			}
		});

		return Array.from(combinationsMap.entries()).map(([key, data]) => ({
			combination: key.split(","),
			pnl: data.pnl,
			winRate: (data.winCount / data.totalCount) * 100,
			totalTrades: data.totalCount,
		}));
	}, [trades]);

	const sortedData = useMemo(() => {
		const sortableData = [...combinationsData];
		sortableData.sort((a, b) => {
			const key = sortConfig.key;
			if (a[key] < b[key]) {
				return sortConfig.direction === "asc" ? -1 : 1;
			}
			if (a[key] > b[key]) {
				return sortConfig.direction === "asc" ? 1 : -1;
			}
			return 0;
		});
		return sortableData;
	}, [combinationsData, sortConfig]);

	const handleSort = (key: SortConfig["key"]) => {
		setSortConfig((prev) => ({
			key,
			direction: prev.key === key && prev.direction === "desc" ? "asc" : "desc",
		}));
	};

	const renderSortArrow = (key: SortConfig["key"]) => {
		if (sortConfig.key !== key) return null;
		return sortConfig.direction === "desc" ? (
			<ArrowDown className="w-3 h-3 ml-1" />
		) : (
			<ArrowUp className="w-3 h-3 ml-1" />
		);
	};

	return (
		<Card className="h-full flex flex-col">
			<CardHeader>
				<CardTitle>{t("combinationsPerformance.title")}</CardTitle>
				<CardDescription>
					{t("combinationsPerformance.description")}
				</CardDescription>
			</CardHeader>
			<CardContent className="flex-grow overflow-auto">
				{sortedData.length === 0 ? (
					<div className="flex items-center justify-center h-full text-sm text-muted-foreground">
						{t("combinationsPerformance.noTrades")}
					</div>
				) : (
					<Table>
						<TableHeader>
							<TableRow>
								<TableHead>
									<div className="flex items-center">
										{t("combinationsPerformance.header.combination")}
									</div>
								</TableHead>
								<TableHead
									onClick={() => handleSort("pnl")}
									className="cursor-pointer text-right"
								>
									<div className="flex items-center justify-end">
										{t("combinationsPerformance.header.pnl")}{" "}
										{renderSortArrow("pnl")}
									</div>
								</TableHead>
								<TableHead
									onClick={() => handleSort("winRate")}
									className="cursor-pointer text-right"
								>
									<div className="flex items-center justify-end">
										{t("combinationsPerformance.header.winRate")}{" "}
										{renderSortArrow("winRate")}
									</div>
								</TableHead>
								<TableHead
									onClick={() => handleSort("totalTrades")}
									className="cursor-pointer text-right"
								>
									<div className="flex items-center justify-end">
										{t("combinationsPerformance.header.totalTrades")}{" "}
										{renderSortArrow("totalTrades")}
									</div>
								</TableHead>
							</TableRow>
						</TableHeader>
						<TableBody>
							{sortedData.map((data, index) => (
								<TableRow key={index}>
									<TableCell className="flex flex-wrap gap-1">
										{/* --- Displaying ID, not type --- */}
										{data.combination.map((c) => (
											<Badge key={c} variant="outline">
												{c.replace("w_", "")}
											</Badge>
										))}
									</TableCell>
									<TableCell
										className={`text-right font-medium ${data.pnl > 0 ? "text-green-500" : "text-red-500"}`}
									>
										{data.pnl.toFixed(2)}
									</TableCell>
									<TableCell className="text-right">
										{data.winRate.toFixed(2)}%
									</TableCell>
									<TableCell className="text-right">
										{data.totalTrades}
									</TableCell>
								</TableRow>
							))}
						</TableBody>
					</Table>
				)}
			</CardContent>
		</Card>
	);
};
