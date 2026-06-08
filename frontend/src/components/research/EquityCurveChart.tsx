// src/components/research/EquityCurveChart.tsx

import { format } from "date-fns";
import { enUS, ru } from "date-fns/locale";
import { AlertCircle, LineChart } from "lucide-react";
import type React from "react";
import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import {
	Area,
	AreaChart,
	CartesianGrid,
	ResponsiveContainer,
	Tooltip,
	XAxis,
	YAxis,
} from "recharts";
import type { BacktestRunDetailsData } from "@/types/api"; // Import is needed for the status type
import { Alert, AlertDescription, AlertTitle } from "../ui/alert";

// --- Create a simple, local type for props ---
// This type describes the minimum set of data required for the component to work.
type EquityCurveChartRunData = {
	status?: BacktestRunDetailsData["status"]; // 'COMPLETED', 'RUNNING', etc.
	equity_curve_json?: [number | string, number][];
	portfolio_equity_curve_json?: [number | string, number][];
};

interface EquityCurveChartProps {
	run: Partial<EquityCurveChartRunData>; // Use Partial to make all fields optional
	isPortfolio?: boolean;
	isSingleDay?: boolean; // If true, hours are displayed on the X axis instead of dates
}

export const EquityCurveChart: React.FC<EquityCurveChartProps> = ({
	run,
	isPortfolio,
	isSingleDay,
}) => {
	const { t, i18n } = useTranslation(["research", "common"]);
	const currentLocale = i18n.language;

	const equityCurveJson = useMemo(() => {
		if (isPortfolio && run && "portfolio_equity_curve_json" in run) {
			return run.portfolio_equity_curve_json;
		}
		if (run && "equity_curve_json" in run) {
			return run.equity_curve_json;
		}
		return undefined;
	}, [run, isPortfolio]);

	const status = run.status;

	const chartData = useMemo(() => {
		const sourceData = equityCurveJson || [];
		if (!sourceData || sourceData.length === 0) return [];

		return sourceData
			.map(([timestamp, value]) => {
				const parsedTimestamp =
					typeof timestamp === "string"
						? Date.parse(timestamp)
						: Number(timestamp);
				return {
					date: parsedTimestamp,
					equity: Number(value),
				};
			})
			.filter(
				({ date, equity }) => !Number.isNaN(date) && !Number.isNaN(equity),
			)
			.map(({ date, equity }) => ({
				date, // Keep as number for XAxis scale="time"
				equity,
			}));
	}, [equityCurveJson]);

	const renderContent = () => {
		if (status === "FAILED") {
			return (
				<div className="flex items-center justify-center h-full">
					<Alert variant="destructive" className="w-auto">
						<AlertCircle className="h-4 w-4" />
						<AlertTitle>{t("equityCurve.taskFailedTitle")}</AlertTitle>
						<AlertDescription>{t("equityCurve.noResults")}</AlertDescription>
					</Alert>
				</div>
			);
		}

		if (chartData.length > 0) {
			const dateFnsLocale = currentLocale.startsWith("ru") ? ru : enUS;
			return (
				<ResponsiveContainer width="100%" height={350}>
					<AreaChart data={chartData}>
						<defs>
							<linearGradient id="equityGradient" x1="0" y1="0" x2="0" y2="1">
								<stop
									offset="5%"
									stopColor="hsl(var(--primary))"
									stopOpacity={0.4}
								/>
								<stop
									offset="95%"
									stopColor="hsl(var(--primary))"
									stopOpacity={0}
								/>
							</linearGradient>
						</defs>
						<CartesianGrid
							strokeDasharray="3 3"
							stroke="hsl(var(--border) / 0.5)"
						/>
						<XAxis
							dataKey="date"
							type="number"
							domain={["dataMin", "dataMax"]}
							scale="time"
							stroke="hsl(var(--muted-foreground))"
							fontSize={12}
							tickLine={false}
							axisLine={false}
							tickFormatter={(unixTime) => {
								try {
									return format(
										new Date(unixTime),
										isSingleDay ? "HH:mm" : "MMM dd",
										{ locale: dateFnsLocale },
									);
								} catch {
									return "";
								}
							}}
						/>
						<YAxis
							stroke="hsl(var(--muted-foreground))"
							fontSize={12}
							tickLine={false}
							axisLine={false}
							tickFormatter={(value) => `$${(value / 1000).toFixed(0)}k`}
							domain={["auto", "auto"]}
						/>
						<Tooltip
							contentStyle={{
								background: "hsl(var(--card))",
								borderColor: "hsl(var(--border))",
								borderRadius: "var(--radius)",
							}}
							labelFormatter={(label) => {
								try {
									return format(new Date(label), "PPP", {
										locale: dateFnsLocale,
									});
								} catch {
									return "";
								}
							}}
							formatter={(value: unknown) => [
								Number(value ?? 0).toLocaleString(currentLocale, {
									style: "currency",
									currency: "USD",
								}),
								t("equityCurve.tooltipLabel"),
							]}
						/>
						<Area
							type="monotone"
							dataKey="equity"
							name={t("equityCurve.tooltipLabel")}
							stroke="hsl(var(--primary))"
							fillOpacity={1}
							fill="url(#equityGradient)"
							isAnimationActive={status !== "RUNNING"}
						/>
					</AreaChart>
				</ResponsiveContainer>
			);
		}

		return (
			<div className="flex flex-col items-center justify-center h-[350px] text-muted-foreground">
				<LineChart className="w-12 h-12 mb-4 text-primary/30" />
				<p>{t("equityCurve.waitingForData")}</p>
			</div>
		);
	};

	return <div className="min-h-[350px]">{renderContent()}</div>;
};
