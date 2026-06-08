// src/pages/MLCorePage.tsx

import {
	Activity,
	BrainCircuit,
	ChevronRight,
	Copy,
	Database,
	Eye,
	Filter,
	FlaskConical,
	Layers,
	Loader2,
	Play,
	RefreshCcw,
	Settings,
	Shield,
	Trash2,
	TrendingUp,
	Zap,
} from "lucide-react";
import type React from "react";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate, useSearchParams } from "react-router-dom";

// Platform Components
import { PageLayout } from "@/components/layout/PageLayout";
import { DatasetDetailModal } from "@/components/models/DatasetDetailModal";
import { ModelQualityReport } from "@/components/models/ModelQualityReport";
// Existing components
import { TrainingProgressCharts } from "@/components/models/TrainingProgressCharts";
import { AppLoader } from "@/components/shared/AppLoader";
import { ConfirmationModal } from "@/components/shared/ConfirmationModal";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
	Card,
	CardContent,
	CardDescription,
	CardHeader,
	CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import {
	Select,
	SelectContent,
	SelectItem,
	SelectTrigger,
	SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
	Tooltip,
	TooltipContent,
	TooltipProvider,
	TooltipTrigger,
} from "@/components/ui/tooltip";
import { useToast } from "@/components/ui/use-toast";
// API Hooks
import {
	useCreateDatasetTask,
	useCreateModelTrainingTask,
	useDeleteDatasetRun,
	useDeleteTrainingRun,
	useGetTrainingRunDetails,
	useListDatasetRuns,
	useListTrainingRuns,
	useStartMlStrategy,
} from "@/lib/api";
// Types
import type {
	DatasetRunCreate,
	DatasetRunResponse,
	StrategyRunRequest,
	TrainingRunCreate,
} from "@/types/api";

