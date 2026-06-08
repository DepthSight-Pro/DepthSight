// src/components/settings/AddApiKeyModal.tsx

import { zodResolver } from "@hookform/resolvers/zod";
import { Loader2 } from "lucide-react";
import React from "react";
import { useForm, useWatch } from "react-hook-form";
import { useTranslation } from "react-i18next"; // Import useTranslation
import * as z from "zod";
import { Button } from "@/components/ui/button";
import {
	Dialog,
	DialogClose,
	DialogContent,
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
	Select,
	SelectContent,
	SelectItem,
	SelectTrigger,
	SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import type { AddApiKeyPayload } from "@/types/api";

interface FormValues {
	name: string;
	exchange: string;
	api_key: string;
	api_secret: string;
	api_password?: string;
	isTestnet: boolean;
}

interface AddApiKeyModalProps {
	isOpen: boolean;
	onClose: () => void;
	onAdd: (data: AddApiKeyPayload) => void;
	isLoading: boolean;
}

export const AddApiKeyModal: React.FC<AddApiKeyModalProps> = ({
	isOpen,
	onClose,
	onAdd,
	isLoading,
}) => {
	const { t } = useTranslation("settings");

	// We create the validation schema inside to use 't' for error messages
	const validationSchema = React.useMemo(
		() =>
			z
				.object({
					name: z
						.string()
						.min(1, { message: t("apiKeys.addModal.errors.nameRequired") }),
					exchange: z
						.string()
						.min(1, { message: t("apiKeys.addModal.errors.exchangeRequired") }),
					api_key: z
						.string()
						.min(1, { message: t("apiKeys.addModal.errors.apiKeyRequired") }),
					api_secret: z.string().min(1, {
						message: t("apiKeys.addModal.errors.apiSecretRequired"),
					}),
					api_password: z.string().optional(),
					isTestnet: z.boolean(),
				})
				.refine(
					(data) => {
						if (
							data.exchange.startsWith("bitget") &&
							(!data.api_password || data.api_password.trim() === "")
						) {
							return false;
						}
						return true;
					},
					{
						message: "Passphrase is required for Bitget",
						path: ["api_password"],
					},
				)
				.refine(
					(data) => {
						if (
							data.exchange.startsWith("gateio") &&
							(!data.api_password || data.api_password.trim() === "")
						) {
							return false;
						}
						return true;
					},
					{
						message: "UID is required for Gate.io futures private streams",
						path: ["api_password"],
					},
				)
				.refine(
					(data) => {
						if (
							data.exchange.startsWith("okx") &&
							(!data.api_password || data.api_password.trim() === "")
						) {
							return false;
						}
						return true;
					},
					{
						message: "Passphrase is required for OKX",
						path: ["api_password"],
					},
				),
		[t],
	);

	const form = useForm<FormValues>({
		resolver: zodResolver(validationSchema),
		defaultValues: {
			name: "",
			exchange: "binance",
			api_key: "",
			api_secret: "",
			api_password: "",
			isTestnet: false,
		},
	});

	const { handleSubmit, control, reset } = form;
	const selectedExchange = useWatch({ control, name: "exchange" }) || "";
	const needsExtraCredential =
		selectedExchange.startsWith("bitget") ||
		selectedExchange.startsWith("gateio") ||
		selectedExchange.startsWith("okx");
	const isGateioSelected = selectedExchange.startsWith("gateio");

	const onSubmit = (values: FormValues) => {
		const payload: AddApiKeyPayload = {
			name: values.name,
			exchange: values.isTestnet
				? `${values.exchange}_testnet`
				: values.exchange,
			api_key: values.api_key,
			api_secret: values.api_secret,
			api_password: values.api_password,
		};
		onAdd(payload);
	};

	React.useEffect(() => {
		if (isOpen) {
			reset({
				name: "",
				exchange: "binance",
				api_key: "",
				api_secret: "",
				api_password: "",
				isTestnet: false,
			});
		}
	}, [isOpen, reset]);

	return (
		<Dialog
			open={isOpen}
			onOpenChange={(open) => {
				if (!open) onClose();
			}}
		>
			<DialogContent className="sm:max-w-[480px]">
				<DialogHeader>
					<DialogTitle>{t("apiKeys.addModal.title")}</DialogTitle>
					{/* DialogDescription can be added if needed, using a key like 'apiKeys.addModal.description' */}
				</DialogHeader>
				<Form {...form}>
					<form onSubmit={handleSubmit(onSubmit)} className="space-y-4 py-4">
						<FormField
							control={control}
							name="name"
							render={({ field }) => (
								<FormItem>
									<FormLabel>{t("apiKeys.addModal.nameLabel")}</FormLabel>
									<FormControl>
										<Input
											placeholder={t("apiKeys.addModal.namePlaceholder")}
											{...field}
											value={field.value as string}
										/>
									</FormControl>
									<FormMessage />
								</FormItem>
							)}
						/>
						<FormField
							control={control}
							name="exchange"
							render={({ field }) => (
								<FormItem>
									<FormLabel>{t("apiKeys.addModal.exchangeLabel")}</FormLabel>
									<Select
										onValueChange={field.onChange}
										defaultValue={field.value as string}
										value={field.value as string}
									>
										<FormControl>
											<SelectTrigger>
												<SelectValue
													placeholder={t("apiKeys.addModal.selectExchange")}
												/>
											</SelectTrigger>
										</FormControl>
										<SelectContent>
											<SelectItem value="binance">Binance</SelectItem>
											<SelectItem value="bybit">Bybit</SelectItem>
											<SelectItem value="okx">OKX</SelectItem>
											<SelectItem value="bitget">Bitget</SelectItem>
											<SelectItem value="gateio">Gate.io</SelectItem>
											<SelectItem value="bingx">BingX</SelectItem>
										</SelectContent>
									</Select>
									<FormMessage />
								</FormItem>
							)}
						/>
						<FormField
							control={control}
							name="isTestnet"
							render={({ field }) => (
								<FormItem className="flex flex-row items-center justify-between rounded-lg border p-3 shadow-sm">
									<div className="space-y-0.5">
										<FormLabel>Testnet Mode</FormLabel>
										<div className="text-[0.7rem] text-muted-foreground">
											Use testnet environment for this account
										</div>
									</div>
									<FormControl>
										<Switch
											checked={field.value as boolean}
											onCheckedChange={field.onChange}
										/>
									</FormControl>
								</FormItem>
							)}
						/>
						<FormField
							control={control}
							name="api_key"
							render={({ field }) => (
								<FormItem>
									<FormLabel>{t("apiKeys.addModal.keyLabel")}</FormLabel>
									<FormControl>
										<Input
											placeholder={t("apiKeys.addModal.apiKeyPlaceholder")}
											{...field}
											value={field.value as string}
										/>
									</FormControl>
									<FormMessage />
								</FormItem>
							)}
						/>
						<FormField
							control={control}
							name="api_secret"
							render={({ field }) => (
								<FormItem>
									<FormLabel>{t("apiKeys.addModal.secretLabel")}</FormLabel>
									<FormControl>
										<Input
											type="password"
											placeholder={t("apiKeys.addModal.secretPlaceholder")}
											{...field}
											value={field.value as string}
										/>
									</FormControl>
									<FormMessage />
								</FormItem>
							)}
						/>
						{needsExtraCredential && (
							<FormField
								control={control}
								name="api_password"
								render={({ field }) => (
									<FormItem>
										<FormLabel>
											{isGateioSelected
												? "Gate.io UID"
												: "Passphrase (Password)"}
										</FormLabel>
										<FormControl>
											<Input
												type="password"
												placeholder={
													isGateioSelected ? "Numeric UID" : "API Passphrase"
												}
												{...field}
												value={field.value as string}
											/>
										</FormControl>
										<FormMessage />
									</FormItem>
								)}
							/>
						)}
						<DialogFooter>
							<DialogClose asChild>
								<Button
									type="button"
									variant="outline"
									onClick={onClose}
									disabled={isLoading}
								>
									{t("apiKeys.addModal.cancelButton")}
								</Button>
							</DialogClose>
							<Button type="submit" disabled={isLoading}>
								{isLoading ? (
									<Loader2 className="mr-2 h-4 w-4 animate-spin" />
								) : null}
								{isLoading
									? t("common:loading")
									: t("apiKeys.addModal.addButton")}
							</Button>
						</DialogFooter>
					</form>
				</Form>
			</DialogContent>
		</Dialog>
	);
};
