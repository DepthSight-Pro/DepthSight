// src/components/research/PortfolioContractForm.tsx

import { Trash2 as TrashIcon } from "lucide-react";
import type React from "react";
import {
	Controller,
	type FieldError,
	type UseFormReturn,
} from "react-hook-form";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
	Select,
	SelectContent,
	SelectItem,
	SelectTrigger,
	SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { useStrategyConfigsList } from "@/lib/api";
import type { StrategyConfigSummary } from "@/types/api";
import { FormMessage } from "../ui/form";
import type { PortfolioBacktestFormValues } from "./LaunchTaskForm";

interface PortfolioContractFormProps {
	nestIndex: number;
	remove: (index: number) => void;
	formMethods: UseFormReturn<PortfolioBacktestFormValues>;
}

export const PortfolioContractForm: React.FC<PortfolioContractFormProps> = ({
	nestIndex,
	remove,
	formMethods,
}) => {
	const { t } = useTranslation("research");
	const { data: strategyConfigs, isLoading, error } = useStrategyConfigsList();

	const {
		control,
		formState: { errors },
	} = formMethods;

	// Check that errors.contracts is an array before accessing it by index.
	// This helps TypeScript understand that we are working with an array.
	const contractErrors = (
		Array.isArray(errors.contracts) ? errors.contracts[nestIndex] : undefined
	) as { [key: string]: FieldError } | undefined; // Clarifying the type for convenience

	if (isLoading) return <p>{t("loadingStrategyConfigs")}</p>;
	if (error)
		return (
			<p>{t("errorLoadingStrategyConfigs", { message: error.message })}</p>
		);
	if (!strategyConfigs) return <p>{t("noStrategyConfigsFound")}</p>;

	return (
		<div className="p-4 border rounded-md space-y-4 relative bg-secondary/30">
			<div className="flex justify-between items-center">
				<h4 className="font-semibold">
					{t("launchForm.contractTitle", { index: nestIndex + 1 })}
				</h4>
				<Button
					type="button"
					variant="ghost"
					size="icon"
					onClick={() => remove(nestIndex)}
					className="h-7 w-7 text-destructive"
				>
					<TrashIcon className="h-4 w-4" />
				</Button>
			</div>

			<div>
				<Label htmlFor={`contracts.${nestIndex}.strategy_name`}>
					{t("launchForm.strategyConfigurationLabel")}
				</Label>
				<Controller
					name={`contracts.${nestIndex}.strategy_name`}
					control={control}
					rules={{ required: t("validationStrategyConfigRequired") }}
					render={({ field }) => (
						<Select onValueChange={field.onChange} defaultValue={field.value}>
							<SelectTrigger>
								<SelectValue
									placeholder={t("launchForm.strategyConfigurationPlaceholder")}
								/>
							</SelectTrigger>
							<SelectContent>
								{strategyConfigs.map((config: StrategyConfigSummary) => (
									<SelectItem key={config.id} value={config.name}>
										{config.name}
									</SelectItem>
								))}
							</SelectContent>
						</Select>
					)}
				/>
				{/* Now access to contractErrors.strategy_name is safe */}
				{contractErrors?.strategy_name && (
					<FormMessage className="text-xs">
						{contractErrors.strategy_name.message}
					</FormMessage>
				)}
			</div>

			<div>
				<Label htmlFor={`contracts.${nestIndex}.symbol`}>
					{t("launchForm.symbolLabel")}
				</Label>
				<Controller
					name={`contracts.${nestIndex}.symbol`}
					control={control}
					rules={{ required: t("validationSymbolRequired") }}
					render={({ field }) => (
						<Input {...field} placeholder={t("launchForm.symbolPlaceholder")} />
					)}
				/>
				{contractErrors?.symbol && (
					<FormMessage className="text-xs">
						{contractErrors.symbol.message}
					</FormMessage>
				)}
			</div>

			<div>
				<Label htmlFor={`contracts.${nestIndex}.params`}>
					{t("launchForm.parameterOverridesLabel")}
				</Label>
				<Controller
					name={`contracts.${nestIndex}.params`}
					control={control}
					render={({ field }) => (
						<Textarea
							{...field}
							placeholder={t("launchForm.parameterOverridesPlaceholder")}
							rows={3}
						/>
					)}
				/>
				<p className="text-sm text-muted-foreground mt-1">
					{t("launchForm.parameterOverridesDesc")}
				</p>
				{contractErrors?.params && (
					<FormMessage className="text-xs">
						{contractErrors.params.message}
					</FormMessage>
				)}
			</div>
		</div>
	);
};

export default PortfolioContractForm;
