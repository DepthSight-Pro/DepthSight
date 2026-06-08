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
	selectedStrategy: CombinedStrategyForPanel | null;
	onClose: () => void;
}

export const StrategyDetailsPanel: React.FC<StrategyDetailsPanelProps> = ({
	selectedStrategy,
	onClose,
}) => {
	const { t } = useTranslation("strategies");

	if (!selectedStrategy) {
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
		selectedStrategy.symbols?.join(", ") ||
		selectedStrategy.config_data?.symbol ||
		"N/A";
	const displayName = selectedStrategy.name;

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
							id: selectedStrategy.id,
						})}
					</CardDescription>
				</div>
				<Button variant="ghost" size="icon" onClick={onClose}>
					<XIcon className="h-5 w-5" />
				</Button>
			</CardHeader>
			<CardContent>
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
						<StrategyOverviewTab strategy={selectedStrategy} />
					</TabsContent>

					<TabsContent value="trade-history" className="pt-4">
						<StrategyTradeHistoryTab strategyId={selectedStrategy.id} />
					</TabsContent>
				</Tabs>
			</CardContent>
		</Card>
	);
};