// ============================================================================
// DATASET MODULE
// ============================================================================
const DatasetModule: React.FC = () => {
	const { t } = useTranslation("modelLab");
	const { data: datasets = [], isLoading } = useListDatasetRuns();
	const { mutate: createDataset, isPending: isCreating } =
		useCreateDatasetTask();
	const { mutate: deleteDataset, isPending: isDeleting } =
		useDeleteDatasetRun();
	const [viewingDataset, setViewingDataset] =
		useState<DatasetRunResponse | null>(null);
	const [confirmModal, setConfirmModal] = useState<{
		open: boolean;
		id: string | null;
	}>({ open: false, id: null });

	// Form state
	const [formData, setFormData] = useState({
		name: "",
		symbols: "BTCUSDT",
		start_date: "2023-01-01",
		end_date: "2024-01-01",
		feature_types: ["Klines 1m"],
		target_variable: "Price_Movement_5m",
	});

	const handleSubmit = (e: React.FormEvent) => {
		e.preventDefault();
		const payload: DatasetRunCreate = {
			...formData,
			symbols: formData.symbols.split(",").map((s) => s.trim().toUpperCase()),
		};
		createDataset(payload, {
			onSuccess: () => setFormData({ ...formData, name: "" }),
		});
	};

	const handleDelete = (id: string) => {
		deleteDataset(id, {
			onSettled: () => setConfirmModal({ open: false, id: null }),
		});
	};

	const getStatusBadge = (status: string) => {
		const s = status.toUpperCase();
		if (s === "COMPLETED")
			return (
				<Badge className="bg-emerald-500/10 text-emerald-500 border-emerald-500/20">
					{t("statuses.COMPLETED", "Completed")}
				</Badge>
			);
		if (s === "FAILED")
			return (
				<Badge variant="destructive">{t("statuses.FAILED", "Failed")}</Badge>
			);
		if (s === "RUNNING")
			return (
				<Badge className="bg-blue-500/10 text-blue-500 border-blue-500/20 animate-pulse">
					{t("statuses.RUNNING", "Running")}
				</Badge>
			);
		return <Badge variant="outline">{t(`statuses.${s}`, s)}</Badge>;
	};

	return (
		<div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
			{/* Form Panel */}
			<div className="lg:col-span-4 space-y-6">
				<Card className="border-border/50">
					<CardHeader className="pb-4">
						<CardTitle className="flex items-center gap-2 text-base">
							<div className="p-2 rounded-lg bg-amber-500/10">
								<Database className="w-4 h-4 text-amber-500" />
							</div>
							{t("launchForm.tabDataset", "Create Dataset")}
						</CardTitle>
						<CardDescription className="text-xs">
							{t(
								"launchForm.description",
								"Configure data collection parameters",
							)}
						</CardDescription>
					</CardHeader>
					<CardContent>
						<form onSubmit={handleSubmit} className="space-y-4">
							<div className="space-y-2">
								<label className="text-[11px] font-bold text-muted-foreground uppercase tracking-wider">
									{t("launchForm.datasetNameLabel", "Name")}
								</label>
								<Input
									value={formData.name}
									onChange={(e) =>
										setFormData({ ...formData, name: e.target.value })
									}
									placeholder={t(
										"launchForm.datasetNamePlaceholder",
										"Dataset name...",
									)}
									className="bg-muted/30 border-border/50"
								/>
							</div>
							<div className="space-y-2">
								<label className="text-[11px] font-bold text-muted-foreground uppercase tracking-wider">
									{t("launchForm.symbolsLabel", "Symbols")}
								</label>
								<Input
									value={formData.symbols}
									onChange={(e) =>
										setFormData({ ...formData, symbols: e.target.value })
									}
									placeholder={t(
										"launchForm.symbolsPlaceholder",
										"BTCUSDT, ETHUSDT...",
									)}
									className="bg-muted/30 border-border/50"
								/>
							</div>
							<div className="grid grid-cols-2 gap-3">
								<div className="space-y-2">
									<label className="text-[11px] font-bold text-muted-foreground uppercase tracking-wider">
										{t("launchForm.dateRangeLabel", "Start")}
									</label>
									<Input
										type="date"
										value={formData.start_date}
										onChange={(e) =>
											setFormData({ ...formData, start_date: e.target.value })
										}
										className="bg-muted/30 border-border/50"
									/>
								</div>
								<div className="space-y-2">
									<label className="text-[11px] font-bold text-muted-foreground uppercase tracking-wider">
										{t("launchForm.endDateLabel", "End")}
									</label>
									<Input
										type="date"
										value={formData.end_date}
										onChange={(e) =>
											setFormData({ ...formData, end_date: e.target.value })
										}
										className="bg-muted/30 border-border/50"
									/>
								</div>
							</div>
							<Button
								type="submit"
								disabled={isCreating || !formData.name}
								className="w-full"
							>
								{isCreating && (
									<Loader2 className="mr-2 h-4 w-4 animate-spin" />
								)}
								{t("launchForm.generateDatasetButton", "Generate Dataset")}
							</Button>
						</form>
					</CardContent>
				</Card>

				{/* Session Summary */}
				<Card className="bg-gradient-to-br from-primary/10 to-primary/5 border-primary/20">
					<CardContent className="pt-6">
						<div className="flex items-center gap-2 mb-4">
							<Shield className="w-4 h-4 text-primary" />
							<span className="font-semibold text-sm">
								{t("sessionSummary", "Session Summary")}
							</span>
						</div>
						<div className="space-y-3 text-sm">
							<div className="flex justify-between">
								<span className="text-muted-foreground">
									{t("tasksTable.typeDataset", "Datasets")}
								</span>
								<span className="font-mono font-bold">{datasets.length}</span>
							</div>
							<div className="flex justify-between">
								<span className="text-muted-foreground">
									{t("statuses.COMPLETED", "Completed")}
								</span>
								<span className="font-mono font-bold text-emerald-500">
									{datasets.filter((d) => d.status === "COMPLETED").length}
								</span>
							</div>
							<div className="flex justify-between">
								<span className="text-muted-foreground">
									{t("statuses.RUNNING", "Running")}
								</span>
								<span className="font-mono font-bold text-blue-500">
									{datasets.filter((d) => d.status === "RUNNING").length}
								</span>
							</div>
						</div>
					</CardContent>
				</Card>
			</div>

			{/* Datasets List */}
			<div className="lg:col-span-8">
				<Card className="border-border/50">
					<CardHeader className="pb-4">
						<CardTitle className="text-base">
							{t("tasksTable.title", "Existing Datasets")}
						</CardTitle>
						<CardDescription className="text-xs">
							{datasets.length} {t("tasksTable.colName", "datasets")}
						</CardDescription>
					</CardHeader>
					<CardContent>
						<TooltipProvider>
							<div className="space-y-2">
								{isLoading ? (
									[...Array(3)].map((_, i) => (
										<Skeleton key={i} className="h-16 w-full" />
									))
								) : datasets.length === 0 ? (
									<div className="text-center py-12 text-muted-foreground">
										<Database className="w-12 h-12 mx-auto mb-4 opacity-20" />
										<p>
											{t(
												"tasksTable.noTasks",
												"No datasets yet. Create your first dataset.",
											)}
										</p>
									</div>
								) : (
									datasets.map((dataset) => (
										<div
											key={dataset.id}
											className="group flex items-center justify-between p-4 rounded-xl bg-muted/30 border border-border/50 hover:border-primary/30 transition-all"
										>
											<div className="flex items-center gap-4">
												<div className="p-3 rounded-lg bg-amber-500/10">
													<Database className="w-5 h-5 text-amber-500" />
												</div>
												<div>
													<p className="font-medium">{dataset.name}</p>
													<p className="text-xs text-muted-foreground font-mono">
														{dataset.id.substring(0, 8)}... •{" "}
														{new Date(dataset.created_at).toLocaleDateString()}
													</p>
												</div>
											</div>
											<div className="flex items-center gap-3">
												{getStatusBadge(dataset.status)}
												<Tooltip>
													<TooltipTrigger asChild>
														<Button
															variant="ghost"
															size="icon"
															className="h-8 w-8"
															onClick={() => setViewingDataset(dataset)}
														>
															<Eye className="w-4 h-4" />
														</Button>
													</TooltipTrigger>
													<TooltipContent>
														{t("tasksTable.viewDetailsTooltip", "View Details")}
													</TooltipContent>
												</Tooltip>
												<Tooltip>
													<TooltipTrigger asChild>
														<Button
															variant="ghost"
															size="icon"
															className="h-8 w-8 text-destructive"
															onClick={() =>
																setConfirmModal({ open: true, id: dataset.id })
															}
														>
															<Trash2 className="w-4 h-4" />
														</Button>
													</TooltipTrigger>
													<TooltipContent>
														{t("tasksTable.deleteTaskTooltip", "Delete")}
													</TooltipContent>
												</Tooltip>
											</div>
										</div>
									))
								)}
							</div>
						</TooltipProvider>
					</CardContent>
				</Card>
			</div>

			<DatasetDetailModal
				isOpen={!!viewingDataset}
				onClose={() => setViewingDataset(null)}
				dataset={viewingDataset}
			/>
			<ConfirmationModal
				open={confirmModal.open}
				title={t("datasetDeleteFailedTitle", "Delete Dataset")}
				description={t(
					"confirmStopDesc",
					"Are you sure? This action cannot be undone.",
				)}
				onConfirm={() => confirmModal.id && handleDelete(confirmModal.id)}
				loading={isDeleting}
				onOpenChange={(open) => setConfirmModal({ ...confirmModal, open })}
			/>
		</div>
	);
};

