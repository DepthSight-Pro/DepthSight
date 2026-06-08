// src/components/research/LaunchTaskForm.tsx

import { zodResolver } from "@hookform/resolvers/zod";
import { Loader2 } from "lucide-react";
import type React from "react";
import { useEffect, useMemo, useState } from "react";
import { useFieldArray, useForm } from "react-hook-form";
import { useTranslation } from "react-i18next";
import { useLocation, useNavigate } from "react-router-dom";
import * as z from "zod";
import { Button } from "@/components/ui/button";
import {
	Card,
	CardContent,
	CardDescription,
	CardHeader,
	CardTitle,
} from "@/components/ui/card";
import {
	Form,
	FormControl,
	FormDescription,
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
import { Switch } from "@/components/ui/switch";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import { useToast } from "@/components/ui/use-toast";
// --- API AND TYPE IMPORTS ---
import {
	useRunBacktest,
	useRunOptimization,
	useRunPortfolioBacktest,
} from "@/lib/api";
import type {
	BacktestRequest,
	OptimizationRequest,
	PortfolioBacktestRequest,
} from "@/types/api";
import { OptunaParamsPanel } from "./OptunaParamsPanel";
import PortfolioContractForm from "./PortfolioContractForm";

// --- HELPER FUNCTION FOR DATES ---
/**
 * Formats a Date object into a 'YYYY-MM-DD' string.
 * @param date - Date object for formatting.
 * @returns String in 'YYYY-MM-DD' format.
 */
const formatDateForInput = (date: Date): string => {
	return date.toISOString().split("T")[0];
};

// --- Validation schemas ---
const createSchemas = (t: (key: string) => string) => {
	const baseTaskSchema = {
		strategy_name: z.string().min(1, t("validationStrategyNameRequired")),
		symbol: z.string().min(1, t("validationSymbolRequired")).toUpperCase(),
		market_type: z.enum(["futures", "spot"], {
			error: t("validationMarketTypeRequired"),
		}),
		start_date: z
			.string()
			.regex(/^\d{4}-\d{2}-\d{2}$/, t("validationDateFormat")),
		end_date: z
			.string()
			.regex(/^\d{4}-\d{2}-\d{2}$/, t("validationDateFormat")),
		model_id: z.string().optional(),
	};

	const jsonStringSchema = z
		.string()
		.refine(
			(value) => {
				if (
					value.trim() === "" ||
					value.trim() === "{}" ||
					value.trim() === "[]"
				)
					return true;
				try {
					JSON.parse(value);
					return true;
				} catch {
					return false;
				}
			},
			{ message: t("validationValidJsonOrEmpty") },
		)
		.transform((val) => (val.trim() === "" ? "{}" : val));

	const backtestSchema = z.object({
		...baseTaskSchema,
		params: jsonStringSchema,
	});

	const optimizationSchema = z.object({
		...baseTaskSchema,
		optuna_config: jsonStringSchema.refine(
			(val) => val.trim() !== "" && val.trim() !== "{}",
			t("validationOptunaConfigNotEmpty"),
		),
	});

	const portfolioContractSchema = z.object({
		strategy_name: z.string().min(1, t("validationStrategyConfigRequired")),
		symbol: z.string().min(1, t("validationSymbolRequired")).toUpperCase(),
		params: jsonStringSchema,
	});

	const portfolioBacktestSchema = z.object({
		name: z.string().min(1, t("validationPortfolioNameRequired")),
		initial_balance: z.preprocess(
			(val) => Number(val),
			z.number().positive(t("validationInitialBalancePositive")),
		),
		start_date: z
			.string()
			.regex(/^\d{4}-\d{2}-\d{2}$/, t("validationDateFormat")),
		end_date: z
			.string()
			.regex(/^\d{4}-\d{2}-\d{2}$/, t("validationDateFormat")),
		contracts: z
			.array(portfolioContractSchema)
			.min(1, t("validationMinOneContract")),
		global_risk_limits: jsonStringSchema.optional(),
		simulate_market_impact: z.boolean(),
	});

	return { backtestSchema, optimizationSchema, portfolioBacktestSchema };
};

type BacktestFormValues = z.infer<
	ReturnType<typeof createSchemas>["backtestSchema"]
>;
type OptimizationFormValues = z.infer<
	ReturnType<typeof createSchemas>["optimizationSchema"]
>;
export type PortfolioBacktestFormValues = z.infer<
	ReturnType<typeof createSchemas>["portfolioBacktestSchema"]
>;

// --- UPDATING DATES IN defaultValues ---

// Calculate dates once
const today = new Date();
const oneMonthAgo = new Date(new Date().setMonth(today.getMonth() - 1));
const formattedToday = formatDateForInput(today);
const formattedOneMonthAgo = formatDateForInput(oneMonthAgo);

const defaultPortfolioBacktestValues = (): PortfolioBacktestFormValues => ({
	name: "",
	initial_balance: 100000,
	start_date: formattedOneMonthAgo,
	end_date: formattedToday,
	contracts: [{ strategy_name: "", symbol: "", params: "{}" }],
	global_risk_limits: "{}",
	simulate_market_impact: false,
});

const defaultOptunaConfig = `{
  "n_trials": 100,
  "metric_name": "sharpe_ratio",
  "search_space": {}
}`;

export const LaunchTaskForm: React.FC = () => {
	const { t } = useTranslation(["research", "common"]);
	const { toast } = useToast();
	const [activeTab, setActiveTab] = useState<string>("backtest");
	const [seedStrategy, setSeedStrategy] = useState<Record<
		string,
		unknown
	> | null>(null);
	const [optunaParams, setOptunaParams] = useState<Record<
		string,
		unknown
	> | null>(null);
	const navigate = useNavigate();
	const location = useLocation();

	const { backtestSchema, optimizationSchema, portfolioBacktestSchema } =
		useMemo(() => createSchemas(t), [t]);

	const { mutate: launchBacktest, isPending: isBacktesting } = useRunBacktest();
	const { mutate: launchOptimization, isPending: isOptimizing } =
		useRunOptimization();
	const { mutate: launchPortfolioBacktest, isPending: isPortfolioLoading } =
		useRunPortfolioBacktest();

	const backtestForm = useForm<BacktestFormValues>({
		resolver: zodResolver(backtestSchema),
		// --- UPDATING DATES IN defaultValues ---
		defaultValues: {
			strategy_name: "",
			symbol: "",
			market_type: "futures",
			start_date: formattedOneMonthAgo,
			end_date: formattedToday,
			params: "{}",
			model_id: "",
		},
	});

	const optimizationForm = useForm<OptimizationFormValues>({
		resolver: zodResolver(optimizationSchema),
		// --- UPDATING DATES IN defaultValues ---
		defaultValues: {
			strategy_name: "",
			symbol: "",
			market_type: "futures",
			start_date: formattedOneMonthAgo,
			end_date: formattedToday,
			optuna_config: defaultOptunaConfig,
		},
	});

	const portfolioBacktestForm = useForm<PortfolioBacktestFormValues>({
		resolver: zodResolver(portfolioBacktestSchema),
		defaultValues: defaultPortfolioBacktestValues(),
	});

	const { fields, append, remove } = useFieldArray({
		control: portfolioBacktestForm.control,
		name: "contracts",
	});

	const modelIdFromState = location.state?.modelId;

	useEffect(() => {
		if (modelIdFromState) {
			backtestForm.setValue("model_id", modelIdFromState);
			backtestForm.setValue("strategy_name", "MLStrategy");
			backtestForm.setValue(
				"params",
				JSON.stringify({ model_id: modelIdFromState }, null, 2),
			);
			toast({
				title: t("research:modelLoadedTitle"),
				description: t("research:modelLoadedDescription", {
					modelId: modelIdFromState,
				}),
			});
			navigate(location.pathname, { replace: true, state: {} });
		}
	}, [modelIdFromState, backtestForm, toast, navigate, location.pathname, t]);

	useEffect(() => {
		if (location.state?.seedStrategy) {
			const strategy = location.state.seedStrategy as Record<string, unknown>;

			// Use setTimeout to avoid synchronous setState in effect (prevents cascading renders)
			setTimeout(() => {
				setSeedStrategy(strategy);
				optimizationForm.setValue(
					"strategy_name",
					strategy.name || "VisualStrategy",
				);

				// Prefill fields from location.state if redirected from backtest viewer
				const stateSymbol = location.state.symbol || strategy.symbol;
				if (stateSymbol) {
					optimizationForm.setValue("symbol", stateSymbol);
				}

				if (location.state.start_date) {
					optimizationForm.setValue(
						"start_date",
						location.state.start_date.split("T")[0],
					);
				}
				if (location.state.end_date) {
					optimizationForm.setValue(
						"end_date",
						location.state.end_date.split("T")[0],
					);
				}
				if (location.state.market_type) {
					optimizationForm.setValue("market_type", location.state.market_type);
				}

				optimizationForm.setValue("optuna_config", "{}");
				setActiveTab("optimization");

				toast({
					title: t("research:optunaStrategyLoadedTitle", "Strategy Loaded"),
					description: t(
						"research:optunaStrategyLoadedDescription",
						'Strategy "{{name}}" has been successfully imported for Bayesian optimization.',
						{ name: strategy.name || "VisualStrategy" },
					),
				});
			}, 0);

			navigate(location.pathname, { replace: true, state: {} });
		}
	}, [
		location.state?.seedStrategy,
		location.state?.symbol,
		location.state?.start_date,
		location.state?.end_date,
		location.state?.market_type,
		optimizationForm,
		toast,
		navigate,
		location.pathname,
		t,
	]);

	const handleBacktestSubmit = (values: BacktestFormValues) => {
		const configObject = values.params ? JSON.parse(values.params) : {};
		if (values.model_id) {
			configObject.model_id = values.model_id;
		}
		const payload: BacktestRequest = {
			strategy_name: values.strategy_name,
			symbol: values.symbol,
			market_type: values.market_type,
			start_date: values.start_date,
			end_date: values.end_date,
			params: {
				config: configObject,
			},
		};
		launchBacktest(payload);
	};

	const handleOptimizationSubmit = (values: OptimizationFormValues) => {
		let finalOptunaConfig: Record<string, unknown> | null;
		if (seedStrategy) {
			finalOptunaConfig = optunaParams;
		} else {
			try {
				finalOptunaConfig = JSON.parse(values.optuna_config);
			} catch {
				toast({
					title: t("common:error"),
					description: t("validationValidJsonOrEmpty"),
					variant: "destructive",
				});
				return;
			}
		}

		const payload: OptimizationRequest = {
			...values,
			optuna_config: finalOptunaConfig as Record<string, unknown>,
		};
		launchOptimization(payload, {
			onSuccess: (data) => navigate(`/research/optimizations/${data.task_id}`),
		});
	};

	const handlePortfolioBacktestSubmit = (
		values: PortfolioBacktestFormValues,
	) => {
		const payload: PortfolioBacktestRequest = {
			...values,
			contracts: values.contracts.map((c) => ({
				...c,
				params: c.params ? JSON.parse(c.params) : {},
			})),
			global_risk_limits: values.global_risk_limits
				? JSON.parse(values.global_risk_limits)
				: {},
		};
		launchPortfolioBacktest(payload, {
			onSuccess: () => {
				portfolioBacktestForm.reset(defaultPortfolioBacktestValues());
			},
		});
	};

	return (
		<Card>
			<CardHeader>
				<CardTitle>{t("launchTask.title")}</CardTitle>
				<CardDescription>{t("launchTask.description")}</CardDescription>
			</CardHeader>
			<CardContent>
				<Tabs value={activeTab} onValueChange={setActiveTab}>
					<TabsList className="grid w-full grid-cols-3">
						<TabsTrigger value="backtest">
							{t("launchForm.tabBacktest")}
						</TabsTrigger>
						<TabsTrigger value="optimization">
							{t("launchForm.tabOptimization")}
						</TabsTrigger>
						<TabsTrigger value="portfolio_backtest">
							{t("launchForm.tabPortfolio")}
						</TabsTrigger>
					</TabsList>

					<TabsContent value="backtest" className="pt-4">
						<Form {...backtestForm}>
							<form
								onSubmit={backtestForm.handleSubmit(handleBacktestSubmit)}
								className="space-y-4"
							>
								<FormField
									control={backtestForm.control}
									name="strategy_name"
									render={({ field }) => (
										<FormItem>
											<FormLabel>{t("launchForm.strategyNameLabel")}</FormLabel>
											<FormControl>
												<Input
													placeholder={t("launchForm.strategyNamePlaceholder")}
													{...field}
													disabled={!!modelIdFromState}
												/>
											</FormControl>
											<FormMessage />
										</FormItem>
									)}
								/>
								<FormField
									control={backtestForm.control}
									name="market_type"
									render={({ field }) => (
										<FormItem>
											<FormLabel>{t("launchForm.marketTypeLabel")}</FormLabel>
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
													<SelectItem value="futures">Futures</SelectItem>
													<SelectItem value="spot">Spot</SelectItem>
												</SelectContent>
											</Select>
											<FormMessage />
										</FormItem>
									)}
								/>
								<FormField
									control={backtestForm.control}
									name="symbol"
									render={({ field }) => (
										<FormItem>
											<FormLabel>{t("launchForm.symbolLabel")}</FormLabel>
											<FormControl>
												<Input
													placeholder={t("launchForm.symbolPlaceholder")}
													{...field}
												/>
											</FormControl>
											<FormMessage />
										</FormItem>
									)}
								/>
								<FormField
									control={backtestForm.control}
									name="start_date"
									render={({ field }) => (
										<FormItem>
											<FormLabel>{t("launchForm.startDateLabel")}</FormLabel>
											<FormControl>
												<Input type="date" {...field} />
											</FormControl>
											<FormMessage />
										</FormItem>
									)}
								/>
								<FormField
									control={backtestForm.control}
									name="end_date"
									render={({ field }) => (
										<FormItem>
											<FormLabel>{t("launchForm.endDateLabel")}</FormLabel>
											<FormControl>
												<Input type="date" {...field} />
											</FormControl>
											<FormMessage />
										</FormItem>
									)}
								/>
								<FormField
									control={backtestForm.control}
									name="model_id"
									render={({ field }) => (
										<FormItem className={!field.value ? "hidden" : ""}>
											<FormLabel>Model ID (from AI Lab)</FormLabel>
											<FormControl>
												<Input disabled {...field} />
											</FormControl>
										</FormItem>
									)}
								/>
								<FormField
									control={backtestForm.control}
									name="params"
									render={({ field }) => (
										<FormItem>
											<FormLabel>{t("launchForm.paramsLabel")}</FormLabel>
											<FormControl>
												<Textarea {...field} rows={4} />
											</FormControl>
											<FormMessage />
										</FormItem>
									)}
								/>
								<Button
									type="submit"
									disabled={isBacktesting}
									className="w-full"
								>
									{isBacktesting && (
										<Loader2 className="mr-2 h-4 w-4 animate-spin" />
									)}{" "}
									{isBacktesting
										? t("common:loading")
										: t("launchForm.launchBacktestButton")}
								</Button>
							</form>
						</Form>
					</TabsContent>

					<TabsContent value="optimization" className="pt-4">
						<Form {...optimizationForm}>
							<form
								onSubmit={optimizationForm.handleSubmit(
									handleOptimizationSubmit,
								)}
								className="space-y-4"
							>
								<FormField
									control={optimizationForm.control}
									name="strategy_name"
									render={({ field }) => (
										<FormItem>
											<FormLabel>{t("launchForm.strategyNameLabel")}</FormLabel>
											<FormControl>
												<Input
													placeholder={t("launchForm.strategyNamePlaceholder")}
													{...field}
												/>
											</FormControl>
											<FormMessage />
										</FormItem>
									)}
								/>
								{/* ---ADDED MARKET TYPE FIELD FOR OPTIMIZATION --- */}
								<FormField
									control={optimizationForm.control}
									name="market_type"
									render={({ field }) => (
										<FormItem>
											<FormLabel>{t("launchForm.marketTypeLabel")}</FormLabel>
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
													<SelectItem value="futures">Futures</SelectItem>
													<SelectItem value="spot">Spot</SelectItem>
												</SelectContent>
											</Select>
											<FormMessage />
										</FormItem>
									)}
								/>
								<FormField
									control={optimizationForm.control}
									name="symbol"
									render={({ field }) => (
										<FormItem>
											<FormLabel>{t("launchForm.symbolLabel")}</FormLabel>
											<FormControl>
												<Input
													placeholder={t("launchForm.symbolPlaceholder")}
													{...field}
												/>
											</FormControl>
											<FormMessage />
										</FormItem>
									)}
								/>
								<FormField
									control={optimizationForm.control}
									name="start_date"
									render={({ field }) => (
										<FormItem>
											<FormLabel>{t("launchForm.startDateLabel")}</FormLabel>
											<FormControl>
												<Input type="date" {...field} />
											</FormControl>
											<FormMessage />
										</FormItem>
									)}
								/>
								<FormField
									control={optimizationForm.control}
									name="end_date"
									render={({ field }) => (
										<FormItem>
											<FormLabel>{t("launchForm.endDateLabel")}</FormLabel>
											<FormControl>
												<Input type="date" {...field} />
											</FormControl>
											<FormMessage />
										</FormItem>
									)}
								/>
								{seedStrategy ? (
									<OptunaParamsPanel
										seedStrategy={seedStrategy}
										onChange={setOptunaParams}
									/>
								) : (
									<FormField
										control={optimizationForm.control}
										name="optuna_config"
										render={({ field }) => (
											<FormItem>
												<FormLabel>
													{t("launchForm.optunaConfigLabel")}
												</FormLabel>
												<FormControl>
													<Textarea {...field} rows={5} />
												</FormControl>
												<FormMessage />
											</FormItem>
										)}
									/>
								)}
								<Button
									type="submit"
									disabled={isOptimizing}
									className="w-full"
								>
									{isOptimizing && (
										<Loader2 className="mr-2 h-4 w-4 animate-spin" />
									)}{" "}
									{isOptimizing
										? t("common:loading")
										: t("launchForm.launchOptimizationButton")}
								</Button>
							</form>
						</Form>
					</TabsContent>

					<TabsContent value="portfolio_backtest" className="pt-4">
						<Form {...portfolioBacktestForm}>
							<form
								onSubmit={portfolioBacktestForm.handleSubmit(
									handlePortfolioBacktestSubmit,
								)}
								className="space-y-6"
							>
								<FormField
									control={portfolioBacktestForm.control}
									name="name"
									render={({ field }) => (
										<FormItem>
											<FormLabel>
												{t("launchForm.portfolioNameLabel")}
											</FormLabel>
											<FormControl>
												<Input
													placeholder={t("launchForm.portfolioNamePlaceholder")}
													{...field}
												/>
											</FormControl>
											<FormMessage />
										</FormItem>
									)}
								/>
								<FormField
									control={portfolioBacktestForm.control}
									name="initial_balance"
									render={({ field }) => (
										<FormItem>
											<FormLabel>
												{t("launchForm.initialBalanceLabel")}
											</FormLabel>
											<FormControl>
												<Input type="number" {...field} />
											</FormControl>
											<FormMessage />
										</FormItem>
									)}
								/>
								<div className="grid grid-cols-1 md:grid-cols-2 gap-4">
									<FormField
										control={portfolioBacktestForm.control}
										name="start_date"
										render={({ field }) => (
											<FormItem>
												<FormLabel>{t("launchForm.startDateLabel")}</FormLabel>
												<FormControl>
													<Input type="date" {...field} />
												</FormControl>
												<FormMessage />
											</FormItem>
										)}
									/>
									<FormField
										control={portfolioBacktestForm.control}
										name="end_date"
										render={({ field }) => (
											<FormItem>
												<FormLabel>{t("launchForm.endDateLabel")}</FormLabel>
												<FormControl>
													<Input type="date" {...field} />
												</FormControl>
												<FormMessage />
											</FormItem>
										)}
									/>
								</div>

								<div>
									<FormLabel>{t("launchForm.contractsLabel")}</FormLabel>
									<div className="space-y-3 mt-2">
										{fields.map((item, index) => (
											<PortfolioContractForm
												key={item.id}
												nestIndex={index}
												remove={remove}
												formMethods={portfolioBacktestForm}
											/>
										))}
									</div>
									<Button
										type="button"
										variant="outline"
										size="sm"
										className="mt-2"
										onClick={() =>
											append({ strategy_name: "", symbol: "", params: "{}" })
										}
									>
										{t("launchForm.addContractButton")}
									</Button>
									<FormMessage>
										{portfolioBacktestForm.formState.errors.contracts
											?.message ||
											portfolioBacktestForm.formState.errors.contracts?.root
												?.message}
									</FormMessage>
								</div>

								<FormField
									control={portfolioBacktestForm.control}
									name="global_risk_limits"
									render={({ field }) => (
										<FormItem>
											<FormLabel>{t("launchForm.riskLimitsLabel")}</FormLabel>
											<FormControl>
												<Textarea
													placeholder={t("launchForm.riskLimitsPlaceholder")}
													{...field}
												/>
											</FormControl>
											<FormMessage />
										</FormItem>
									)}
								/>

								<FormField
									control={portfolioBacktestForm.control}
									name="simulate_market_impact"
									render={({ field }) => (
										<FormItem className="flex flex-row items-center justify-between rounded-lg border p-3 shadow-sm">
											<div className="space-y-0.5">
												<FormLabel>
													{t("launchForm.marketImpactLabel")}
												</FormLabel>
												<FormDescription>
													{t("launchForm.marketImpactDesc")}
												</FormDescription>
											</div>
											<FormControl>
												<Switch
													checked={field.value}
													onCheckedChange={field.onChange}
												/>
											</FormControl>
										</FormItem>
									)}
								/>

								<Button
									type="submit"
									disabled={isPortfolioLoading}
									className="w-full"
								>
									{isPortfolioLoading && (
										<Loader2 className="mr-2 h-4 w-4 animate-spin" />
									)}{" "}
									{isPortfolioLoading
										? t("common:loading")
										: t("launchForm.launchPortfolioButton")}
								</Button>
							</form>
						</Form>
					</TabsContent>
				</Tabs>
			</CardContent>
		</Card>
	);
};
