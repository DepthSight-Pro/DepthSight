// src/components/genome/BreedingLab.tsx

import { useMutation, useQuery } from "@tanstack/react-query";
import { AlertCircle, CheckCircle, Loader2, Shuffle } from "lucide-react";
import type React from "react";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
	Card,
	CardContent,
	CardDescription,
	CardHeader,
	CardTitle,
} from "@/components/ui/card";
import {
	Select,
	SelectContent,
	SelectItem,
	SelectTrigger,
	SelectValue,
} from "@/components/ui/select";
import { apiClient } from "@/lib/api";
import { authScopedQueryKey } from "@/lib/queryKeys";
import type { StrategyConfig } from "@/types/api";

interface BreedingMode {
	value: string;
	label: string;
	description: string;
}

interface BreedResponse {
	suggested_name?: string;
	parent_a_name?: string;
	parent_b_name?: string;
	mode?: string;
}

const getBreedingModes = (t: (key: string) => string): BreedingMode[] => [
	{
		value: "entry_a_exit_b",
		label: t("breedingLab.entry_a_exit_b_label"),
		description: t("breedingLab.entry_a_exit_b_desc"),
	},
	{
		value: "entry_b_exit_a",
		label: t("breedingLab.entry_b_exit_a_label"),
		description: t("breedingLab.entry_b_exit_a_desc"),
	},
	{
		value: "filters_a_entry_b",
		label: t("breedingLab.filters_a_entry_b_label"),
		description: t("breedingLab.filters_a_entry_b_desc"),
	},
	{
		value: "filters_b_entry_a",
		label: t("breedingLab.filters_b_entry_a_label"),
		description: t("breedingLab.filters_b_entry_a_desc"),
	},
	{
		value: "balanced_merge",
		label: t("breedingLab.balanced_merge_label"),
		description: t("breedingLab.balanced_merge_desc"),
	},
	{
		value: "best_of_both",
		label: t("breedingLab.best_of_both_label"),
		description: t("breedingLab.best_of_both_desc"),
	},
];

