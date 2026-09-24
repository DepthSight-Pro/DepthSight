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
import { Segmented } from "@/components/ui/quant-ui";
import {
	Table,
	TableBody,
	TableCell,
	TableHead,
	TableHeader,
	TableRow,
} from "@/components/ui/table";
import {
	Tooltip,
	TooltipContent,
	TooltipTrigger,
} from "@/components/ui/tooltip";
import { useDeleteBacktestRun, useResearchTasks } from "@/lib/api";
import { cn } from "@/lib/utils";
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
				<Badge
					variant="outline"
					className="bg-emerald-500/10 border-emerald-500/25 text-emerald-400 font-mono text-[11px] font-semibold tracking-wide"
				>
					{t("statuses.completed")}
				</Badge>
			);
		case "FAILURE":
			return (
				<Badge
					variant="outline"
					className="bg-rose-500/10 border-rose-500/25 text-rose-400 font-mono text-[11px] font-semibold tracking-wide"
				>
					{t("statuses.failed")}
				</Badge>
			);
		case "PENDING":
			return (
				<Badge
					variant="outline"
					className="bg-white/[0.04] border-white/10 text-white/60 font-mono text-[11px]"
				>
					{t("statuses.pending")}
				</Badge>
			);
		case "RUNNING":
			return (
				<Badge
					variant="outline"
					className="animate-pulse bg-cyan/10 border-cyan/30 text-cyan font-mono text-[11px] font-semibold shadow-[0_0_12px_rgba(0,212,255,0.25)]"
				>
					{t("statuses.running")}
				</Badge>
			);
		case "STOPPED":
			return (
				<Badge
					variant="outline"
					className="bg-amber-500/10 border-amber-500/25 text-amber-400 font-mono text-[11px]"
				>
					{t("statuses.stopped")}
				</Badge>
			);
		default:
			return (
				<Badge
					variant="outline"
					className="bg-white/[0.04] border-white/10 text-white/60 font-mono text-[11px]"
				>
					{status}
				</Badge>
			);
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
			<div className="space-y-6 w-full min-w-0">
				{/* Mode Tabs */}
				<div className="flex items-center overflow-x-auto pb-1 max-w-full touch-pan-x [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
					<Segmented<"tasks" | "simulator">
						size="md"
						value={activeTab as "tasks" | "simulator"}
						onChange={handleTabChange}
						options={[
							{
								value: "tasks",
								label: t("tabs.tasks"),
								icon: <ListTodo className="w-4 h-4" />,
							},
							{
								value: "simulator",
								label: t("tabs.simulator"),
								icon: <FlaskConical className="w-4 h-4" />,
							},
						]}
					/>
				</div>

				{activeTab === "tasks" && (
					<div className="grid gap-6 lg:grid-cols-5 animate-fade-up w-full min-w-0">
						<div className="lg:col-span-3 w-full min-w-0">
							<div className="rounded-2xl border border-white/10 glass shadow-xl overflow-hidden w-full min-w-0">
								<div className="p-4 sm:p-6 border-b border-white/5">
									<h2 className="text-base font-bold text-white tracking-tight">
										{t("taskHistory.title")}
									</h2>
									<p className="text-xs text-white/50 mt-1">
										{t("taskHistory.description")}
									</p>
								</div>
								<div className="p-0 overflow-x-auto w-full min-w-0 touch-pan-x overscroll-x-contain">
									{isLoading && (
										<div className="space-y-2 p-6">
											{[...Array(5)].map((_, i) => (
												<div key={i} className="h-12 w-full rounded-xl bg-white/[0.03] border border-white/5 animate-pulse" />
											))}
										</div>
									)}
									{isError && (
										<div className="p-6">
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
										</div>
									)}
									{!isLoading && !isError && allRuns.length === 0 && (
										<div className="text-center text-white/40 py-12 text-sm font-mono">
											{t("table.noTasks")}
										</div>
									)}
									{!isLoading && !isError && allRuns.length > 0 && (
										<Table className="min-w-[760px]">
											<TableHeader className="bg-white/[0.02] border-b border-white/10">
												<TableRow className="hover:bg-transparent border-b border-white/10">
													<TableHead className="font-mono text-[11px] uppercase tracking-wider text-white/50 whitespace-nowrap">{t("table.colName")}</TableHead>
													<TableHead className="font-mono text-[11px] uppercase tracking-wider text-white/50 whitespace-nowrap">{t("table.colType")}</TableHead>
													<TableHead className="font-mono text-[11px] uppercase tracking-wider text-white/50 whitespace-nowrap">{t("table.colSymbol")}</TableHead>
													<TableHead className="font-mono text-[11px] uppercase tracking-wider text-white/50 whitespace-nowrap">{t("table.colStatus")}</TableHead>
													<TableHead className="font-mono text-[11px] uppercase tracking-wider text-white/50 whitespace-nowrap">{t("table.colResult")}</TableHead>
													<TableHead className="font-mono text-[11px] uppercase tracking-wider text-white/50 whitespace-nowrap">{t("table.colSubmitted")}</TableHead>
													<TableHead className="text-right font-mono text-[11px] uppercase tracking-wider text-white/50 whitespace-nowrap">
														{t("table.colActions")}
													</TableHead>
												</TableRow>
											</TableHeader>
											<TableBody>
												{allRuns.map((item) => (
													<TableRow
														key={item.id}
														className="group border-b border-white/5 hover:bg-white/[0.03] transition-colors"
													>
														<TableCell className="font-medium text-white/90 text-sm whitespace-nowrap">
															{item.name}
														</TableCell>
														<TableCell className="whitespace-nowrap">
															<Badge
																variant="outline"
																className="bg-white/[0.04] border-white/10 text-white/70 font-mono text-[10px] uppercase whitespace-nowrap"
															>
																{item.task_type_display}
															</Badge>
														</TableCell>
														<TableCell className="font-mono text-xs text-cyan font-semibold whitespace-nowrap">
															{item.symbol}
														</TableCell>
														<TableCell className="whitespace-nowrap">
															<GetStatusBadge status={item.status} t={t} />
														</TableCell>
														<TableCell
															className={cn(
																"font-mono text-xs font-bold whitespace-nowrap",
																item.pnl == null
																	? "text-white/40"
																	: item.pnl >= 0
																		? "text-emerald-400"
																		: "text-rose-400",
															)}
														>
															{item.pnl != null
																? `${item.pnl >= 0 ? "+" : ""}$${item.pnl.toFixed(2)}`
																: t("common:na")}
														</TableCell>
														<TableCell className="text-xs text-white/40 font-mono whitespace-nowrap">
															{new Date(item.created_at).toLocaleString()}
														</TableCell>
														<TableCell className="text-right whitespace-nowrap">
															<div className="flex justify-end items-center space-x-1.5">
																<Tooltip>
																	<TooltipTrigger asChild>
																		<Button
																			variant="ghost"
																			size="icon"
																			className="h-8 w-8 text-white/60 hover:text-cyan hover:bg-cyan/10 rounded-lg transition-colors"
																			asChild
																		>
																			<Link to={getDetailsLink(item)}>
																				<Eye size={15} />
																			</Link>
																		</Button>
																	</TooltipTrigger>
																	<TooltipContent className="bg-[#0c0d12] border-white/10 text-white text-xs">
																		{t("tooltips.viewDetails")}
																	</TooltipContent>
																</Tooltip>
																{item.task_type_key === "backtest" && (
																	<Tooltip>
																		<TooltipTrigger asChild>
																			<Button
																				variant="ghost"
																				size="icon"
																				className="h-8 w-8 text-white/40 hover:text-rose-400 hover:bg-rose-500/10 rounded-lg transition-colors"
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
																					<Loader2 className="w-4 h-4 animate-spin text-rose-400" />
																				) : (
																					<Trash2 size={15} />
																				)}
																			</Button>
																		</TooltipTrigger>
																		<TooltipContent className="bg-[#0c0d12] border-white/10 text-white text-xs">
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
								</div>
								{data && data.total > 0 && (
									<div className="flex flex-wrap items-center justify-between border-t border-white/5 bg-white/[0.01] px-4 py-3 sm:px-6 sm:py-4 gap-2">
										<div className="text-xs text-white/40 font-mono">
											{t("common:pagination.totalItems", { count: data.total })}
										</div>
										<div className="flex items-center space-x-2">
											<Button
												variant="ghost"
												size="sm"
												className="h-8 px-2.5 border border-white/10 bg-white/[0.03] text-white/70 hover:text-white hover:bg-white/10 rounded-lg text-xs"
												onClick={() => setPage((p) => Math.max(1, p - 1))}
												disabled={page <= 1}
											>
												<ChevronLeft className="h-4 w-4" />
											</Button>
											<span className="text-xs font-mono text-white/60 px-2">
												{t("common:pagination.pageInfo", {
													page: page,
													totalPages:
														Math.ceil(data.total / pageSize) > 0
															? Math.ceil(data.total / pageSize)
															: 1,
												})}
											</span>
											<Button
												variant="ghost"
												size="sm"
												className="h-8 px-2.5 border border-white/10 bg-white/[0.03] text-white/70 hover:text-white hover:bg-white/10 rounded-lg text-xs"
												onClick={() => setPage((p) => p + 1)}
												disabled={page >= Math.ceil(data.total / pageSize)}
											>
												<ChevronRight className="h-4 w-4" />
											</Button>
										</div>
									</div>
								)}
							</div>
						</div>
						<div className="lg:col-span-2 w-full min-w-0">
							<LaunchTaskForm />
						</div>
					</div>
				)}

				{activeTab === "simulator" && (
					<div className="animate-fade-up">
						<SimulationTab />
					</div>
				)}
			</div>

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
