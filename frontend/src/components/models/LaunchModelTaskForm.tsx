// src/components/models/LaunchModelTaskForm.tsx

import { zodResolver } from "@hookform/resolvers/zod";
import { Loader2 } from "lucide-react";
import { useForm } from "react-hook-form";
import { useTranslation } from "react-i18next";
import * as z from "zod";
import { Button } from "@/components/ui/button";
import {
	Card,
	CardContent,
	CardDescription,
	CardHeader,
	CardTitle,
} from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import {
	Form,
	FormControl,
	FormField,
	FormItem,
	FormLabel,
	FormMessage,
} from "@/components/ui/form";
import { Input } from "@/components/ui/input";
import {
	Select,
	SelectContent,
	SelectItem,
	SelectTrigger,
	SelectValue,
} from "@/components/ui/select";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import {
	useCreateDatasetTask,
	useCreateModelTrainingTask,
	useListDatasetRuns,
} from "@/lib/api";
import type { DatasetRunCreate, TrainingRunCreate } from "@/types/api";

const createDatasetSchema = (t: (key: string) => string) =>
	z.object({
		name: z.string().min(3, t("validation.nameRequired")),
		symbols: z.string().min(1, t("validation.symbolsRequired")),
		start_date: z
			.string()
			.regex(/^\d{4}-\d{2}-\d{2}$/, t("validation.dateFormat")),
		end_date: z
			.string()
			.regex(/^\d{4}-\d{2}-\d{2}$/, t("validation.dateFormat")),
		feature_types: z
			.array(z.string())
			.refine((value) => value.some((item) => item), {
				message: "You have to select at least one feature type.",
			}),
		target_variable: z.string().min(1, t("validation.targetRequired")),
	});

const createTrainingSchema = (t: (key: string) => string) =>
	z.object({
		dataset_id: z.string().min(1, t("validation.datasetRequired")),
		model_type: z.enum([
			"XGBoost",
			"River HOEFFDINGTREE",
			"Sklearn RandomForest",
		]),
		features_json: z.string().refine(
			(v) => {
				try {
					JSON.parse(v);
					return true;
				} catch {
					return false;
				}
			},
			{ message: t("validation.validJsonRequired") },
		),
		hyperparameters_json: z.string().refine(
			(v) => {
				try {
					JSON.parse(v);
					return true;
				} catch {
					return false;
				}
			},
			{ message: t("validation.validJsonRequired") },
		),
	});

type DatasetFormValues = z.infer<ReturnType<typeof createDatasetSchema>>;
type TrainingFormValues = z.infer<ReturnType<typeof createTrainingSchema>>;

const FEATURE_ITEMS = [
	{ id: "Klines 1m", labelKey: "featureKlines" },
	{ id: "AggTrades", labelKey: "featureAggTrades" },
	{ id: "Orderbook L2", labelKey: "featureOrderbook" },
] as const;

