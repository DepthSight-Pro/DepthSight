// src/components/strategies/BacktestStrategyModal.tsx

import { zodResolver } from "@hookform/resolvers/zod";
import { format } from "date-fns";
import { CalendarIcon, Loader2 } from "lucide-react";
import type React from "react";
import { useEffect, useMemo } from "react";
import { useForm } from "react-hook-form";
import { useTranslation } from "react-i18next";
import * as z from "zod";
import { Button } from "@/components/ui/button";
import { Calendar } from "@/components/ui/calendar";
// UI Components
import {
	Dialog,
	DialogContent,
	DialogDescription,
	DialogFooter,
	DialogHeader,
	DialogTitle,
} from "@/components/ui/dialog";
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
	Popover,
	PopoverContent,
	PopoverTrigger,
} from "@/components/ui/popover";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import { Slider } from "@/components/ui/slider";
import { Switch } from "@/components/ui/switch";
import { cn } from "@/lib/utils";

// Types
import type { StrategyTemplate } from "@/types/api";

// Zod schema for form validation with all new fields
const createBacktestSchema = (
	t: (key: string, options?: Record<string, unknown>) => string,
) =>
	z
		.object({
			symbol: z
				.string()
				.min(3, { message: t("backtestModal.errors.symbolRequired") })
				.toUpperCase(),
			market_type: z.enum(["spot", "futures"], {
				message: t("backtestModal.errors.marketTypeRequired"),
			}),
			dateRange: z.object({
				from: z.date({ message: t("backtestModal.errors.startDateRequired") }),
				to: z.date({ message: t("backtestModal.errors.endDateRequired") }),
			}),
			use_ml_confirmation: z.boolean(),
			move_sl_to_be_on_first_tp: z.boolean(),
			use_partial_exits: z.boolean(),
			min_foundation_weight_threshold: z.number().min(0).max(100),
		})
		.refine((data) => data.dateRange.from < data.dateRange.to, {
			message: t("backtestModal.errors.dateOrder"),
			path: ["dateRange"],
		});

export type BacktestFormValues = z.infer<
	ReturnType<typeof createBacktestSchema>
>;

interface BacktestStrategyModalProps {
	isOpen: boolean;
	onClose: () => void;
	onRun: (data: BacktestFormValues) => void;
	isLoading: boolean;
	template: StrategyTemplate | null;
}

