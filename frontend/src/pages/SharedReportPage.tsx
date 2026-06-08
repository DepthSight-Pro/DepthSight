// src/pages/SharedReportPage.tsx

import { format, parseISO } from "date-fns";
import { enUS, ru } from "date-fns/locale";
import { AlertCircle, LineChart, UploadCloud } from "lucide-react";
import { Helmet } from "react-helmet-async";
import { useTranslation } from "react-i18next";
import { Link, useLocation, useNavigate, useParams } from "react-router-dom";
import { EquityCurveChart } from "@/components/research/EquityCurveChart";
import { AppLoader } from "@/components/shared/AppLoader";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import {
	Card,
	CardContent,
	CardDescription,
	CardHeader,
	CardTitle,
} from "@/components/ui/card";
import { Logo } from "@/components/ui/logo";
import { useToast } from "@/components/ui/use-toast";
import { useSharedBacktestData } from "@/lib/api";
import { useStrategyEditorStore } from "@/stores/strategyEditorStore";

const KpiCard = ({
	title,
	value,
	prefix = "",
	suffix = "",
	valueColor,
}: {
	title: string;
	value: string | number;
	prefix?: string;
	suffix?: string;
	valueColor?: string;
}) => (
	<Card>
		<CardHeader className="pb-2">
			<CardTitle className="text-sm font-medium text-muted-foreground">
				{title}
			</CardTitle>
		</CardHeader>
		<CardContent>
			<div className={`text-3xl font-bold ${valueColor}`}>
				{prefix}
				{value}
				{suffix}
			</div>
		</CardContent>
	</Card>
);

const getSharedStrategyDisplayName = (data: {
	strategyName: string;
	parameters?: Record<string, unknown>;
	strategyConfig?: unknown;
}): string => {
	const params = data.parameters;
	const config = data.strategyConfig as Record<string, unknown> | undefined;
	return (
		(params?.name as string) ||
		(params?.strategy_display_name as string) ||
		(config?.name as string) ||
		data.strategyName
	);
};