export const LaunchModelTaskForm = () => {
	const { t } = useTranslation("modelLab");
	const { mutate: createDataset, isPending: isCreatingDataset } =
		useCreateDatasetTask();
	const { mutate: createTraining, isPending: isCreatingTraining } =
		useCreateModelTrainingTask();
	const { data: availableDatasets, isLoading: isLoadingDatasets } =
		useListDatasetRuns();

	const datasetForm = useForm<DatasetFormValues>({
		resolver: zodResolver(createDatasetSchema(t)),
		defaultValues: {
			name: "",
			symbols: "BTCUSDT",
			start_date: "2023-01-01",
			end_date: "2024-01-01",
			feature_types: ["Klines 1m"],
			target_variable: "Price_Movement_5m",
		},
	});

	const trainingForm = useForm<TrainingFormValues>({
		resolver: zodResolver(createTrainingSchema(t)),
		defaultValues: {
			dataset_id: "",
			model_type: "XGBoost",
			features_json: "[]",
			hyperparameters_json: "{}",
		},
	});

	const onDatasetSubmit = (values: DatasetFormValues) => {
		const payload: DatasetRunCreate = {
			...values,
			symbols: values.symbols.split(",").map((s) => s.trim().toUpperCase()),
		};
		createDataset(payload, { onSuccess: () => datasetForm.reset() });
	};

	const onTrainingSubmit = (values: TrainingFormValues) => {
		const payload: TrainingRunCreate = {
			...values,
			features_json: JSON.parse(values.features_json),
			hyperparameters_json: JSON.parse(values.hyperparameters_json),
		};
		createTraining(payload, { onSuccess: () => trainingForm.reset() });
	};

	return (
		<Card>
			<CardHeader>
				<CardTitle>{t("launchForm.title")}</CardTitle>
				<CardDescription>{t("launchForm.description")}</CardDescription>
			</CardHeader>
			<CardContent>
				<Tabs defaultValue="dataset">
					<TabsList className="grid w-full grid-cols-2">
						<TabsTrigger value="dataset">
							{t("launchForm.tabDataset")}
						</TabsTrigger>
						<TabsTrigger value="training">
							{t("launchForm.tabTraining")}
						</TabsTrigger>
					</TabsList>

					<TabsContent value="dataset" className="pt-4">
						<Form {...datasetForm}>
							<form
								onSubmit={datasetForm.handleSubmit(onDatasetSubmit)}
								className="space-y-4"
							>
								<FormField
									control={datasetForm.control}
									name="name"
									render={({ field }) => (
										<FormItem>
											<FormLabel>{t("launchForm.datasetNameLabel")}</FormLabel>
											<FormControl>
												<Input
													placeholder={t("launchForm.datasetNamePlaceholder")}
													{...field}
												/>
											</FormControl>
											<FormMessage />
										</FormItem>
									)}
								/>
								<FormField
									control={datasetForm.control}
									name="symbols"
									render={({ field }) => (
										<FormItem>
											<FormLabel>{t("launchForm.symbolsLabel")}</FormLabel>
											<FormControl>
												<Input
													placeholder={t("launchForm.symbolsPlaceholder")}
													{...field}
												/>
											</FormControl>
											<FormMessage />
										</FormItem>
									)}
								/>
								<div className="grid grid-cols-2 gap-4">
									<FormField
										control={datasetForm.control}
										name="start_date"
										render={({ field }) => (
											<FormItem>
												<FormLabel>{t("launchForm.dateRangeLabel")}</FormLabel>
												<FormControl>
													<Input type="date" {...field} />
												</FormControl>
												<FormMessage />
											</FormItem>
										)}
									/>
									<FormField
										control={datasetForm.control}
										name="end_date"
										render={({ field }) => (
											<FormItem>
												<FormLabel className="invisible">End Date</FormLabel>
												<FormControl>
													<Input type="date" {...field} />
												</FormControl>
												<FormMessage />
											</FormItem>
										)}
									/>
								</div>
								<FormField
									control={datasetForm.control}
									name="feature_types"
									render={() => (
										<FormItem>
											<FormLabel>{t("launchForm.featureTypesLabel")}</FormLabel>
											<div className="space-y-2 rounded-md border p-3">
												{FEATURE_ITEMS.map((item) => (
													<FormField
														key={item.id}
														control={datasetForm.control}
														name="feature_types"
														render={({ field }) => (
															<FormItem className="flex flex-row items-start space-x-3 space-y-0">
																<FormControl>
																	<Checkbox
																		checked={field.value?.includes(item.id)}
																		onCheckedChange={(checked) => {
																			return checked
																				? field.onChange([
																						...field.value,
																						item.id,
																					])
																				: field.onChange(
																						field.value?.filter(
																							(value) => value !== item.id,
																						),
																					);
																		}}
																	/>
																</FormControl>
																<FormLabel className="font-normal">
																	{t(`launchForm.${item.labelKey}`)}
																</FormLabel>
															</FormItem>
														)}
													/>
												))}
											</div>
											<FormMessage />
										</FormItem>
									)}
								/>
								<FormField
									control={datasetForm.control}
									name="target_variable"
									render={({ field }) => (
										<FormItem>
											<FormLabel>
												{t("launchForm.targetVariableLabel")}
											</FormLabel>
											<Select
												onValueChange={field.onChange}
												defaultValue={field.value}
											>
												<FormControl>
													<SelectTrigger>
														<SelectValue placeholder="Select target..." />
													</SelectTrigger>
												</FormControl>
												<SelectContent>
													<SelectItem value="Price_Movement_5m">
														Future Price Movement {">"} X% (5m)
													</SelectItem>
													<SelectItem value="Signal_Quality">
														Signal Quality
													</SelectItem>
												</SelectContent>
											</Select>
											<FormMessage />
										</FormItem>
									)}
								/>
								<Button
									type="submit"
									disabled={isCreatingDataset}
									className="w-full"
								>
									{isCreatingDataset && (
										<Loader2 className="mr-2 h-4 w-4 animate-spin" />
									)}{" "}
									{t("launchForm.generateDatasetButton")}
								</Button>
							</form>
						</Form>
					</TabsContent>

					<TabsContent value="training" className="pt-4">
						<Form {...trainingForm}>
							<form
								onSubmit={trainingForm.handleSubmit(onTrainingSubmit)}
								className="space-y-4"
							>
								<FormField
									control={trainingForm.control}
									name="dataset_id"
									render={({ field }) => (
										<FormItem>
											<FormLabel>
												{t("launchForm.selectDatasetLabel")}
											</FormLabel>
											<Select
												onValueChange={field.onChange}
												defaultValue={field.value}
												disabled={isLoadingDatasets}
											>
												<FormControl>
													<SelectTrigger>
														<SelectValue
															placeholder={
																isLoadingDatasets
																	? "Loading..."
																	: t("launchForm.selectDatasetPlaceholder")
															}
														/>
													</SelectTrigger>
												</FormControl>
												<SelectContent>
													{availableDatasets
														?.filter((d) => d.status === "COMPLETED")
														.map((d) => (
															<SelectItem key={d.id} value={d.id}>
																{d.name} ({d.id.substring(0, 8)})
															</SelectItem>
														))}
												</SelectContent>
											</Select>
											<FormMessage />
										</FormItem>
									)}
								/>
								<FormField
									control={trainingForm.control}
									name="model_type"
									render={({ field }) => (
										<FormItem>
											<FormLabel>{t("launchForm.modelTypeLabel")}</FormLabel>
											<Select
												onValueChange={field.onChange}
												defaultValue={field.value}
											>
												<FormControl>
													<SelectTrigger>
														<SelectValue />
													</SelectTrigger>
												</FormControl>
												<SelectContent>
													<SelectItem value="XGBoost">XGBoost</SelectItem>
													<SelectItem value="River HOEFFDINGTREE">
														River HOEFFDINGTREE
													</SelectItem>
													<SelectItem value="Sklearn RandomForest">
														Sklearn RandomForest
													</SelectItem>
												</SelectContent>
											</Select>
											<FormMessage />
										</FormItem>
									)}
								/>
								<FormField
									control={trainingForm.control}
									name="features_json"
									render={({ field }) => (
										<FormItem>
											<FormLabel>{t("launchForm.featuresJsonLabel")}</FormLabel>
											<FormControl>
												<Textarea rows={3} {...field} />
											</FormControl>
											<FormMessage />
										</FormItem>
									)}
								/>
								<FormField
									control={trainingForm.control}
									name="hyperparameters_json"
									render={({ field }) => (
										<FormItem>
											<FormLabel>
												{t("launchForm.hyperparametersJsonLabel")}
											</FormLabel>
											<FormControl>
												<Textarea rows={4} {...field} />
											</FormControl>
											<FormMessage />
										</FormItem>
									)}
								/>
								<Button
									type="submit"
									disabled={isCreatingTraining}
									className="w-full"
								>
									{isCreatingTraining && (
										<Loader2 className="mr-2 h-4 w-4 animate-spin" />
									)}{" "}
									{t("launchForm.startTrainingButton")}
								</Button>
							</form>
						</Form>
					</TabsContent>
				</Tabs>
			</CardContent>
		</Card>
	);
};