export const BacktestStrategyModal: React.FC<BacktestStrategyModalProps> = ({
	isOpen,
	onClose,
	onRun,
	isLoading,
	template,
}) => {
	const { t } = useTranslation("strategies");
	const backtestSchema = useMemo(() => createBacktestSchema(t), [t]);

	const form = useForm<BacktestFormValues>({
		resolver: zodResolver(backtestSchema),
		defaultValues: {
			symbol: "BTCUSDT",
			market_type: "futures",
			dateRange: {
				from: new Date(new Date().setDate(new Date().getDate() - 90)),
				to: new Date(),
			},
			use_ml_confirmation: false,
			move_sl_to_be_on_first_tp: true,
			use_partial_exits: true,
			min_foundation_weight_threshold: 49,
		},
	});

	const hasPartialExits = useMemo(
		() =>
			Array.isArray(template?.default_params?.partial_exit_rr_config) &&
			template.default_params.partial_exit_rr_config.length > 0,
		[template],
	);

	const hasMoveToBe = useMemo(
		() => template?.default_params?.move_sl_to_be_on_first_tp != null,
		[template],
	);

	useEffect(() => {
		if (template && isOpen) {
			form.reset({
				symbol: "BTCUSDT",
				market_type: "futures",
				dateRange: {
					from: new Date(new Date().setDate(new Date().getDate() - 90)),
					to: new Date(),
				},
				use_ml_confirmation: false,
				move_sl_to_be_on_first_tp: hasMoveToBe
					? (template.default_params.move_sl_to_be_on_first_tp as boolean)
					: false,
				use_partial_exits: hasPartialExits,
				min_foundation_weight_threshold: 49,
			});
		}
	}, [template, isOpen, form, hasMoveToBe, hasPartialExits]);

	const onSubmit = (data: BacktestFormValues) => {
		onRun(data);
	};

	return (
		<Dialog open={isOpen} onOpenChange={onClose}>
			<DialogContent className="sm:max-w-[480px]">
				<DialogHeader>
					<DialogTitle>
						{t("backtestModal.title", { name: template?.name })}
					</DialogTitle>
					<DialogDescription>
						{t("backtestModal.description")}
					</DialogDescription>
				</DialogHeader>
				<Form {...form}>
					<form
						onSubmit={form.handleSubmit(onSubmit)}
						className="space-y-4 py-4 max-h-[70vh] overflow-y-auto pr-6"
					>
						<FormField
							control={form.control}
							name="symbol"
							render={({ field }) => (
								<FormItem>
									<FormLabel>{t("backtestModal.symbolLabel")}</FormLabel>
									<FormControl>
										<Input placeholder="BTCUSDT" {...field} />
									</FormControl>
									<FormMessage />
								</FormItem>
							)}
						/>

						<FormField
							control={form.control}
							name="market_type"
							render={({ field }) => (
								<FormItem className="space-y-2">
									<FormLabel>{t("backtestModal.marketTypeLabel")}</FormLabel>
									<FormControl>
										<RadioGroup
											onValueChange={field.onChange}
											defaultValue={field.value}
											className="flex space-x-4"
										>
											<FormItem className="flex items-center space-x-2 space-y-0">
												<FormControl>
													<RadioGroupItem value="futures" />
												</FormControl>
												<FormLabel className="font-normal">
													{t("backtestModal.marketTypeFutures")}
												</FormLabel>
											</FormItem>
											<FormItem className="flex items-center space-x-2 space-y-0">
												<FormControl>
													<RadioGroupItem value="spot" />
												</FormControl>
												<FormLabel className="font-normal">
													{t("backtestModal.marketTypeSpot")}
												</FormLabel>
											</FormItem>
										</RadioGroup>
									</FormControl>
									<FormMessage />
								</FormItem>
							)}
						/>

						<FormField
							control={form.control}
							name="dateRange"
							render={({ field }) => (
								<FormItem className="flex flex-col">
									<FormLabel>{t("backtestModal.dateRangeLabel")}</FormLabel>
									<Popover>
										<PopoverTrigger asChild>
											<FormControl>
												<Button
													variant={"outline"}
													className={cn(
														"w-full justify-start text-left font-normal",
														!field.value?.from && "text-muted-foreground",
													)}
												>
													<CalendarIcon className="mr-2 h-4 w-4" />
													{field.value?.from ? (
														field.value.to ? (
															<>
																{format(field.value.from, "LLL dd, y")} -{" "}
																{format(field.value.to, "LLL dd, y")}
															</>
														) : (
															format(field.value.from, "LLL dd, y")
														)
													) : (
														<span>{t("backtestModal.datePlaceholder")}</span>
													)}
												</Button>
											</FormControl>
										</PopoverTrigger>
										<PopoverContent className="w-auto p-0" align="start">
											<Calendar
												initialFocus
												mode="range"
												defaultMonth={field.value?.from}
												selected={
													field.value
														? { from: field.value.from, to: field.value.to }
														: undefined
												}
												onSelect={(range) =>
													field.onChange(
														range || { from: undefined, to: undefined },
													)
												}
												numberOfMonths={2}
											/>
										</PopoverContent>
									</Popover>
									<FormMessage />
								</FormItem>
							)}
						/>

						<div className="space-y-4 rounded-lg border p-4 shadow-sm">
							<FormField
								control={form.control}
								name="use_ml_confirmation"
								render={({ field }) => (
									<FormItem className="flex flex-row items-center justify-between">
										<FormLabel>{t("launchModal.mlLabel")}</FormLabel>
										<FormControl>
											<Switch
												checked={field.value}
												onCheckedChange={field.onChange}
											/>
										</FormControl>
									</FormItem>
								)}
							/>

							{hasPartialExits && (
								<FormField
									control={form.control}
									name="use_partial_exits"
									render={({ field }) => (
										<FormItem className="flex flex-row items-center justify-between">
											<FormLabel>{t("launchModal.partialsLabel")}</FormLabel>
											<FormControl>
												<Switch
													checked={field.value}
													onCheckedChange={field.onChange}
												/>
											</FormControl>
										</FormItem>
									)}
								/>
							)}

							{hasMoveToBe && (
								<FormField
									control={form.control}
									name="move_sl_to_be_on_first_tp"
									render={({ field }) => (
										<FormItem className="flex flex-row items-center justify-between">
											<FormLabel>{t("launchModal.moveToBeLabel")}</FormLabel>
											<FormControl>
												<Switch
													checked={field.value}
													onCheckedChange={field.onChange}
												/>
											</FormControl>
										</FormItem>
									)}
								/>
							)}

							<FormField
								control={form.control}
								name="min_foundation_weight_threshold"
								render={({ field }) => (
									<FormItem>
										<div className="flex justify-between items-center pt-2">
											<FormLabel>
												{t("launchModal.foundationWeightLabel")}
											</FormLabel>
											<span className="text-sm font-medium">
												{field.value}%
											</span>
										</div>
										<FormControl>
											<Slider
												min={0}
												max={100}
												step={1}
												defaultValue={[field.value]}
												onValueChange={(value: number[]) =>
													field.onChange(value[0])
												}
											/>
										</FormControl>
									</FormItem>
								)}
							/>
						</div>

						<DialogFooter>
							<Button
								type="button"
								variant="outline"
								onClick={onClose}
								disabled={isLoading}
							>
								{t("common:cancel")}
							</Button>
							<Button type="submit" disabled={isLoading}>
								{isLoading && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
								{isLoading ? t("common:running") : t("backtestModal.runButton")}
							</Button>
						</DialogFooter>
					</form>
				</Form>
			</DialogContent>
		</Dialog>
	);
};
