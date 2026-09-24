import { formatDistanceToNow } from "date-fns";
import { enUS, ru } from "date-fns/locale";
import { AlertTriangle, TrendingUp } from "lucide-react";
import type React from "react";
import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import {
	Card,
	CardContent,
	CardDescription,
	CardHeader,
	CardTitle,
} from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import {
	Table,
	TableBody,
	TableCell,
	TableHead,
	TableHeader,
	TableRow,
} from "@/components/ui/table";
import { usePortfolioMode } from "@/context/PortfolioModeContext";
import { useStrategies } from "@/lib/api";

const getStatusBadgeVariant = (status: string) => {
	switch (status.toLowerCase()) {
		case "running":
		case "active":
		case "in_position":
		case "in-position":
			return "bg-green-500 hover:bg-green-600";
		case "stopped":
		case "paused":
			return "bg-yellow-500 hover:bg-yellow-600";
		case "error":
			return "bg-red-500 hover:bg-red-600";
		default:
			return "bg-gray-500 hover:bg-gray-600";
	}
};

const isActiveStrategy = (s: { status?: string; open_positions?: number | null }) => {
	const st = String(s.status || "").toLowerCase();
	if (
		st === "running" ||
		st === "active" ||
		st === "in_position" ||
		st === "in-position"
	)
		return true;
	return Number(s.open_positions ?? 0) > 0;
};

import { ExchangeBadge } from "@/components/layout/AccountSelector";
import { useAccountStore } from "@/stores/accountStore";