// ============================================================================
// TRAINING CONFIG MODULE
// ============================================================================
const TrainingConfigModule: React.FC<{
	onTrainingCreated: (id: string) => void;
}> = ({ onTrainingCreated }) => {
	const { t } = useTranslation("modelLab");
	const { data: datasets = [], isLoading: isLoadingDatasets } =
		useListDatasetRuns();
	const { mutate: createTraining, isPending: isCreating } =
		useCreateModelTrainingTask();

	const [trainType, setTrainType] = useState<"online" | "batch">("online");
	const [formData, setFormData] = useState({
		dataset_id: "",
		model_type: "XGBoost" as const,
		learning_rate: 0.005,
		l2: 0.001,
		drift_detector: true,
		features_json: "[]",
		hyperparameters_json: "{}",
	});

	const completedDatasets = useMemo(
		() => datasets.filter((d) => d.status === "COMPLETED"),
		[datasets],
	);

	const handleSubmit = (e: React.FormEvent) => {
		e.preventDefault();
		const payload: TrainingRunCreate = {
			dataset_id: formData.dataset_id,
			model_type: formData.model_type,
			features_json: JSON.parse(formData.features_json || "[]"),
			hyperparameters_json: {
				...JSON.parse(formData.hyperparameters_json || "{}"),
				learning_rate: formData.learning_rate,
				l2: formData.l2,
			},
		};
		createTraining(payload, {
			onSuccess: (data) => {
				onTrainingCreated(data.id);
			},
		});
	};

	return (
		<div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
			{/* Main Settings Area */}
			<div className="lg:col-span-8 space-y-6">
				{/* Train Type Toggle */}
				<div className="flex items-center gap-4 mb-2">
					<div className="flex bg-muted rounded-lg p-1 border border-border/50">
						<button
							onClick={() => setTrainType("online")}
							className={`px-4 py-2 text-xs font-bold rounded-md transition-all ${
								trainType === "online"
									? "bg-primary text-primary-foreground shadow-sm"
									: "text-muted-foreground hover:text-foreground"
							}`}
						>
							ONLINE (River)
						</button>
						<button
							onClick={() => setTrainType("batch")}
							className={`px-4 py-2 text-xs font-bold rounded-md transition-all ${
								trainType === "batch"
									? "bg-primary text-primary-foreground shadow-sm"
									: "text-muted-foreground hover:text-foreground"
							}`}
						>
							BATCH (Sklearn)
						</button>
					</div>
					<Badge variant="outline" className="text-[10px]">
						{trainType === "online"
							? t("trainingMode", "INC-LEARNING")
							: "GRADIENT-DESCENT"}
					</Badge>
				</div>

				<Card className="border-border/50">
					<CardHeader className="pb-4">
						<CardTitle className="flex items-center gap-2 text-base">
							<Settings className="w-4 h-4 text-primary" />
							{t("architectureTitle", "Architecture & Hyperparameters")}
						</CardTitle>
					</CardHeader>
					<CardContent>
						<form onSubmit={handleSubmit} className="space-y-6">
							<div className="grid grid-cols-2 gap-6">
								<div className="space-y-2">
									<label className="text-[11px] font-bold text-muted-foreground uppercase tracking-wider">
										{t("launchForm.selectDatasetLabel", "Dataset")}
									</label>
									<Select
										value={formData.dataset_id}
										onValueChange={(v) =>
											setFormData({ ...formData, dataset_id: v })
										}
										disabled={isLoadingDatasets}
									>
										<SelectTrigger className="bg-muted/30 border-border/50">
											<SelectValue
												placeholder={
													isLoadingDatasets
														? t("common:loading", "Loading...")
														: t(
																"launchForm.selectDatasetPlaceholder",
																"Select dataset",
															)
												}
											/>
										</SelectTrigger>
										<SelectContent>
											{completedDatasets.map((d) => (
												<SelectItem key={d.id} value={d.id}>
													{d.name} ({d.id.substring(0, 8)})
												</SelectItem>
											))}
										</SelectContent>
									</Select>
								</div>

								<div className="space-y-2">
									<label className="text-[11px] font-bold text-muted-foreground uppercase tracking-wider">
										{t("launchForm.modelTypeLabel", "Algorithm")}
									</label>
									<Select
										value={formData.model_type}
										onValueChange={(v) =>
											setFormData({ ...formData, model_type: v as "XGBoost" })
										}
									>
										<SelectTrigger className="bg-muted/30 border-border/50">
											<SelectValue />
										</SelectTrigger>
										<SelectContent>
											{trainType === "online" ? (
												<>
													<SelectItem value="River HOEFFDINGTREE">
														Hoeffding Tree
													</SelectItem>
													<SelectItem value="Logistic">
														Logistic Regression (SGD)
													</SelectItem>
												</>
											) : (
												<>
													<SelectItem value="XGBoost">XGBoost</SelectItem>
													<SelectItem value="Sklearn RandomForest">
														Random Forest
													</SelectItem>
												</>
											)}
										</SelectContent>
									</Select>
								</div>

								<div className="space-y-2">
									<label className="text-[11px] font-bold text-muted-foreground uppercase tracking-wider">
										Learning Rate
									</label>
									<div className="relative">
										<Input
											type="number"
											step="0.001"
											value={formData.learning_rate}
											onChange={(e) =>
												setFormData({
													...formData,
													learning_rate: parseFloat(e.target.value),
												})
											}
											className="bg-muted/30 border-border/50 pr-10"
										/>
										<Zap className="absolute right-3 top-2.5 w-4 h-4 text-muted-foreground" />
									</div>
								</div>

								<div className="space-y-2">
									<label className="text-[11px] font-bold text-muted-foreground uppercase tracking-wider">
										L2 Regularization
									</label>
									<Input
										type="number"
										step="0.0001"
										value={formData.l2}
										onChange={(e) =>
											setFormData({
												...formData,
												l2: parseFloat(e.target.value),
											})
										}
										className="bg-muted/30 border-border/50"
									/>
								</div>
							</div>

							<div className="flex items-center justify-between p-4 bg-muted/30 rounded-xl border border-border/50">
								<div>
									<p className="text-sm font-medium">
										{t("driftDetectionTitle", "Drift Detection (ADWIN)")}
									</p>
									<p className="text-xs text-muted-foreground">
										{t("driftDetectionDesc", "Auto-adapt to data drift")}
									</p>
								</div>
								<button
									type="button"
									onClick={() =>
										setFormData({
											...formData,
											drift_detector: !formData.drift_detector,
										})
									}
									className={`w-11 h-6 rounded-full relative transition-colors ${
										formData.drift_detector
											? "bg-primary"
											: "bg-muted-foreground/30"
									}`}
								>
									<div
										className={`absolute top-1 w-4 h-4 bg-white rounded-full transition-all ${
											formData.drift_detector ? "right-1" : "left-1"
										}`}
									/>
								</button>
							</div>

							<Button
								type="submit"
								disabled={isCreating || !formData.dataset_id}
								className="w-full"
							>
								{isCreating ? (
									<RefreshCcw className="mr-2 h-4 w-4 animate-spin" />
								) : (
									<Play className="mr-2 h-4 w-4" />
								)}
								{t("launchForm.startTrainingButton", "Start Training")}
							</Button>
						</form>
					</CardContent>
				</Card>
			</div>

			{/* Sidebar */}
			<div className="lg:col-span-4 space-y-6">
				<Card className="bg-gradient-to-br from-primary to-primary/80 text-primary-foreground">
					<CardContent className="pt-6 relative overflow-hidden">
						<TrendingUp className="absolute top-4 right-4 w-20 h-20 opacity-10" />
						<div className="flex items-center gap-2 mb-4">
							<Shield className="w-4 h-4" />
							<span className="font-semibold text-sm">
								{t("sessionSummary", "Session Summary")}
							</span>
						</div>
						<div className="space-y-3 relative z-10">
							<div className="flex justify-between items-center">
								<span className="opacity-70 text-xs">
									{t("algorithm", "Algorithm")}
								</span>
								<span className="font-mono text-xs font-bold">
									{formData.model_type ||
										t("common:notSelected", "Not selected")}
								</span>
							</div>
							<div className="flex justify-between items-center">
								<span className="opacity-70 text-xs">
									{t("learningRate", "Learning Rate")}
								</span>
								<span className="font-mono text-xs font-bold">
									{formData.learning_rate}
								</span>
							</div>
							<div className="flex justify-between items-center">
								<span className="opacity-70 text-xs">
									{t("trainingMode", "Training Mode")}
								</span>
								<span className="font-mono text-xs font-bold">
									{trainType.toUpperCase()}
								</span>
							</div>
							<div className="pt-3 mt-2 border-t border-white/20 flex justify-between items-center">
								<span className="text-sm font-bold">
									{t("readyDatasets", "Ready Datasets")}
								</span>
								<span className="text-xs font-bold">
									{completedDatasets.length}
								</span>
							</div>
						</div>
					</CardContent>
				</Card>

				<Card className="border-border/50">
					<CardHeader className="pb-3">
						<CardTitle className="text-xs font-bold uppercase tracking-widest text-muted-foreground">
							{t("pipelineStatus", "Pipeline Status")}
						</CardTitle>
					</CardHeader>
					<CardContent>
						<ul className="space-y-3">
							{[
								{
									label: t("stepFeatureExtractor", "Feature Extractor"),
									status: "Ready",
									color: "text-emerald-500",
								},
								{
									label: t("stepScaling", "Scaling (Robust)"),
									status: "Active",
									color: "text-emerald-500",
								},
								{
									label: t("stepLabeling", "Labeling Engine"),
									status: formData.dataset_id ? "Ready" : "Pending",
									color: formData.dataset_id
										? "text-emerald-500"
										: "text-amber-500",
								},
							].map((step, i) => (
								<li key={i} className="flex items-center justify-between">
									<span className="text-xs">{step.label}</span>
									<span className={`text-[10px] font-bold ${step.color}`}>
										{t(`statuses.${step.status.toUpperCase()}`, step.status)}
									</span>
								</li>
							))}
						</ul>
					</CardContent>
				</Card>
			</div>
		</div>
	);
};

