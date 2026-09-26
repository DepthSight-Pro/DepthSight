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

interface CustomEquityTooltipProps {
	active?: boolean;
	payload?: Array<{ value?: unknown; payload?: { time: number; equity: number } }>;
	label?: string | number;
	tooltipLabelText: string;
	dateFnsLocale: typeof ru | typeof enUS;
	currentLocale: string;
	isSingleDay?: boolean;
}

const CustomEquityTooltip = ({
	active,
	payload,
	label,
	tooltipLabelText,
	dateFnsLocale,
	currentLocale,
	isSingleDay,
}: CustomEquityTooltipProps) => {
	if (!active || !payload?.length) return null;
	const equity = Number(payload[0].value ?? 0);
	let formattedDate = "";
	try {
		const d = new Date(label as number);
		formattedDate = format(d, isSingleDay ? "PPP HH:mm" : "PPP", {
			locale: dateFnsLocale,
		});
	} catch {
		formattedDate = String(label);
	}

	return (
		<div className="rounded-xl border border-border dark:border-white/15 bg-card/95 dark:bg-[#0b0f17]/95 px-3.5 py-2.5 shadow-2xl backdrop-blur-xl text-card-foreground">
			<div className="text-[11px] font-medium text-muted-foreground dark:text-slate-300 mb-1">{formattedDate}</div>
			<div className="flex items-center gap-2">
				<span className="w-2 h-2 rounded-full bg-cyan-500 dark:bg-cyan-400 shrink-0 shadow-[0_0_8px_rgba(6,182,212,0.5)]" />
				<span className="text-xs text-foreground/80 dark:text-slate-200">{tooltipLabelText}:</span>
				<span className="text-sm font-semibold font-mono text-cyan-600 dark:text-cyan-300">
					{equity.toLocaleString(currentLocale, {
						style: "currency",
						currency: "USD",
					})}
				</span>
			</div>
		</div>
	);
};

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
							content={
								<CustomEquityTooltip
									tooltipLabelText={t("equityCurve.tooltipLabel")}
									dateFnsLocale={dateFnsLocale}
									currentLocale={currentLocale}
									isSingleDay={isSingleDay}
								/>
							}
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
