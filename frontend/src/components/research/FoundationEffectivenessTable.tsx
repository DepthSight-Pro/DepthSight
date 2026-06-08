// src/components/research/FoundationEffectivenessTable.tsx

import { ArrowDown, ArrowUp } from "lucide-react";
import type React from "react";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Badge } from "@/components/ui/badge";
import {
	Table,
	TableBody,
	TableCell,
	TableHead,
	TableHeader,
	TableRow,
} from "@/components/ui/table";
import type { BacktestTrade } from "@/types/api";

type FoundationData = {
	foundationId: string;
	pnl: number;
	winRate: number;
	totalTrades: number;
};

type SortConfig = {
	key: keyof Omit<FoundationData, "foundationId">;
	direction: "asc" | "desc";
};

const SIMPLE_FOUNDATION_TYPES = new Set([
	"volume_confirmation",
	"trend_direction",
	"classic_pattern",
	"round_level",
]);

type TraceNode = {
	id?: unknown;
	type?: unknown;
	result?: unknown;
	children?: unknown;
};

const getTriggeredFoundations = (trace: unknown): string[] => {
	const foundations = new Set<string>();
	const traverse = (node: unknown) => {
		if (!node || typeof node !== "object") return;
		const traceNode = node as TraceNode;
		const nodeId = typeof traceNode.id === "string" ? traceNode.id : undefined;
		const nodeType =
			typeof traceNode.type === "string" ? traceNode.type : undefined;
		const nodeResult =
			typeof traceNode.result === "boolean" ? traceNode.result : undefined;

		if (nodeId?.startsWith("w_") && nodeResult === true) {
			foundations.add(nodeId);
			return;
		}
		if (
			nodeType &&
			SIMPLE_FOUNDATION_TYPES.has(nodeType) &&
			nodeResult === true
		) {
			if (nodeId) foundations.add(nodeId);
			return;
		}
		if (Array.isArray(traceNode.children)) {
			for (const child of traceNode.children) traverse(child);
		}
	};
	traverse(trace);
	return Array.from(foundations);
};

export const FoundationEffectivenessTable: React.FC<{
	trades: BacktestTrade[];
}> = ({ trades }) => {
	const { t } = useTranslation(["research"]);
	const [sortConfig, setSortConfig] = useState<SortConfig>({
		key: "pnl",
		direction: "desc",
	});

	const foundationsData = useMemo<FoundationData[]>(() => {
		if (!trades || trades.length === 0) return [];

		const foundationsMap = new Map<
			string,
			{ pnl: number; winCount: number; totalCount: number }
		>();

		trades.forEach((trade) => {
			let decisionTrace: unknown = {};
			try {
				if (typeof trade.decision_trace_json === "string") {
					decisionTrace = JSON.parse(trade.decision_trace_json || "{}");
				} else if (
					typeof trade.decision_trace_json === "object" &&
					trade.decision_trace_json !== null
				) {
					decisionTrace = trade.decision_trace_json;
				}
			} catch (e) {
				console.error("Failed to parse decision_trace_json", e);
			}

			const triggeredFoundations = getTriggeredFoundations(decisionTrace);

			triggeredFoundations.forEach((foundationId) => {
				const entry = foundationsMap.get(foundationId) || {
					pnl: 0,
					winCount: 0,
					totalCount: 0,
				};
				entry.pnl += trade.pnl;
				entry.totalCount += 1;
				if (trade.pnl > 0) entry.winCount += 1;
				foundationsMap.set(foundationId, entry);
			});
		});

		return Array.from(foundationsMap.entries()).map(([key, data]) => ({
			foundationId: key,
			pnl: data.pnl,
			winRate: (data.winCount / data.totalCount) * 100,
			totalTrades: data.totalCount,
		}));
	}, [trades]);

	const sortedData = useMemo(() => {
		const sortableData = [...foundationsData];
		sortableData.sort((a, b) => {
			const key = sortConfig.key;
			if (a[key] < b[key]) return sortConfig.direction === "asc" ? -1 : 1;
			if (a[key] > b[key]) return sortConfig.direction === "asc" ? 1 : -1;
			return 0;
		});
		return sortableData;
	}, [foundationsData, sortConfig]);

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
		<div className="flex-grow overflow-auto">
			{sortedData.length === 0 ? (
				<div className="flex items-center justify-center h-full text-sm text-muted-foreground">
					{t("combinationsPerformance.noTrades")}
				</div>
			) : (
				<Table>
					<TableHeader>
						<TableRow>
							<TableHead>
								{t("foundationEffectiveness.header.foundation")}
							</TableHead>
							<TableHead
								onClick={() => handleSort("pnl")}
								className="cursor-pointer text-right"
							>
								<div className="flex items-center justify-end">
									{t("foundationEffectiveness.header.pnl")}{" "}
									{renderSortArrow("pnl")}
								</div>
							</TableHead>
							<TableHead
								onClick={() => handleSort("winRate")}
								className="cursor-pointer text-right"
							>
								<div className="flex items-center justify-end">
									{t("foundationEffectiveness.header.winRate")}{" "}
									{renderSortArrow("winRate")}
								</div>
							</TableHead>
							<TableHead
								onClick={() => handleSort("totalTrades")}
								className="cursor-pointer text-right"
							>
								<div className="flex items-center justify-end">
									{t("foundationEffectiveness.header.totalTrades")}{" "}
									{renderSortArrow("totalTrades")}
								</div>
							</TableHead>
						</TableRow>
					</TableHeader>
					<TableBody>
						{sortedData.map((data, index) => (
							<TableRow key={index}>
								<TableCell>
									<Badge variant="outline">
										{data.foundationId.replace("w_", "")}
									</Badge>
								</TableCell>
								<TableCell
									className={`text-right font-medium ${data.pnl > 0 ? "text-green-500" : "text-red-500"}`}
								>
									{data.pnl.toFixed(2)}
								</TableCell>
								<TableCell className="text-right">
									{data.winRate.toFixed(2)}%
								</TableCell>
								<TableCell className="text-right">{data.totalTrades}</TableCell>
							</TableRow>
						))}
					</TableBody>
				</Table>
			)}
		</div>
	);
};