// ============================================================================
// MODELS LIST MODULE
// ============================================================================
const ModelsListModule: React.FC<{ onSelectModel: (id: string) => void }> = ({
	onSelectModel,
}) => {
	const { t } = useTranslation("modelLab");
	const { data: trainings = [], isLoading } = useListTrainingRuns();
	const { mutate: deleteTraining, isPending: isDeleting } =
		useDeleteTrainingRun();
	const [confirmModal, setConfirmModal] = useState<{
		open: boolean;
		id: string | null;
	}>({ open: false, id: null });

	const getStatusBadge = (status: string) => {
		const s = status.toUpperCase();
		if (s === "COMPLETED")
			return (
				<Badge className="bg-emerald-500/10 text-emerald-500 border-emerald-500/20">
					{t("statusDeployed", "Deployed")}
				</Badge>
			);
		if (s === "FAILED")
			return (
				<Badge variant="destructive">{t("statuses.FAILED", "Failed")}</Badge>
			);
		if (s === "RUNNING")
			return (
				<Badge className="bg-blue-500/10 text-blue-500 border-blue-500/20">
					{t("statusTraining", "Training")}
				</Badge>
			);
		return <Badge variant="outline">{t(`statuses.${s}`, s)}</Badge>;
	};

	const handleDelete = (id: string) => {
		deleteTraining(id, {
			onSettled: () => setConfirmModal({ open: false, id: null }),
		});
	};

	return (
		<div className="space-y-4">
			<div className="flex justify-between items-center">
				<h3 className="text-sm font-bold text-muted-foreground uppercase tracking-widest">
					{t("historyExperiments", "History of Experiments")}
				</h3>
				<div className="flex gap-2">
					<Button variant="outline" size="icon" className="h-8 w-8">
						<Filter className="w-4 h-4" />
					</Button>
				</div>
			</div>

			{isLoading ? (
				[...Array(3)].map((_, i) => (
					<Skeleton key={i} className="h-20 w-full" />
				))
			) : trainings.length === 0 ? (
				<Card className="border-border/50">
					<CardContent className="py-12 text-center text-muted-foreground">
						<Activity className="w-12 h-12 mx-auto mb-4 opacity-20" />
						<p>
							{t(
								"noTrainingRuns",
								"No training runs yet. Start your first training.",
							)}
						</p>
					</CardContent>
				</Card>
			) : (
				trainings.map((training) => (
					<div
						key={training.id}
						className="group bg-card border border-border/50 hover:border-primary/30 p-5 rounded-2xl flex items-center transition-all cursor-pointer"
						onClick={() => onSelectModel(training.id)}
					>
						<div
							className={`p-4 rounded-xl mr-5 transition-all ${
								training.status === "COMPLETED"
									? "bg-emerald-500/10 text-emerald-500"
									: "bg-muted text-muted-foreground group-hover:bg-muted/80"
							}`}
						>
							<Activity className="w-6 h-6" />
						</div>
						<div className="flex-1 grid grid-cols-5 gap-6 items-center">
							<div>
								<div className="text-sm font-bold">
									{training.id.substring(0, 8)}
								</div>
								<div className="text-[10px] text-muted-foreground font-mono">
									{new Date(training.created_at).toLocaleDateString()}
								</div>
							</div>
							<div>
								<div className="text-[10px] text-muted-foreground uppercase tracking-widest mb-1">
									{t("architecture", "Architecture")}
								</div>
								<div className="text-xs font-bold">{training.model_type}</div>
							</div>
							<div>
								<div className="text-[10px] text-muted-foreground uppercase tracking-widest mb-1">
									{t("datasetId", "Dataset")}
								</div>
								<div className="text-xs font-mono">
									{training.dataset_id.substring(0, 8)}...
								</div>
							</div>
							<div>
								<div className="text-[10px] text-muted-foreground uppercase tracking-widest mb-1">
									{t("tasksTable.colStatus", "Status")}
								</div>
								{getStatusBadge(training.status)}
							</div>
							<div className="text-right flex items-center justify-end gap-2">
								<Button
									variant="ghost"
									size="icon"
									className="h-8 w-8 text-destructive"
									onClick={(e) => {
										e.stopPropagation();
										setConfirmModal({ open: true, id: training.id });
									}}
								>
									<Trash2 className="w-4 h-4" />
								</Button>
								<ChevronRight className="w-5 h-5 text-muted-foreground group-hover:text-primary transition-colors" />
							</div>
						</div>
					</div>
				))
			)}

			<ConfirmationModal
				open={confirmModal.open}
				title={t("trainingDeleteFailedTitle", "Delete Training Run")}
				description={t(
					"trainingDeleteSuccessDescription",
					"Are you sure? This will delete the model and all associated data.",
				)}
				onConfirm={() => confirmModal.id && handleDelete(confirmModal.id)}
				loading={isDeleting}
				onOpenChange={(open) => setConfirmModal({ ...confirmModal, open })}
			/>
		</div>
	);
};

