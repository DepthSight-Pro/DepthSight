// src/components/dashboard/SystemStatus.tsx

import { AlertTriangle, CheckCircle2, HelpCircle, XCircle } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import {
	Tooltip,
	TooltipContent,
	TooltipProvider,
	TooltipTrigger,
} from "@/components/ui/tooltip";
import { useSystemStatus } from "@/lib/api";
import { cn } from "@/lib/utils";

export function SystemStatus() {
	const { t } = useTranslation(["index", "common"]);
	const { data: systemData, isLoading, isError, error } = useSystemStatus();

	const getStatusInfo = (
		status: string,
	): { icon: React.ReactNode; color: string; label: string } => {
		switch (status?.toLowerCase()) {
			case "connected":
			case "ok":
			case "active":
				return {
					icon: <CheckCircle2 className="h-4 w-4" />,
					color: "text-profit",
					label: t("index:systemHealth.status.ok"),
				};
			case "error":
			case "failed":
			case "disconnected":
				return {
					icon: <XCircle className="h-4 w-4" />,
					color: "text-loss",
					label: t("index:systemHealth.status.error"),
				};
			default:
				return {
					icon: <HelpCircle className="h-4 w-4" />,
					color: "text-warning",
					label: t("index:systemHealth.status.unknown"),
				};
		}
	};

	return (
		<TooltipProvider>
			<Card className="h-full flex flex-col">
				<CardHeader className="pb-3">
					<CardTitle className="text-base font-medium text-foreground">
						{t("index:systemHealth.title")}
					</CardTitle>
				</CardHeader>
				<CardContent className="flex-grow">
					{isLoading && (
						<div className="space-y-4">
							{[...Array(3)].map((_, i) => (
								<Skeleton key={i} className="h-5 w-full" />
							))}
						</div>
					)}
					{isError && !isLoading && (
						<Alert variant="destructive" className="mt-2">
							<AlertTriangle className="h-4 w-4" />
							<AlertTitle>{t("common:errorTitle")}</AlertTitle>
							<AlertDescription>
								{error?.message ||
									t("index:systemHealth.failedToLoadSystemStatus")}
							</AlertDescription>
						</Alert>
					)}
					{!isLoading &&
						!isError &&
						systemData?.components &&
						systemData.components.length > 0 && (
							<div className="space-y-2">
								{systemData.components.map((component) => {
									const statusInfo = getStatusInfo(component.status);
									return (
										<Tooltip key={component.name} delayDuration={100}>
											<TooltipTrigger asChild>
												<div className="flex items-center justify-between text-sm p-2 rounded-md hover:bg-muted/50 transition-colors">
													<span className="text-muted-foreground">
														{t(
															`index:systemHealth.components.${component.name}`,
															component.name,
														)}
													</span>
													<div
														className={cn(
															"flex items-center space-x-2",
															statusInfo.color,
														)}
													>
														{statusInfo.icon}
														<span className="font-semibold text-xs uppercase">
															{statusInfo.label}
														</span>
													</div>
												</div>
											</TooltipTrigger>
											<TooltipContent>
												<p>
													{t("index:systemHealth.componentStatus", {
														component: component.name,
														status: component.status,
													})}
												</p>
												{component.message && (
													<p className="text-xs text-muted-foreground">
														{component.message}
													</p>
												)}
											</TooltipContent>
										</Tooltip>
									);
								})}
							</div>
						)}
					{!isLoading &&
						!isError &&
						(!systemData?.components || systemData.components.length === 0) && (
							<p className="text-sm text-muted-foreground pt-2">
								{t("index:systemHealth.noSystemComponentsStatusAvailable")}
							</p>
						)}
				</CardContent>
			</Card>
		</TooltipProvider>
	);
}