export const TopStrategiesTable: React.FC<{ topN?: number }> = ({
	topN = 5,
}) => {
	const { mode } = usePortfolioMode();
	const { selectedApiKeyId } = useAccountStore();
	const { t, i18n } = useTranslation(["index", "common"]);
	const {
		data: strategies,
		isLoading,
		isError,
		error,
	} = useStrategies({
		mode,
		apiKeyId: mode === "live" ? selectedApiKeyId : undefined,
	});
	const navigate = useNavigate();

	const dateFnsLocale = useMemo(() => {
		const lang = i18n.language.split("-")[0];
		if (lang === "ru") return ru;
		return enUS;
	}, [i18n.language]);

	// Active now (running/active/in_position or open_positions>0), sorted by PnL,
	// then top by PnL across all (active first so a fresh 0-PnL bot never vanishes).
	const { runningNow, topStrategies } = useMemo(() => {
		if (!strategies) return { runningNow: [], topStrategies: [] };
		const running = [...strategies]
			.filter(isActiveStrategy)
			.sort((a, b) => (b.pnl || 0) - (a.pnl || 0));
		const top = [...strategies]
			.sort((a, b) => {
				const aActive = isActiveStrategy(a) ? 0 : 1;
				const bActive = isActiveStrategy(b) ? 0 : 1;
				if (aActive !== bActive) return aActive - bActive;
				return (b.pnl || 0) - (a.pnl || 0);
			})
			.slice(0, topN);
		return { runningNow: running, topStrategies: top };
	}, [strategies, topN]);

	const handleRowClick = (strategyId: string) => {
		navigate(`/strategies?id=${encodeURIComponent(strategyId)}`);
	};

	const calculateRuntime = (startTime: string): string => {
		try {
			return formatDistanceToNow(new Date(startTime), {
				addSuffix: true,
				locale: dateFnsLocale,
			});
		} catch {
			return t("common:na");
		}
	};

	if (isError) {
		return (
			<Alert variant="destructive" className="my-4">
				<AlertTriangle className="h-4 w-4" />
				<AlertTitle>{t("index:topStrategies.errors.loadFailed")}</AlertTitle>
				<AlertDescription>
					{error?.message || t("common:errors.unknownError")}
				</AlertDescription>
			</Alert>
		);
	}

	return (
		<Card>
			<CardHeader>
				<CardTitle className="flex items-center">
					<TrendingUp className="w-5 h-5 mr-2 text-primary" />
					{t("index:topStrategies.title")}
				</CardTitle>
				<CardDescription>
					{t("index:topStrategies.description")}
				</CardDescription>
			</CardHeader>
			<CardContent className="space-y-4">
				{isLoading ? (
					<Table>
						<TableBody>
							{[...Array(topN)].map((_, i) => (
								<TableRow key={`skeleton-${i}`}>
									<TableCell colSpan={5}>
										<Skeleton className="h-8 w-full" />
									</TableCell>
								</TableRow>
							))}
						</TableBody>
					</Table>
				) : (
					<>
						{runningNow.length > 0 && (
							<div>
								<div className="mb-2 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
									{t("index:topStrategies.runningNow", "Running now")}
								</div>
								<Table>
									<TableBody>
										{runningNow.map((strategy) => (
											<TableRow
												key={`running-${strategy.id}`}
												onClick={() => handleRowClick(strategy.id)}
												className="cursor-pointer hover:bg-muted/50"
											>
												<TableCell className="font-medium">
													<span className="flex items-center gap-2">
														<ExchangeBadge
															exchange={strategy.exchange}
															size="xs"
														/>
														{strategy.name || strategy.strategy_name}
													</span>
												</TableCell>
												<TableCell className="font-mono text-sm">
													{strategy.symbol}
												</TableCell>
												<TableCell className="text-center">
													<Badge
														className={getStatusBadgeVariant(strategy.status)}
													>
														{strategy.status.toUpperCase()}
													</Badge>
												</TableCell>
												<TableCell
													className={`text-right font-medium mono ${strategy.pnl >= 0 ? "text-profit" : "text-loss"}`}
												>
													{strategy.pnl >= 0 ? "+" : ""}
													{strategy.pnl.toFixed(2)}
												</TableCell>
												<TableCell className="text-right text-sm text-muted-foreground">
													{calculateRuntime(strategy.started_at)}
												</TableCell>
											</TableRow>
										))}
									</TableBody>
								</Table>
							</div>
						)}
						<div>
							<div className="mb-2 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
								{t("index:topStrategies.topByPnl", "Top by PnL")}
							</div>
							<Table>
								<TableHeader>
									<TableRow>
										<TableHead>{t("index:topStrategies.colName")}</TableHead>
										<TableHead>{t("index:topStrategies.colSymbol")}</TableHead>
										<TableHead className="text-center">
											{t("index:topStrategies.colStatus")}
										</TableHead>
										<TableHead className="text-right">
											{t("index:topStrategies.colPnl")}
										</TableHead>
										<TableHead className="text-right">
											{t("index:topStrategies.colRuntime")}
										</TableHead>
									</TableRow>
								</TableHeader>
								<TableBody>
									{topStrategies.length === 0 ? (
										<TableRow>
											<TableCell
												colSpan={5}
												className="h-24 text-center text-muted-foreground"
											>
												{t("index:topStrategies.noData")}
											</TableCell>
										</TableRow>
									) : (
										topStrategies.map((strategy) => (
											<TableRow
												key={strategy.id}
												onClick={() => handleRowClick(strategy.id)}
												className="cursor-pointer hover:bg-muted/50"
											>
												<TableCell className="font-medium">
													<span className="flex items-center gap-2">
														<ExchangeBadge
															exchange={strategy.exchange}
															size="xs"
														/>
														{strategy.name || strategy.strategy_name}
													</span>
												</TableCell>
												<TableCell className="font-mono text-sm">
													{strategy.symbol}
												</TableCell>
												<TableCell className="text-center">
													<Badge
														className={getStatusBadgeVariant(strategy.status)}
													>
														{strategy.status.toUpperCase()}
													</Badge>
												</TableCell>
												<TableCell
													className={`text-right font-medium mono ${strategy.pnl >= 0 ? "text-profit" : "text-loss"}`}
												>
													{strategy.pnl >= 0 ? "+" : ""}
													{strategy.pnl.toFixed(2)}
												</TableCell>
												<TableCell className="text-right text-sm text-muted-foreground">
													{calculateRuntime(strategy.started_at)}
												</TableCell>
											</TableRow>
										))
									)}
								</TableBody>
							</Table>
						</div>
					</>
				)}
			</CardContent>
		</Card>
	);
};
