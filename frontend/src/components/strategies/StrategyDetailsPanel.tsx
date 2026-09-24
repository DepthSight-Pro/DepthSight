// src/components/strategies/StrategyDetailsPanel.tsx

import { XIcon } from "lucide-react";
import type React from "react";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import {
	Card,
	CardContent,
	CardDescription,
	CardHeader,
	CardTitle,
} from "@/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import type { StrategyConfigData, StrategyData } from "@/types/api";
import { StrategyOverviewTab } from "./StrategyOverviewTab";
import { StrategyTradeHistoryTab } from "./StrategyTradeHistoryTab";

// Logs tab removed

// Define a new type for props that will work
type CombinedStrategyForPanel = StrategyData & {
	config_data?: StrategyConfigData;
	symbols?: string[];
};

interface StrategyDetailsPanelProps {
	selectedStrategy?: CombinedStrategyForPanel | null;
	/** Alias used by the Strategies page (`strategy=`). */
	strategy?: CombinedStrategyForPanel | null;
	isOpen?: boolean;
	onClose: () => void;
	onStart?: () => void;
	onStop?: () => void;
	onEdit?: () => void;
}

export const StrategyDetailsPanel: React.FC<StrategyDetailsPanelProps> = ({
	selectedStrategy,
	strategy,
	isOpen,
	onClose,
	onStart,
	onStop,
	onEdit,
}) => {
	const { t } = useTranslation("strategies");

	const resolvedStrategy = selectedStrategy ?? strategy ?? null;

	if (isOpen === false) {
		return null;
	}

	if (!resolvedStrategy) {
		return (
			<Card className="mt-6">
				<CardHeader>
					<CardTitle>{t("detailsPanel.noStrategySelectedTitle")}</CardTitle>
					<CardDescription>
						{t("detailsPanel.noStrategySelectedDesc")}
					</CardDescription>
				</CardHeader>
			</Card>
		);
	}

	const displaySymbols =
		resolvedStrategy.symbols?.join(", ") ||
		resolvedStrategy.config_data?.symbol ||
		"N/A";
	const displayName = resolvedStrategy.name;
	const hasActions = onStart || onStop || onEdit;

	return (
		<Card className="mt-6 sticky top-6">
			<CardHeader className="flex flex-row items-center justify-between">
				<div>
					<CardTitle>
						{t("detailsPanel.title", { name: displayName })}
					</CardTitle>
					<CardDescription>
						{t("detailsPanel.description", {
							symbol: displaySymbols,
							id: resolvedStrategy.id,
						})}
					</CardDescription>
				</div>
				<Button variant="ghost" size="icon" onClick={onClose}>
					<XIcon className="h-5 w-5" />
				</Button>
			</CardHeader>
			<CardContent>
				{hasActions && (
					<div className="mb-4 flex flex-wrap gap-2">
						{onStart && (
							<Button variant="default" size="sm" onClick={onStart}>
								{t("startTooltip", "Start")}
							</Button>
						)}
						{onStop && (
							<Button variant="outline" size="sm" onClick={onStop}>
								{t("stopTooltip", "Stop")}
							</Button>
						)}
						{onEdit && (
							<Button variant="ghost" size="sm" onClick={onEdit}>
								{t("editButton", "Load in editor")}
							</Button>
						)}
					</div>
				)}
				<Tabs defaultValue="overview">
					<TabsList className="grid w-full grid-cols-2">
						<TabsTrigger value="overview">
							{t("detailsPanel.tabOverview")}
						</TabsTrigger>
						<TabsTrigger value="trade-history">
							{t("detailsPanel.tabTradeHistory")}
						</TabsTrigger>
					</TabsList>

					<TabsContent value="overview" className="pt-4">
						<StrategyOverviewTab strategy={resolvedStrategy} />
					</TabsContent>

					<TabsContent value="trade-history" className="pt-4">
						<StrategyTradeHistoryTab strategyId={resolvedStrategy.id} />
					</TabsContent>
				</Tabs>
			</CardContent>
		</Card>
	);
};
