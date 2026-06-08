// src/pages/Research.tsx

import {
	AlertTriangle,
	ChevronLeft,
	ChevronRight,
	Eye,
	FlaskConical,
	ListTodo,
	Loader2,
	Trash2,
} from "lucide-react";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useSearchParams } from "react-router-dom";
import { PageLayout } from "@/components/layout/PageLayout";
import { LaunchTaskForm } from "@/components/research/LaunchTaskForm";
import { ConfirmationModal } from "@/components/shared/ConfirmationModal";
import { SimulationTab } from "@/components/simulation";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
	Card,
	CardContent,
	CardDescription,
	CardFooter,
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
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
	Tooltip,
	TooltipContent,
	TooltipTrigger,
} from "@/components/ui/tooltip";
import { useDeleteBacktestRun, useResearchTasks } from "@/lib/api";
import type { TaskData } from "@/types/api";

// Define our type for display
type DisplayedTaskItem = {
	id: string; // task_id
	run_id?: string; // for backtests, if needed
	name: string;
	task_type_key:
		| "backtest"
		| "optimization"
		| "portfolio"
		| "geneticSearch"
		| "unknown"; // For translation key
	task_type_display: string; // Translated display string
	symbol?: string;
	status: string;
	pnl?: number;
	fitness_score?: number;
	created_at: string;
};

// Stricter type for status
type TaskStatus =
	| "PENDING"
	| "RUNNING"
	| "SUCCESS"
	| "FAILURE"
	| "COMPLETED"
	| "STOPPED";

interface RequestParamsHelper {
	name?: string;
	strategy_display_name?: string;
	strategy_name?: string;
	symbol?: string;
	params?: {
		name?: string;
		strategy_display_name?: string;
		config?: {
			name?: string;
		};
	};
}

const getTaskDisplayName = (task: TaskData, fallback: string): string => {
	const params = task.request_params as RequestParamsHelper | undefined;
	return (
		params?.name ||
		params?.strategy_display_name ||
		params?.params?.name ||
		params?.params?.strategy_display_name ||
		params?.params?.config?.name ||
		params?.strategy_name ||
		fallback
	);
};

const GetStatusBadge = ({
	status,
	t,
}: {
	status: string;
	t: (key: string) => string;
}) => {
	const upperStatus = status.toUpperCase() as TaskStatus;
	switch (upperStatus) {
		case "COMPLETED":
		case "SUCCESS":
			return (
				<Badge variant="default" className="bg-green-500 hover:bg-green-600">
					{t("statuses.completed")}
				</Badge>
			);
		case "FAILURE":
			return <Badge variant="destructive">{t("statuses.failed")}</Badge>;
		case "PENDING":
			return <Badge variant="outline">{t("statuses.pending")}</Badge>;
		case "RUNNING":
			return (
				<Badge
					variant="secondary"
					className="animate-pulse border-blue-500 text-blue-500"
				>
					{t("statuses.running")}
				</Badge>
			);
		case "STOPPED":
			return (
				<Badge variant="default" className="bg-yellow-500 hover:bg-yellow-600">
					{t("statuses.stopped")}
				</Badge>
			);
		default:
			return <Badge variant="outline">{status}</Badge>;
	}
};

