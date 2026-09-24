// src/components/settings/AddApiKeyModal.tsx

import { zodResolver } from "@hookform/resolvers/zod";
import { Key, Loader2 } from "lucide-react";
import React from "react";
import { useForm, useWatch } from "react-hook-form";
import { useTranslation } from "react-i18next";
import * as z from "zod";
import { ExchangeBadge } from "@/components/layout/AccountSelector";
import { useAuth } from "@/context/AuthContext";
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
	const { user } = useAuth();
	// Testnet keys can only be added by admins; regular users trade live only.
	const isAdmin = user?.role === "admin";

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
				)
				.refine(
					(data) => {
						if (
							data.exchange.startsWith("weex") &&
							(!data.api_password || data.api_password.trim() === "")
						) {
							return false;
						}
						return true;
					},
					{
						message: "Passphrase is required for WEEX",
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
		selectedExchange.startsWith("okx") ||
		selectedExchange.startsWith("weex");
	const isGateioSelected = selectedExchange.startsWith("gateio");

	React.useEffect(() => {
		if (selectedExchange === "weex" || !isAdmin) {
			form.setValue("isTestnet", false);
		}
	}, [selectedExchange, form, isAdmin]);

	const onSubmit = (values: FormValues) => {
		const effectiveIsTestnet = isAdmin ? values.isTestnet : false;
		const payload: AddApiKeyPayload = {
			name: values.name,
			exchange: effectiveIsTestnet
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
			<DialogContent className="sm:max-w-[480px] bg-obsidian/90 border border-white/10 text-white shadow-2xl backdrop-blur-2xl rounded-2xl sm:rounded-2xl p-6 overflow-hidden">
				{/* Ambient glow */}
				<div className="pointer-events-none absolute -top-16 -right-16 h-48 w-48 rounded-full bg-cyan/15 blur-3xl" />
				<div className="pointer-events-none absolute -bottom-16 -left-16 h-48 w-48 rounded-full bg-azure/10 blur-3xl" />

				<DialogHeader className="relative pb-1">
					<DialogTitle className="text-lg font-semibold text-white tracking-tight flex items-center gap-2.5">
						<div className="flex h-8 w-8 items-center justify-center rounded-xl bg-cyan/10 border border-cyan/30 text-cyan shadow-sm">
							<Key className="h-4 w-4" />
						</div>
						<span>{t("apiKeys.addModal.title")}</span>
					</DialogTitle>
				</DialogHeader>
				<Form {...form}>
					<form onSubmit={handleSubmit(onSubmit)} className="space-y-4 py-2 relative z-10">
						<FormField
							control={control}
							name="name"
							render={({ field }) => (
								<FormItem>
									<FormLabel className="text-xs font-medium text-white/80">{t("apiKeys.addModal.nameLabel")}</FormLabel>
									<FormControl>
										<Input
											placeholder={t("apiKeys.addModal.namePlaceholder")}
											{...field}
											value={field.value as string}
											className="rounded-xl bg-white/[0.04] border-white/10 text-white placeholder:text-white/30 focus:border-cyan/50 focus:ring-1 focus:ring-cyan/30 h-10 transition-colors"
										/>
									</FormControl>
									<FormMessage className="text-xs text-rose-400" />
								</FormItem>
							)}
						/>
						<FormField
							control={control}
							name="exchange"
							render={({ field }) => (
								<FormItem>
									<FormLabel className="text-xs font-medium text-white/80">{t("apiKeys.addModal.exchangeLabel")}</FormLabel>
									<Select
										onValueChange={field.onChange}
										defaultValue={field.value as string}
										value={field.value as string}
									>
										<FormControl>
											<SelectTrigger className="rounded-xl bg-white/[0.04] border-white/10 text-white focus:border-cyan/50 focus:ring-1 focus:ring-cyan/30 h-10 transition-colors">
												<SelectValue
													placeholder={t("apiKeys.addModal.selectExchange")}
												/>
											</SelectTrigger>
										</FormControl>
										<SelectContent className="rounded-xl bg-obsidian/95 border border-white/10 text-white backdrop-blur-2xl shadow-2xl p-1">
											<SelectItem value="binance" className="rounded-lg py-2 pl-9 pr-3 text-xs sm:text-sm text-white/90 focus:bg-white/[0.08] focus:text-white cursor-pointer transition-colors">
												<div className="flex items-center gap-2.5">
													<ExchangeBadge exchange="binance" size="sm" />
													<span className="font-medium">Binance</span>
												</div>
											</SelectItem>
											<SelectItem value="bybit" className="rounded-lg py-2 pl-9 pr-3 text-xs sm:text-sm text-white/90 focus:bg-white/[0.08] focus:text-white cursor-pointer transition-colors">
												<div className="flex items-center gap-2.5">
													<ExchangeBadge exchange="bybit" size="sm" />
													<span className="font-medium">Bybit</span>
												</div>
											</SelectItem>
											<SelectItem value="okx" className="rounded-lg py-2 pl-9 pr-3 text-xs sm:text-sm text-white/90 focus:bg-white/[0.08] focus:text-white cursor-pointer transition-colors">
												<div className="flex items-center gap-2.5">
													<ExchangeBadge exchange="okx" size="sm" />
													<span className="font-medium">OKX</span>
												</div>
											</SelectItem>
											<SelectItem value="bitget" className="rounded-lg py-2 pl-9 pr-3 text-xs sm:text-sm text-white/90 focus:bg-white/[0.08] focus:text-white cursor-pointer transition-colors">
												<div className="flex items-center gap-2.5">
													<ExchangeBadge exchange="bitget" size="sm" />
													<span className="font-medium">Bitget</span>
												</div>
											</SelectItem>
											<SelectItem value="gateio" disabled className="rounded-lg py-2 pl-9 pr-3 text-xs sm:text-sm text-white/90 focus:bg-white/[0.08] focus:text-white cursor-pointer transition-colors opacity-50">
												<div className="flex items-center gap-2.5">
													<ExchangeBadge exchange="gateio" size="sm" />
													<span className="font-medium">Gate.io</span>
												</div>
											</SelectItem>
											<SelectItem value="bingx" disabled className="rounded-lg py-2 pl-9 pr-3 text-xs sm:text-sm text-white/90 focus:bg-white/[0.08] focus:text-white cursor-pointer transition-colors opacity-50">
												<div className="flex items-center gap-2.5">
													<ExchangeBadge exchange="bingx" size="sm" />
													<span className="font-medium">BingX</span>
												</div>
											</SelectItem>
											<SelectItem value="weex" className="rounded-lg py-2 pl-9 pr-3 text-xs sm:text-sm text-white/90 focus:bg-white/[0.08] focus:text-white cursor-pointer transition-colors">
												<div className="flex items-center gap-2.5">
													<ExchangeBadge exchange="weex" size="sm" />
													<span className="font-medium">WEEX</span>
												</div>
											</SelectItem>
										</SelectContent>
									</Select>
									<FormMessage className="text-xs text-rose-400" />
								</FormItem>
							)}
						/>
					{isAdmin && selectedExchange !== "weex" && (
						<FormField
							control={control}
							name="isTestnet"
								render={({ field }) => (
									<FormItem className="flex flex-row items-center justify-between rounded-xl border border-white/10 bg-white/[0.02] p-3 shadow-sm">
										<div className="space-y-0.5">
											<FormLabel className="text-xs font-medium text-white/90">Testnet Mode</FormLabel>
											<div className="text-[11px] text-white/40">
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
						)}
						<FormField
							control={control}
							name="api_key"
							render={({ field }) => (
								<FormItem>
									<FormLabel className="text-xs font-medium text-white/80">{t("apiKeys.addModal.keyLabel")}</FormLabel>
									<FormControl>
										<Input
											placeholder={t("apiKeys.addModal.keyPlaceholder")}
											{...field}
											value={field.value as string}
											className="rounded-xl bg-white/[0.04] border-white/10 text-white placeholder:text-white/30 focus:border-cyan/50 focus:ring-1 focus:ring-cyan/30 h-10 transition-colors font-mono text-xs"
										/>
									</FormControl>
									<FormMessage className="text-xs text-rose-400" />
								</FormItem>
							)}
						/>
						<FormField
							control={control}
							name="api_secret"
							render={({ field }) => (
								<FormItem>
									<FormLabel className="text-xs font-medium text-white/80">{t("apiKeys.addModal.secretLabel")}</FormLabel>
									<FormControl>
										<Input
											type="password"
											placeholder={t("apiKeys.addModal.secretPlaceholder")}
											{...field}
											value={field.value as string}
											className="rounded-xl bg-white/[0.04] border-white/10 text-white placeholder:text-white/30 focus:border-cyan/50 focus:ring-1 focus:ring-cyan/30 h-10 transition-colors font-mono text-xs"
										/>
									</FormControl>
									<FormMessage className="text-xs text-rose-400" />
								</FormItem>
							)}
						/>
						{needsExtraCredential && (
							<FormField
								control={control}
								name="api_password"
								render={({ field }) => (
									<FormItem>
										<FormLabel className="text-xs font-medium text-white/80">
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
												className="rounded-xl bg-white/[0.04] border-white/10 text-white placeholder:text-white/30 focus:border-cyan/50 focus:ring-1 focus:ring-cyan/30 h-10 transition-colors font-mono text-xs"
											/>
										</FormControl>
										<FormMessage className="text-xs text-rose-400" />
									</FormItem>
								)}
							/>
						)}
						<DialogFooter className="pt-2 gap-2">
							<DialogClose asChild>
								<Button
									type="button"
									variant="outline"
									onClick={onClose}
									disabled={isLoading}
									className="rounded-xl border-white/10 bg-white/[0.04] text-white/70 hover:bg-white/[0.08] hover:text-white transition-colors"
								>
									{t("apiKeys.addModal.cancelButton")}
								</Button>
							</DialogClose>
							<Button
								type="submit"
								disabled={isLoading}
								className="rounded-xl bg-gradient-to-r from-azure to-cyan text-white font-semibold shadow-[0_0_20px_-3px_rgba(0,212,255,0.6)] hover:shadow-[0_0_25px_-2px_rgba(0,212,255,0.8)] transition-all"
							>
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