export const BreedingLab: React.FC = () => {
	const { t } = useTranslation("laboratory");
	const [parentAId, setParentAId] = useState<string>("");
	const [parentBId, setParentBId] = useState<string>("");
	const [mode, setMode] = useState<string>("best_of_both");
	const [mutationRate, setMutationRate] = useState<number>(0.1);
	const breedingModes = getBreedingModes(t);

	// --- Update useQuery to use apiClient ---
	const { data: strategiesData, isLoading: strategiesLoading } = useQuery<
		StrategyConfig[]
	>({
		queryKey: authScopedQueryKey("strategyConfigsList"),
		queryFn: () => apiClient<StrategyConfig[]>("/strategies/config"),
	});

	// --- Update useMutation to use apiClient ---
	const breedMutation = useMutation({
		mutationFn: (params: {
			parent_a_id: string;
			parent_b_id: string;
			mode: string;
			mutation_rate: number;
		}) =>
			apiClient<BreedResponse>("/strategies/breed", {
				method: "POST",
				body: JSON.stringify(params),
			}),
		onSuccess: (data) => {
			toast.success(
				<div>
					<div className="font-bold">
						{t("breedingLab.toast_hybrid_created_title")}
					</div>
					<div className="text-sm">{data.suggested_name}</div>
				</div>,
			);
		},
		onError: (error: Error) => {
			toast.error(t("breedingLab.toast_failed_to_breed"), {
				description: error.message,
			});
		},
	});

	const handleBreed = () => {
		if (!parentAId || !parentBId) {
			toast.error(t("breedingLab.toast_select_both_parents"));
			return;
		}

		if (parentAId === parentBId) {
			toast.error(t("breedingLab.toast_select_different_parents"));
			return;
		}

		breedMutation.mutate({
			parent_a_id: parentAId,
			parent_b_id: parentBId,
			mode,
			mutation_rate: mutationRate,
		});
	};

	const selectedMode = breedingModes.find((m) => m.value === mode);

	return (
		<div className="space-y-6">
			{/* Instructions */}
			<Card className="bg-gradient-to-br from-purple-500/10 to-pink-500/10 border-purple-500/20">
				<CardHeader>
					<CardTitle className="flex items-center gap-2">
						<Shuffle className="w-5 h-5 text-purple-500" />
						{t("breedingLab.title")}
					</CardTitle>
					<CardDescription>{t("breedingLab.description")}</CardDescription>
				</CardHeader>
				<CardContent>
					<Alert>
						<AlertCircle className="h-4 w-4" />
						<AlertDescription>
							{t("breedingLab.alert_description")}
						</AlertDescription>
					</Alert>
				</CardContent>
			</Card>

			<div className="grid md:grid-cols-2 gap-6">
				<Card>
					<CardHeader className="pb-3">
						<CardTitle className="text-base">
							{t("breedingLab.parent_a_title")}
						</CardTitle>
						<CardDescription>{t("breedingLab.parent_a_desc")}</CardDescription>
					</CardHeader>
					<CardContent>
						<Select
							value={parentAId}
							onValueChange={setParentAId}
							disabled={strategiesLoading}
						>
							<SelectTrigger>
								<SelectValue
									placeholder={t("breedingLab.select_strategy_placeholder")}
								/>
							</SelectTrigger>
							<SelectContent>
								{strategiesData?.map((strategy) => (
									<SelectItem key={strategy.id} value={strategy.id}>
										{strategy.name}
									</SelectItem>
								))}
							</SelectContent>
						</Select>
						{parentAId && (
							<div className="mt-2">
								<Badge variant="outline">
									{t("breedingLab.selected_badge")}
								</Badge>
							</div>
						)}
					</CardContent>
				</Card>

				<Card>
					<CardHeader className="pb-3">
						<CardTitle className="text-base">
							{t("breedingLab.parent_b_title")}
						</CardTitle>
						<CardDescription>{t("breedingLab.parent_b_desc")}</CardDescription>
					</CardHeader>
					<CardContent>
						<Select
							value={parentBId}
							onValueChange={setParentBId}
							disabled={strategiesLoading}
						>
							<SelectTrigger>
								<SelectValue
									placeholder={t("breedingLab.select_strategy_placeholder")}
								/>
							</SelectTrigger>
							<SelectContent>
								{strategiesData?.map((strategy) => (
									<SelectItem key={strategy.id} value={strategy.id}>
										{strategy.name}
									</SelectItem>
								))}
							</SelectContent>
						</Select>
						{parentBId && (
							<div className="mt-2">
								<Badge variant="outline">
									{t("breedingLab.selected_badge")}
								</Badge>
							</div>
						)}
					</CardContent>
				</Card>
			</div>

			{/* Breeding Mode Selection */}
			<Card>
				<CardHeader>
					<CardTitle className="text-base">
						{t("breedingLab.breeding_mode_title")}
					</CardTitle>
					<CardDescription>
						{t("breedingLab.breeding_mode_desc")}
					</CardDescription>
				</CardHeader>
				<CardContent className="space-y-4">
					<Select value={mode} onValueChange={setMode}>
						<SelectTrigger>
							<SelectValue />
						</SelectTrigger>
						<SelectContent>
							{breedingModes.map((m) => (
								<SelectItem key={m.value} value={m.value}>
									{m.label}
								</SelectItem>
							))}
						</SelectContent>
					</Select>

					{selectedMode && (
						<Alert>
							<AlertDescription>{selectedMode.description}</AlertDescription>
						</Alert>
					)}

					{/* Mutation Rate */}
					<div className="space-y-2">
						<label className="text-sm font-medium">
							{t("breedingLab.mutation_rate_label", {
								rate: (mutationRate * 100).toFixed(0),
							})}
						</label>
						<input
							type="range"
							min="0"
							max="100"
							value={mutationRate * 100}
							onChange={(e) =>
								setMutationRate(parseInt(e.target.value, 10) / 100)
							}
							className="w-full"
						/>
						<p className="text-xs text-muted-foreground">
							{t("breedingLab.mutation_rate_desc")}
						</p>
					</div>
				</CardContent>
			</Card>

			{/* Breed Button */}
			<Card>
				<CardContent className="pt-6">
					<Button
						onClick={handleBreed}
						disabled={!parentAId || !parentBId || breedMutation.isPending}
						size="lg"
						className="w-full bg-gradient-to-r from-purple-500 to-pink-500 hover:from-purple-600 hover:to-pink-600"
					>
						{breedMutation.isPending ? (
							<>
								<Loader2 className="w-4 h-4 mr-2 animate-spin" />
								{t("breedingLab.breeding_button_pending")}
							</>
						) : (
							<>
								<Shuffle className="w-4 h-4 mr-2" />
								{t("breedingLab.breeding_button_cta")}
							</>
						)}
					</Button>
				</CardContent>
			</Card>

			{/* Result */}
			{breedMutation.isSuccess && breedMutation.data && (
				<Card className="border-green-500/50 bg-green-500/10">
					<CardHeader>
						<CardTitle className="flex items-center gap-2 text-green-500">
							<CheckCircle className="w-5 h-5" />
							{t("breedingLab.result_success_title")}
						</CardTitle>
						<CardDescription>
							{breedMutation.data.suggested_name}
						</CardDescription>
					</CardHeader>
					<CardContent className="space-y-4">
						<div className="grid grid-cols-2 gap-4 text-sm">
							<div>
								<span className="text-muted-foreground">
									{t("breedingLab.result_parent_a_label")}
								</span>
								<div className="font-medium">
									{breedMutation.data.parent_a_name}
								</div>
							</div>
							<div>
								<span className="text-muted-foreground">
									{t("breedingLab.result_parent_b_label")}
								</span>
								<div className="font-medium">
									{breedMutation.data.parent_b_name}
								</div>
							</div>
							<div>
								<span className="text-muted-foreground">
									{t("breedingLab.result_mode_label")}
								</span>
								<div className="font-medium">
									{
										breedingModes.find(
											(m) => m.value === breedMutation.data.mode,
										)?.label
									}
								</div>
							</div>
						</div>

						<Alert>
							<AlertDescription>
								{t("breedingLab.result_alert_desc")}
							</AlertDescription>
						</Alert>

						<div className="flex gap-2">
							<Button
								variant="outline"
								onClick={() => {
									// TODO: Open strategy editor with hybrid config
									toast.info(t("breedingLab.toast_editor_soon"));
								}}
							>
								{t("breedingLab.open_in_editor_button")}
							</Button>
							<Button
								onClick={() => {
									// TODO: Start backtest with hybrid config
									toast.info(t("breedingLab.toast_backtest_soon"));
								}}
							>
								{t("breedingLab.run_backtest_button")}
							</Button>
						</div>
					</CardContent>
				</Card>
			)}
		</div>
	);
};