export default function Research() {
	const { t } = useTranslation(["research", "common"]);
	const [page, setPage] = useState(1);
	const pageSize = 15; // Tasks per page
	const [searchParams, setSearchParams] = useSearchParams();

	// Support for URL parameter ?tab=simulator for navigation from GA
	const [activeTab, setActiveTab] = useState(() => {
		const tabFromUrl = searchParams.get("tab");
		return tabFromUrl === "simulator" ? "simulator" : "tasks";
	});

	// Synchronize tab with URL on change
	const handleTabChange = (value: string) => {
		setActiveTab(value);
		if (value === "simulator") {
			setSearchParams({ tab: "simulator" });
		} else {
			setSearchParams({});
		}
	};

	const { data, isLoading, isError, error } = useResearchTasks(page, pageSize);
	const { mutate: deleteBacktestRun, isPending: isDeletingBacktest } =
		useDeleteBacktestRun();
	const [confirmModal, setConfirmModal] = useState<{
		open: boolean;
		title: string;
		description: string;
		onConfirm: () => void;
		isLoading: boolean;
		itemIdToActOn: string | null;
	}>({
		open: false,
		title: "",
		description: "",
		onConfirm: () => {},
		isLoading: false,
		itemIdToActOn: null,
	});

	const allRuns: DisplayedTaskItem[] = useMemo(() => {
		if (!data?.tasks) return [];
		return data.tasks
			.map((task: TaskData): DisplayedTaskItem => {
				let taskTypeKey: DisplayedTaskItem["task_type_key"] = "unknown";

				if (task.request_params && typeof task.request_params === "object") {
					const rp = task.request_params as unknown as Record<string, unknown>;
					if ("optuna_config" in rp) taskTypeKey = "optimization";
					else if ("contracts" in rp) taskTypeKey = "portfolio";
					else if ("strategy_name" in rp) taskTypeKey = "backtest";
				}

				const resultsData = task.results as
					| Record<string, Record<string, unknown>>
					| undefined;
				let backtestKpis: Record<string, unknown> | null = null;

				// Looking for the results object inside `results`, as it is nested under a key with the symbol name
				if (
					taskTypeKey === "backtest" &&
					resultsData &&
					typeof resultsData === "object"
				) {
					const symbolKey = Object.keys(resultsData).find((key) => {
						const val = resultsData[key];
						return val && typeof val === "object" && "total_pnl" in val;
					});
					if (symbolKey) {
						backtestKpis = resultsData[symbolKey];
					}
				}

				return {
					id: task.task_id,
					run_id: backtestKpis?.run_id as string | undefined, // Use run_id from the found KPI
					name: getTaskDisplayName(task, t("common:na")),
					task_type_key: taskTypeKey,
					task_type_display: t(`taskTypes.${taskTypeKey}`),
					symbol:
						(task.request_params as RequestParamsHelper | undefined)?.symbol ||
						t("common:na"),
					status: task.status,
					created_at: task.submitted_at,
					pnl: backtestKpis?.total_pnl as number | undefined,
				};
			})
			.sort(
				(a, b) =>
					new Date(b.created_at).getTime() - new Date(a.created_at).getTime(),
			);
	}, [data, t]);

	const handleDeleteConfirmation = (item: DisplayedTaskItem) => {
		if (item.task_type_key !== "backtest") return;

		// We must always use the main task ID (task_id),
		// which is called 'id' in our DisplayedTaskItem.
		const taskIdToDelete = item.id;
		console.log("ID SENT FOR DELETION:", taskIdToDelete);

		setConfirmModal({
			open: true,
			title: t("confirmation.deleteTitle", { type: item.task_type_display }),
			description: t("confirmation.deleteDescription", { name: item.name }),
			isLoading: isDeletingBacktest,
			itemIdToActOn: taskIdToDelete, // Use taskIdToDelete to track the loading state
			onConfirm: () => {
				// Always send taskIdToDelete for deletion
				deleteBacktestRun(taskIdToDelete, {
					onSettled: () =>
						setConfirmModal({
							open: false,
							title: "",
							description: "",
							onConfirm: () => {},
							isLoading: false,
							itemIdToActOn: null,
						}),
				});
			},
		});
	};

	const getDetailsLink = (item: DisplayedTaskItem): string => {
		switch (item.task_type_key) {
			case "backtest":
				return `/research/backtests/${item.run_id || item.id}`;
			case "optimization":
				return `/research/optimizations/${item.id}`;
			case "portfolio":
				return `/research/portfolio-backtests/${item.id}`;
			// case 'geneticSearch': // Add if/when genetic search has a viewer page
			//   return `/discovery/runs/${item.id}`;
			default:
				return "#";
		}
	};

	return (
		<PageLayout title={t("pageTitle")} icon={FlaskConical}>
			<Tabs
				value={activeTab}
				onValueChange={handleTabChange}
				className="space-y-6"
			>
				<TabsList className="grid w-full grid-cols-2">
					<TabsTrigger value="tasks" className="flex items-center gap-2">
						<ListTodo className="w-4 h-4" />
						{t("tabs.tasks")}
					</TabsTrigger>
					<TabsTrigger value="simulator" className="flex items-center gap-2">
						<FlaskConical className="w-4 h-4" />
						{t("tabs.simulator")}
					</TabsTrigger>
				</TabsList>

				<TabsContent value="tasks">
					<div className="grid gap-6 lg:grid-cols-5">
						<div className="lg:col-span-3">
							<Card>
								<CardHeader>
									<CardTitle>{t("taskHistory.title")}</CardTitle>
									<CardDescription>
										{t("taskHistory.description")}
									</CardDescription>
								</CardHeader>
								<CardContent>
									{isLoading && (
										<div className="space-y-2">
											{[...Array(5)].map((_, i) => (
												<Skeleton key={i} className="h-12 w-full rounded-md" />
											))}
										</div>
									)}
									{isError && (
										<Alert variant="destructive">
											<AlertTriangle className="h-4 w-4" />
											<AlertTitle>
												{t("taskHistory.errors.loadFailedTitle")}
											</AlertTitle>
											<AlertDescription>
												{error instanceof Error
													? error.message
													: t("taskHistory.errors.unknownError")}
											</AlertDescription>
										</Alert>
									)}
									{!isLoading && !isError && allRuns.length === 0 && (
										<div className="text-center text-muted-foreground py-8">
											{t("table.noTasks")}
										</div>
									)}
									{!isLoading && !isError && allRuns.length > 0 && (
										<Table>
											<TableHeader>
												<TableRow>
													<TableHead>{t("table.colName")}</TableHead>
													<TableHead>{t("table.colType")}</TableHead>
													<TableHead>{t("table.colSymbol")}</TableHead>
													<TableHead>{t("table.colStatus")}</TableHead>
													<TableHead>{t("table.colResult")}</TableHead>
													<TableHead>{t("table.colSubmitted")}</TableHead>
													<TableHead className="text-right">
														{t("table.colActions")}
													</TableHead>
												</TableRow>
											</TableHeader>
											<TableBody>
												{allRuns.map((item) => (
													<TableRow key={item.id}>
														<TableCell className="font-medium">
															{item.name}
														</TableCell>
														<TableCell>
															<Badge variant="outline">
																{item.task_type_display}
															</Badge>
														</TableCell>
														<TableCell className="font-mono text-xs">
															{item.symbol}
														</TableCell>
														<TableCell>
															<GetStatusBadge status={item.status} t={t} />
														</TableCell>
														<TableCell
															className={`font-mono text-xs ${item.pnl == null ? "" : item.pnl >= 0 ? "text-profit" : "text-loss"}`}
														>
															{item.pnl != null
																? `${item.pnl >= 0 ? "+" : ""}$${item.pnl.toFixed(2)}`
																: t("common:na")}
														</TableCell>
														<TableCell className="text-xs text-muted-foreground">
															{new Date(item.created_at).toLocaleString()}
														</TableCell>
														<TableCell className="text-right">
															<div className="flex justify-end space-x-1">
																<Tooltip>
																	<TooltipTrigger asChild>
																		<Button
																			variant="ghost"
																			size="icon"
																			className="h-8 w-8"
																			asChild
																		>
																			<Link to={getDetailsLink(item)}>
																				<Eye size={16} />
																			</Link>
																		</Button>
																	</TooltipTrigger>
																	<TooltipContent>
																		{t("tooltips.viewDetails")}
																	</TooltipContent>
																</Tooltip>
																{item.task_type_key === "backtest" && ( // Check against task_type_key
																	<Tooltip>
																		<TooltipTrigger asChild>
																			<Button
																				variant="ghost"
																				size="icon"
																				className="h-8 w-8 text-destructive hover:text-destructive"
																				onClick={() =>
																					handleDeleteConfirmation(item)
																				}
																				disabled={
																					confirmModal.isLoading &&
																					confirmModal.itemIdToActOn ===
																						(item.run_id || item.id)
																				}
																			>
																				{confirmModal.isLoading &&
																				confirmModal.itemIdToActOn ===
																					(item.run_id || item.id) ? (
																					<Loader2 className="w-4 h-4 animate-spin" />
																				) : (
																					<Trash2 size={16} />
																				)}
																			</Button>
																		</TooltipTrigger>
																		<TooltipContent>
																			{t("tooltips.deleteRun")}
																		</TooltipContent>
																	</Tooltip>
																)}
															</div>
														</TableCell>
													</TableRow>
												))}
											</TableBody>
										</Table>
									)}
								</CardContent>
								{data && data.total > 0 && (
									<CardFooter className="flex items-center justify-between border-t pt-4">
										<div className="text-sm text-muted-foreground">
											{t("common:pagination.totalItems", { count: data.total })}
										</div>
										<div className="flex items-center space-x-2">
											<Button
												variant="outline"
												size="sm"
												onClick={() => setPage((p) => Math.max(1, p - 1))}
												disabled={page <= 1}
											>
												<ChevronLeft className="h-4 w-4" />
											</Button>
											<span className="text-sm font-medium">
												{t("common:pagination.pageInfo", {
													page: page,
													totalPages:
														Math.ceil(data.total / pageSize) > 0
															? Math.ceil(data.total / pageSize)
															: 1,
												})}
											</span>
											<Button
												variant="outline"
												size="sm"
												onClick={() => setPage((p) => p + 1)}
												disabled={page >= Math.ceil(data.total / pageSize)}
											>
												<ChevronRight className="h-4 w-4" />
											</Button>
										</div>
									</CardFooter>
								)}
							</Card>
						</div>
						<div className="lg:col-span-2">
							<LaunchTaskForm />
						</div>
					</div>
				</TabsContent>

				<TabsContent value="simulator">
					<SimulationTab />
				</TabsContent>
			</Tabs>

			<ConfirmationModal
				open={confirmModal.open}
				title={confirmModal.title}
				description={confirmModal.description}
				onConfirm={confirmModal.onConfirm}
				loading={confirmModal.isLoading}
				onOpenChange={(open) =>
					setConfirmModal({
						...confirmModal,
						open,
						itemIdToActOn: open ? confirmModal.itemIdToActOn : null,
					})
				}
			/>
		</PageLayout>
	);
}