const SharedReportPage = () => {
	const { publicSlug } = useParams<{ publicSlug: string }>();
	const location = useLocation();
	const navigate = useNavigate();
	const { toast } = useToast();
	const { loadStrategy } = useStrategyEditorStore();
	const { t, i18n } = useTranslation();
	const { data, isLoading, isError, error } = useSharedBacktestData(
		publicSlug!,
	);

	const handleLoadInEditor = () => {
		if (data?.strategyConfig) {
			const newName =
				(data.strategyConfig as { name?: string }).name ||
				getSharedStrategyDisplayName(
					data as {
						strategyName: string;
						parameters?: Record<string, unknown>;
						strategyConfig?: unknown;
					},
				);
			const configToLoad = {
				...data.strategyConfig,
				name: newName.includes("(from Share)")
					? newName
					: `${newName} (from Share)`,
			};
			loadStrategy(configToLoad);
			toast({
				title: t("common:strategyLoadedTitle"),
				description: t("common:strategyLoadedDescription"),
			});
			navigate("/editor");
		} else {
			toast({
				title: t("common:strategyConfigUnavailableTitle"),
				description: t("common:strategyConfigUnavailableDescription"),
				variant: "destructive",
			});
		}
	};

	const dateFnsLocale = i18n.language.startsWith("ru") ? ru : enUS;

	const canonicalUrl = `${window.location.origin}${location.pathname}`;

	// 2. Generate ABSOLUTE URL for the image.
	const imageUrl = `${window.location.origin}/og-image/${publicSlug}.png`;

	if (isLoading) {
		return (
			<div className="flex flex-col items-center justify-center h-screen bg-background">
				<AppLoader size="xl" fullLogo text="Loading report..." />
			</div>
		);
	}

	if (isError) {
		return (
			<div className="flex h-screen items-center justify-center p-4 bg-background">
				<Alert variant="destructive" className="max-w-lg">
					<AlertCircle className="h-4 w-4" />
					<AlertTitle>Error loading report</AlertTitle>
					<AlertDescription>
						{error?.message ||
							"The requested report was not found or is no longer available."}
					</AlertDescription>
					<div className="mt-4">
						<Button asChild>
							<Link to="/">To home</Link>
						</Button>
					</div>
				</Alert>
			</div>
		);
	}

	if (!data) {
		return null;
	}

	const runDataForChart = {
		status: "COMPLETED" as const,
		equity_curve_json: data.equityCurve,
	};

	const formattedPeriod = `${format(parseISO(data.period.start), "dd MMM yyyy", { locale: dateFnsLocale })} - ${format(parseISO(data.period.end), "dd MMM yyyy", { locale: dateFnsLocale })}`;

	const strategyDisplayName = getSharedStrategyDisplayName(data);
	const metaTitle = `Backtest report: ${strategyDisplayName}`;
	const metaDescription = `Strategy on ${data.symbol} showed ${data.kpis.total_pnl >= 0 ? "+" : ""}${(data.kpis.total_pnl ?? 0).toFixed(2)} PNL. Period: ${formattedPeriod}.`;

	return (
		<>
			<Helmet>
				<title>{metaTitle}</title>
				<meta name="description" content={metaDescription} />
				<meta property="og:title" content={metaTitle} />
				<meta property="og:description" content={metaDescription} />
				<meta property="og:url" content={canonicalUrl} />
				<meta property="og:image" content={imageUrl} />
				<meta property="og:image:width" content="1200" />
				<meta property="og:image:height" content="630" />
				<meta property="og:type" content="website" />
				<meta name="twitter:card" content="summary_large_image" />
				<meta name="twitter:title" content={metaTitle} />
				<meta name="twitter:description" content={metaDescription} />
				<meta name="twitter:image" content={imageUrl} />
			</Helmet>

			<header className="sticky top-0 z-50 w-full border-b bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60">
				<div className="container mx-auto flex h-20 max-w-5xl items-center justify-between">
					<Link to="/" className="flex items-center gap-2">
						<Logo className="h-12" />
					</Link>
					<Button asChild>
						<Link to="/register">Start for free</Link>
					</Button>
				</div>
			</header>

			<main className="flex-grow container mx-auto max-w-5xl py-8 md:py-12 px-4">
				<div className="mb-8 text-center">
					<h2 className="text-3xl font-bold tracking-tight sm:text-4xl">
						{strategyDisplayName}
					</h2>
					<p className="mt-2 text-lg text-muted-foreground">
						{data.symbol} | {formattedPeriod}
					</p>
				</div>

				<div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4 mb-8">
					<KpiCard
						title="Net profit"
						value={data.kpis.total_pnl?.toFixed(2) ?? "N/A"}
						prefix={data.kpis.total_pnl >= 0 ? "+$" : "-$"}
						suffix=""
						valueColor={data.kpis.total_pnl >= 0 ? "text-profit" : "text-loss"}
					/>
					<KpiCard
						title="% Profitable"
						value={data.kpis.win_rate?.toFixed(1) ?? "N/A"}
						suffix="%"
					/>
					<KpiCard
						title="Max drawdown"
						value={data.kpis.max_drawdown?.toFixed(2) ?? "N/A"}
						suffix="%"
						valueColor="text-loss"
					/>
					<KpiCard
						title="Total trades"
						value={data.kpis.trades?.toString() ?? "N/A"}
					/>
				</div>

				<Card id="equity" className="mb-8">
					<CardHeader>
						<CardTitle>Equity curve</CardTitle>
						<CardDescription>
							Equity dynamics as the backtest progresses.
						</CardDescription>
					</CardHeader>
					<CardContent>
						<EquityCurveChart run={runDataForChart} />
					</CardContent>
				</Card>

				{data.parameters && (
					<Card id="config" className="mb-8">
						<CardHeader>
							<div className="flex justify-between items-center">
								<CardTitle>Strategy configuration</CardTitle>
								{data.strategyConfig && (
									<Button
										onClick={handleLoadInEditor}
										variant="outline"
										size="sm"
									>
										<UploadCloud className="mr-2 h-4 w-4" />
										Load into editor
									</Button>
								)}
							</div>
							<CardDescription>
								JSON configuration that can be loaded into the editor.
							</CardDescription>
						</CardHeader>
						<CardContent>
							<pre className="p-4 bg-muted rounded-md text-sm overflow-x-auto">
								{JSON.stringify(
									data.strategyConfig || data.parameters,
									null,
									2,
								)}
							</pre>
						</CardContent>
					</Card>
				)}
			</main>

			<footer className="py-16 bg-muted/40">
				<div className="container mx-auto max-w-5xl text-center">
					<LineChart className="mx-auto h-12 w-12 text-primary mb-4" />
					<h3 className="text-3xl font-bold mb-2">
						Ready to create your strategy?
					</h3>
					<p className="text-muted-foreground mb-6 max-w-2xl mx-auto">
						Join DepthSight and start testing your ideas in minutes, not weeks.
						For free.
					</p>
					<Button asChild size="lg">
						<Link to="/register">Create a free account</Link>
					</Button>
				</div>
			</footer>
		</>
	);
};

export default SharedReportPage;
