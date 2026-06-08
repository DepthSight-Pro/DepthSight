// src/pages/admin/PlatformHealthPage.tsx

import {
	Activity,
	AlertCircle,
	CheckCircle2,
	Clock,
	Database,
	Server,
} from "lucide-react";
import type React from "react";
import { Badge } from "@/components/ui/badge";
import {
	Card,
	CardContent,
	CardDescription,
	CardHeader,
	CardTitle,
} from "@/components/ui/card";
import { Spinner } from "@/components/ui/Spinner";
import {
	useAdminErrorLogs,
	useAdminSystemMetrics,
	useSystemStatus,
} from "@/lib/api";

const PlatformHealthPage: React.FC = () => {
	const { data: systemStatus, isLoading: isLoadingStatus } = useSystemStatus();
	const { data: systemMetrics, isLoading: isLoadingMetrics } =
		useAdminSystemMetrics();
	const { data: errorLogs, isLoading: isLoadingErrors } = useAdminErrorLogs(5);

	const componentDetails: {
		[key: string]: { description: string; icon: React.ReactNode };
	} = {
		"API Server": {
			description: "Main API server responding normally",
			icon: <Server className="h-5 w-5" />,
		},
		Database: {
			description: "Database queries executing normally",
			icon: <Database className="h-5 w-5" />,
		},
		"Task Queue": {
			description: "Background tasks processing normally",
			icon: <Activity className="h-5 w-5" />,
		},
		Authentication: {
			description: "Auth system functioning properly",
			icon: <CheckCircle2 className="h-5 w-5" />,
		},
		binance_spot_ws: {
			description: "Real-time data feed for Spot markets",
			icon: <Activity className="h-5 w-5" />,
		},
		binance_futures_ws: {
			description: "Real-time data feed for Futures markets",
			icon: <Activity className="h-5 w-5" />,
		},
		database_connection: {
			description: "Connection to the primary database",
			icon: <Database className="h-5 w-5" />,
		},
		task_queue_connection: {
			description: "Connection to the background task queue",
			icon: <Activity className="h-5 w-5" />,
		},
	};

	const healthChecks =
		systemStatus?.components.map((component) => ({
			name: component.name,
			status: component.status.toLowerCase(),
			responseTime: "N/A", // This data is not available from the current endpoint
			description:
				componentDetails[component.name]?.description ||
				"No description available",
			icon: componentDetails[component.name]?.icon || (
				<Activity className="h-5 w-5" />
			),
		})) || [];

	const getStatusBadge = (status: string) => {
		switch (status) {
			case "operational":
			case "ok":
			case "connected":
				return (
					<Badge className="bg-green-500 hover:bg-green-600">Operational</Badge>
				);
			case "degraded":
				return (
					<Badge className="bg-yellow-500 hover:bg-yellow-600">Degraded</Badge>
				);
			case "down":
			case "error":
				return <Badge variant="destructive">Down</Badge>;
			default:
				return <Badge variant="outline">Unknown</Badge>;
		}
	};

	const getStatusIcon = (status: string) => {
		switch (status) {
			case "operational":
			case "ok":
			case "connected":
				return <CheckCircle2 className="h-8 w-8 text-green-500" />;
			case "degraded":
				return <AlertCircle className="h-8 w-8 text-yellow-500" />;
			case "down":
			case "error":
				return <AlertCircle className="h-8 w-8 text-red-500" />;
			default:
				return <Activity className="h-8 w-8 text-gray-500" />;
		}
	};

	const overallStatus = systemStatus?.status.toLowerCase() || "unknown";

	if (isLoadingStatus) {
		return (
			<div className="flex items-center justify-center h-96">
				<Spinner size="lg" />
			</div>
		);
	}

	return (
		<div className="space-y-6">
			<div>
				<h1 className="text-3xl font-bold mb-2">Platform Health</h1>
				<p className="text-muted-foreground">
					Monitor system status and performance
				</p>
			</div>

			<Card className="border-2">
				<CardHeader>
					<div className="flex items-center justify-between">
						<div className="flex items-center gap-4">
							{getStatusIcon(overallStatus)}
							<div>
								<CardTitle className="text-2xl">System Status</CardTitle>
								<CardDescription>All systems {overallStatus}</CardDescription>
							</div>
						</div>
						{getStatusBadge(overallStatus)}
					</div>
				</CardHeader>
			</Card>

			<div className="grid gap-4 md:grid-cols-2">
				{healthChecks.map((check) => (
					<Card key={check.name}>
						<CardHeader>
							<div className="flex items-center justify-between">
								<div className="flex items-center gap-3">
									<div className="p-2 rounded-lg bg-muted">{check.icon}</div>
									<div>
										<CardTitle className="text-lg">{check.name}</CardTitle>
										<CardDescription className="text-xs">
											{check.description}
										</CardDescription>
									</div>
								</div>
								{getStatusBadge(check.status)}
							</div>
						</CardHeader>
						<CardContent>
							<div className="flex items-center gap-2 text-sm text-muted-foreground">
								<Clock className="h-4 w-4" />
								<span>Response time: {check.responseTime}</span>
							</div>
						</CardContent>
					</Card>
				))}
			</div>

			<Card>
				<CardHeader>
					<CardTitle>System Metrics</CardTitle>
					<CardDescription>
						Performance and resource utilization
					</CardDescription>
				</CardHeader>
				<CardContent>
					{isLoadingMetrics ? (
						<div className="flex items-center justify-center h-40">
							<Spinner />
						</div>
					) : systemMetrics ? (
						<div className="space-y-4">
							<div className="flex justify-between items-center py-3 border-b">
								<span className="text-sm font-medium">
									Average Response Time
								</span>
								<span className="text-sm text-muted-foreground">
									{systemMetrics.average_response_time_ms.toFixed(0)}ms
								</span>
							</div>
							<div className="flex justify-between items-center py-3 border-b">
								<span className="text-sm font-medium">Uptime (30 days)</span>
								<span className="text-sm text-green-600 font-medium">
									{systemMetrics.uptime_30_days_percent.toFixed(2)}%
								</span>
							</div>
							<div className="flex justify-between items-center py-3 border-b">
								<span className="text-sm font-medium">
									Total Requests (24h)
								</span>
								<span className="text-sm text-muted-foreground">
									{systemMetrics.total_requests_24h.toLocaleString()}
								</span>
							</div>
							<div className="flex justify-between items-center py-3">
								<span className="text-sm font-medium">Error Rate (24h)</span>
								<span className="text-sm text-muted-foreground">
									{systemMetrics.error_rate_24h.toFixed(2)}%
								</span>
							</div>
						</div>
					) : (
						<div className="text-center py-12">
							<p className="text-muted-foreground">
								Could not load system metrics.
							</p>
						</div>
					)}
				</CardContent>
			</Card>

			<Card>
				<CardHeader>
					<CardTitle>Recent Incidents</CardTitle>
					<CardDescription>System incidents and maintenance</CardDescription>
				</CardHeader>
				<CardContent>
					{isLoadingErrors ? (
						<div className="flex items-center justify-center h-40">
							<Spinner />
						</div>
					) : errorLogs && errorLogs.length > 0 ? (
						<div className="space-y-4">
							{errorLogs.map((log) => (
								<div key={log.id} className="flex items-start gap-4">
									<AlertCircle className="h-5 w-5 text-red-500 mt-1" />
									<div>
										<p className="text-sm font-medium">{log.message}</p>
										<p className="text-xs text-muted-foreground">
											{new Date(log.timestamp).toLocaleString()} -{" "}
											{log.component}
										</p>
									</div>
								</div>
							))}
						</div>
					) : (
						<div className="text-center py-8">
							<CheckCircle2 className="h-12 w-12 text-green-500 mx-auto mb-3" />
							<p className="text-sm text-muted-foreground">
								No recent incidents
							</p>
							<p className="text-xs text-muted-foreground mt-1">
								All systems have been operational for the last 30 days
							</p>
						</div>
					)}
				</CardContent>
			</Card>
		</div>
	);
};

export default PlatformHealthPage;
