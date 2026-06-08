// src/components/strategies/StrategyOverviewTab.tsx

import { formatDistanceToNowStrict } from "date-fns";
import { enUS, type Locale, ru } from "date-fns/locale";
import { useTranslation } from "react-i18next";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { StrategyConfig, StrategyData } from "@/types/api";

interface StatDisplayProps {
	label: string;
	value: string | number | React.ReactNode;
	className?: string;
}

const StatDisplay: React.FC<StatDisplayProps> = ({
	label,
	value,
	className,
}) => (
	<div className={className}>
		<p className="text-sm font-medium text-muted-foreground">{label}</p>
		<div className="text-lg font-semibold">{value}</div>
	</div>
);

const getStatusBadge = (status: string) => {
	status = status.toLowerCase();
	let className = "bg-gray-500 hover:bg-gray-600";
	if (status === "running" || status === "active")
		className = "bg-green-500 hover:bg-green-600 text-white";
	else if (status === "stopped" || status === "paused")
		className = "bg-yellow-500 hover:bg-yellow-600 text-gray-800";
	else if (status === "error" || status === "failed")
		className = "bg-red-500 hover:bg-red-600 text-white";
	return <Badge className={className}>{status.toUpperCase()}</Badge>;
};

const calculateRuntime = (
	startTime: string | undefined,
	locale: Locale,
): string => {
	if (!startTime) return "N/A";
	try {
		return formatDistanceToNowStrict(new Date(startTime), {
			addSuffix: true,
			locale,
		});
	} catch {
		return "N/A";
	}
};

interface StrategyOverviewTabProps {
	strategy: StrategyData & Partial<StrategyConfig>;
}

export const StrategyOverviewTab: React.FC<StrategyOverviewTabProps> = ({
	strategy,
}) => {
	const { t, i18n } = useTranslation("strategies");
	const dateFnsLocale = i18n.language.startsWith("ru") ? ru : enUS;

	const displaySymbols =
		strategy.symbols?.join(", ") || strategy.config_data?.symbol || "N/A";
	const marketType =
		((strategy as unknown as Record<string, unknown>).market_type as string) ||
		strategy.config_data?.marketType ||
		"N/A";
	const params =
		(strategy.config_data as Record<string, unknown> | undefined)?.params ||
		strategy.params ||
		{};
	const strategyName =
		strategy.config_data?.strategy_name ||
		((strategy as unknown as Record<string, unknown>)
			.strategy_name as string) ||
		t("overviewTab.unknownStrategy");

	return (
		<div>
			<div className="grid grid-cols-2 md:grid-cols-3 gap-4 mb-6">
				<StatDisplay
					label={t("overviewTab.totalPnl")}
					value={`${strategy.pnl >= 0 ? "+" : ""}${strategy.pnl.toFixed(2)} USD`}
					className={strategy.pnl >= 0 ? "text-profit" : "text-loss"}
				/>
				<StatDisplay
					label={t("overviewTab.status")}
					value={getStatusBadge(strategy.status)}
				/>
				<StatDisplay
					label={t("overviewTab.strategyType")}
					value={strategyName}
				/>
				<StatDisplay label={t("overviewTab.symbol")} value={displaySymbols} />
				<StatDisplay label={t("overviewTab.marketType")} value={marketType} />
				<StatDisplay
					label={t("overviewTab.openPositions")}
					value={strategy.open_positions}
				/>
				<StatDisplay
					label={t("overviewTab.runningSince")}
					value={calculateRuntime(strategy.started_at, dateFnsLocale)}
				/>
			</div>

			<Card>
				<CardHeader>
					<CardTitle className="text-lg">
						{t("overviewTab.parametersTitle")}
					</CardTitle>
				</CardHeader>
				<CardContent>
					<pre className="text-xs bg-muted p-4 rounded-md whitespace-pre-wrap">
						{JSON.stringify(params, null, 2)}
					</pre>
				</CardContent>
			</Card>
		</div>
	);
};