// ============================================================================
// MODEL DETAILS MODULE
// ============================================================================
const ModelDetailsModule: React.FC<{ modelId: string; onBack: () => void }> = ({
	modelId,
	onBack,
}) => {
	const { t } = useTranslation("modelLab");
	const { toast } = useToast();
	const navigate = useNavigate();
	const { data: run, isLoading, isError } = useGetTrainingRunDetails(modelId);
	const { mutate: startLiveTrade, isPending: isDeploying } =
		useStartMlStrategy();

	const handleCopy = (text: string) => {
		navigator.clipboard.writeText(text);
		toast({ title: "Copied to clipboard" });
	};

	const handleDeploy = () => {
		if (!run) return;
		const payload: StrategyRunRequest = {
			strategy_name: "MLStrategy",
			symbol: "BTCUSDT",
			market_type: "futures",
			mode: "paper",
			params: { model_id: run.id },
		};
		startLiveTrade(payload, {
			onSuccess: () => navigate("/strategies"),
		});
	};

	if (isLoading) {
		return (
			<div className="flex items-center justify-center h-64">
				<AppLoader
					size="lg"
					text={t("loadingDetails", "Loading model details...")}
				/>
			</div>
		);
	}

	if (isError || !run) {
		return (
			<Card className="border-destructive">
				<CardContent className="py-8 text-center text-destructive">
					<p>{t("failedLoadDetails", "Failed to load model details")}</p>
					<Button variant="outline" onClick={onBack} className="mt-4">
						{t("backToModels", "Back to Models")}
					</Button>
				</CardContent>
			</Card>
		);
	}

	const isCompleted = run.status === "COMPLETED";

	return (
		<div className="space-y-6">
			<div className="flex items-center justify-between">
				<Button
					variant="ghost"
					onClick={onBack}
					className="text-muted-foreground"
				>
					{t("backToModels", "← Back to Models")}
				</Button>
				{isCompleted && (
					<div className="flex gap-2">
						<Button
							variant="outline"
							onClick={() =>
								navigate("/research", { state: { modelId: run.id } })
							}
						>
							{t("backtest", "Backtest")}
						</Button>
						<Button
							onClick={handleDeploy}
							disabled={isDeploying}
							className="bg-emerald-600 hover:bg-emerald-700"
						>
							{isDeploying && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
							{t("deployModel", "Deploy Model")}
						</Button>
					</div>
				)}
			</div>

			{/* Summary Card */}
			<Card className="border-border/50">
				<CardHeader className="flex flex-row items-start justify-between">
					<div>
						<CardTitle className="text-base">
							{t("modelDetails", "Model Summary")}
						</CardTitle>
						<CardDescription className="text-xs">
							{run.model_type}
						</CardDescription>
					</div>
					<Badge
						className={
							run.status === "COMPLETED"
								? "bg-emerald-500"
								: run.status === "RUNNING"
									? "bg-blue-500 animate-pulse"
									: "bg-muted-foreground"
						}
					>
						{t(`statuses.${run.status.toUpperCase()}`, run.status)}
					</Badge>
				</CardHeader>
				<CardContent className="grid grid-cols-3 gap-6">
					<div>
						<p className="text-xs text-muted-foreground">
							{t("modelId", "Model ID")}
						</p>
						<div className="flex items-center gap-1">
							<span className="font-mono text-sm">
								{run.id.substring(0, 12)}...
							</span>
							<Button
								variant="ghost"
								size="icon"
								className="h-6 w-6"
								onClick={() => handleCopy(run.id)}
							>
								<Copy className="w-3 h-3" />
							</Button>
						</div>
					</div>
					<div>
						<p className="text-xs text-muted-foreground">
							{t("datasetId", "Dataset ID")}
						</p>
						<div className="flex items-center gap-1">
							<span className="font-mono text-sm">
								{run.dataset_id.substring(0, 12)}...
							</span>
							<Button
								variant="ghost"
								size="icon"
								className="h-6 w-6"
								onClick={() => handleCopy(run.dataset_id)}
							>
								<Copy className="w-3 h-3" />
							</Button>
						</div>
					</div>
					<div>
						<p className="text-xs text-muted-foreground">
							{t("created", "Created")}
						</p>
						<span className="text-sm">
							{new Date(run.created_at).toLocaleString()}
						</span>
					</div>
				</CardContent>
			</Card>

			{/* Charts and Reports */}
			<div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
				<TrainingProgressCharts run={run} />
				{isCompleted ? (
					<ModelQualityReport runId={run.id} />
				) : (
					<Card className="flex items-center justify-center min-h-[300px] border-border/50">
						<CardContent className="text-center text-muted-foreground">
							<p>
								{t(
									"qualityReportFuture",
									"Quality report will be available after training completes",
								)}
							</p>
						</CardContent>
					</Card>
				)}
			</div>
		</div>
	);
};

// ============================================================================
// MAIN PAGE COMPONENT
// ============================================================================
const MLCorePage: React.FC = () => {
	const { t } = useTranslation("modelLab");
	const [searchParams, setSearchParams] = useSearchParams();
	const [activeTab, setActiveTab] = useState(
		searchParams.get("tab") || "dataset",
	);
	const [selectedModelId, setSelectedModelId] = useState<string | null>(
		searchParams.get("model") || null,
	);

	const handleTabChange = (tab: string) => {
		setActiveTab(tab);
		setSearchParams({ tab });
		if (tab !== "details") {
			setSelectedModelId(null);
		}
	};

	const handleSelectModel = (id: string) => {
		setSelectedModelId(id);
		setActiveTab("details");
		setSearchParams({ tab: "details", model: id });
	};

	const handleTrainingCreated = (id: string) => {
		setSelectedModelId(id);
		setActiveTab("details");
		setSearchParams({ tab: "details", model: id });
	};

	return (
		<PageLayout title="ML Core" icon={BrainCircuit}>
			<Tabs
				value={activeTab}
				onValueChange={handleTabChange}
				className="h-full flex flex-col"
			>
				<TabsList className="grid w-full max-w-lg grid-cols-4 mb-6">
					<TabsTrigger value="dataset" className="flex items-center gap-2">
						<Database className="w-4 h-4" />
						<span className="hidden sm:inline">
							{t("launchForm.tabDataset", "Dataset")}
						</span>
					</TabsTrigger>
					<TabsTrigger value="training" className="flex items-center gap-2">
						<FlaskConical className="w-4 h-4" />
						<span className="hidden sm:inline">
							{t("launchForm.tabTraining", "Training")}
						</span>
					</TabsTrigger>
					<TabsTrigger value="models" className="flex items-center gap-2">
						<Activity className="w-4 h-4" />
						<span className="hidden sm:inline">
							{t("tasksTable.colType", "Models")}
						</span>
					</TabsTrigger>
					<TabsTrigger
						value="details"
						className="flex items-center gap-2"
						disabled={!selectedModelId}
					>
						<Layers className="w-4 h-4" />
						<span className="hidden sm:inline">
							{t("tasksTable.viewDetailsTooltip", "Details")}
						</span>
					</TabsTrigger>
				</TabsList>

				<div className="flex-1 min-h-0 overflow-y-auto">
					<TabsContent value="dataset" className="mt-0">
						<DatasetModule />
					</TabsContent>

					<TabsContent value="training" className="mt-0">
						<TrainingConfigModule onTrainingCreated={handleTrainingCreated} />
					</TabsContent>

					<TabsContent value="models" className="mt-0">
						<ModelsListModule onSelectModel={handleSelectModel} />
					</TabsContent>

					<TabsContent value="details" className="mt-0">
						{selectedModelId ? (
							<ModelDetailsModule
								modelId={selectedModelId}
								onBack={() => handleTabChange("models")}
							/>
						) : (
							<Card className="border-border/50">
								<CardContent className="py-12 text-center text-muted-foreground">
									<Layers className="w-12 h-12 mx-auto mb-4 opacity-20" />
									<p>
										{t(
											"selectModelPrompt",
											"Select a model from the Models tab to view details",
										)}
									</p>
								</CardContent>
							</Card>
						)}
					</TabsContent>
				</div>
			</Tabs>
		</PageLayout>
	);
};

export default MLCorePage;
