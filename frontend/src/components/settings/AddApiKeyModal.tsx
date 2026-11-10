// src/components/settings/AddApiKeyModal.tsx

import { zodResolver } from "@hookform/resolvers/zod";
import {
	Calculator,
	Flame,
	Key,
	Loader2,
	Shield,
	Sparkles,
	Zap,
} from "lucide-react";
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
	builder_fee_rate?: string;
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

	const [simVolume, setSimVolume] = React.useState<number>(10000);

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
					builder_fee_rate: z.string().optional(),
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
			builder_fee_rate: "0.05%",
			isTestnet: false,
		},
	});

	const { handleSubmit, control, reset, setValue } = form;
	const selectedExchange = useWatch({ control, name: "exchange" }) || "";
	const needsExtraCredential =
		selectedExchange.startsWith("bitget") ||
		selectedExchange.startsWith("gateio") ||
		selectedExchange.startsWith("okx") ||
		selectedExchange.startsWith("weex");
	const isGateioSelected = selectedExchange.startsWith("gateio");
	const isHyperliquidSelected = selectedExchange === "hyperliquid";
	const isTestnetSelected = useWatch({ control, name: "isTestnet" });
	const selectedFeeRate = useWatch({ control, name: "builder_fee_rate" }) || "0.05%";

	React.useEffect(() => {
		if (selectedExchange === "weex" || !isAdmin) {
			form.setValue("isTestnet", false);
		}
	}, [selectedExchange, form, isAdmin]);

	const onSubmit = (values: FormValues) => {
		const effectiveIsTestnet = isAdmin ? values.isTestnet : false;
		const isHl = values.exchange === "hyperliquid";
		const effectiveFeeRate = isHl ? (values.builder_fee_rate || "0.05%") : undefined;
		const payload: AddApiKeyPayload = {
			name: values.name,
			exchange: effectiveIsTestnet
				? `${values.exchange}_testnet`
				: values.exchange,
			api_key: values.api_key,
			api_secret: values.api_secret,
			api_password: isHl ? effectiveFeeRate : values.api_password,
			builder_fee_rate: effectiveFeeRate,
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
				builder_fee_rate: "0.05%",
				isTestnet: false,
			});
			setSimVolume(10000);
		}
	}, [isOpen, reset]);

	const HL_TIERS = [
		{
			rate: "0.01%",
			rateNum: 0.0001,
			multiplier: "1x",
			title: t("apiKeys.addModal.hyperliquidTier.lowCost.title"),
			badge: t("apiKeys.addModal.hyperliquidTier.lowCost.badge"),
			desc: t("apiKeys.addModal.hyperliquidTier.lowCost.desc"),
			icon: Shield,
			accentColor: "text-blue-400",
			activeBg: "border-blue-500/50 bg-blue-500/10 shadow-[0_0_15px_-3px_rgba(59,130,246,0.3)]",
		},
		{
			rate: "0.05%",
			rateNum: 0.0005,
			multiplier: "5x",
			title: t("apiKeys.addModal.hyperliquidTier.standard.title"),
			badge: t("apiKeys.addModal.hyperliquidTier.standard.badge"),
			desc: t("apiKeys.addModal.hyperliquidTier.standard.desc"),
			icon: Sparkles,
			accentColor: "text-cyan",
			activeBg: "border-cyan/60 bg-cyan/10 shadow-[0_0_18px_-3px_rgba(0,212,255,0.35)]",
			isDefault: true,
		},
		{
			rate: "0.10%",
			rateNum: 0.0010,
			multiplier: "10x",
			title: t("apiKeys.addModal.hyperliquidTier.degen.title"),
			badge: t("apiKeys.addModal.hyperliquidTier.degen.badge"),
			desc: t("apiKeys.addModal.hyperliquidTier.degen.desc"),
			icon: Flame,
			accentColor: "text-amber-400",
			activeBg: "border-amber-500/60 bg-amber-500/10 shadow-[0_0_18px_-3px_rgba(245,158,11,0.35)]",
		},
	];

	const activeTier =
		HL_TIERS.find((tier) => tier.rate === selectedFeeRate) || HL_TIERS[1];
	const simulatedFee = simVolume * activeTier.rateNum;
	const simulatedPoints = simulatedFee; // 1 USD rebate = 1 base mining point

	return (
		<Dialog
			open={isOpen}
			onOpenChange={(open) => {
				if (!open) onClose();
			}}
		>
			<DialogContent className="sm:max-w-[520px] max-h-[92vh] overflow-y-auto pr-3 bg-obsidian/95 border border-white/10 text-white shadow-2xl backdrop-blur-2xl rounded-2xl p-6">
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
									<FormLabel className="text-xs font-medium text-white/80">
										{t("apiKeys.addModal.nameLabel")}
									</FormLabel>
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
									<FormLabel className="text-xs font-medium text-white/80">
										{t("apiKeys.addModal.exchangeLabel")}
									</FormLabel>
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
											<SelectItem value="weex" className="rounded-lg py-2 pl-9 pr-3 text-xs sm:text-sm text-white/90 focus:bg-white/[0.08] focus:text-white cursor-pointer transition-colors">
												<div className="flex items-center gap-2.5">
													<ExchangeBadge exchange="weex" size="sm" />
													<span className="font-medium">WEEX</span>
												</div>
											</SelectItem>
											<SelectItem value="hyperliquid" className="rounded-lg py-2 pl-9 pr-3 text-xs sm:text-sm text-white/90 focus:bg-white/[0.08] focus:text-white cursor-pointer transition-colors">
												<div className="flex items-center gap-2.5">
													<ExchangeBadge exchange="hyperliquid" size="sm" />
													<span className="font-medium">Hyperliquid</span>
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
						{isHyperliquidSelected && (
							<div className="rounded-xl border border-emerald-500/30 bg-emerald-500/10 p-3 text-[11px] text-emerald-200/90 leading-relaxed">
								<p className="font-semibold text-emerald-300 mb-1">
									Hyperliquid API Agent Keys {isTestnetSelected ? "(Testnet)" : "(Mainnet)"}
								</p>
								Use your main <strong>Wallet Address</strong> and an <strong>Agent Private Key</strong> (generated on {isTestnetSelected ? "app.hyperliquid-testnet.xyz" : "app.hyperliquid.xyz"} under More → API). Agent keys can only place orders and cannot withdraw funds. Never input your primary wallet seed phrase or private key.
							</div>
						)}
						<FormField
							control={control}
							name="api_key"
							render={({ field }) => (
								<FormItem>
									<FormLabel className="text-xs font-medium text-white/80">
										{isHyperliquidSelected
											? "Wallet Address (0x...)"
											: t("apiKeys.addModal.keyLabel")}
									</FormLabel>
									<FormControl>
										<Input
											placeholder={
												isHyperliquidSelected
													? "0x..."
													: t("apiKeys.addModal.keyPlaceholder")
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
						<FormField
							control={control}
							name="api_secret"
							render={({ field }) => (
								<FormItem>
									<FormLabel className="text-xs font-medium text-white/80">
										{isHyperliquidSelected
											? "Agent Private Key (0x...)"
											: t("apiKeys.addModal.secretLabel")}
									</FormLabel>
									<FormControl>
										<Input
											type="password"
											placeholder={
												isHyperliquidSelected
													? "0x..."
													: t("apiKeys.addModal.secretPlaceholder")
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
						{isHyperliquidSelected && (
							<div className="rounded-xl border border-white/10 bg-white/[0.02] p-3.5 space-y-3.5">
								<div className="flex items-center justify-between">
									<div className="flex items-center gap-2">
										<Zap className="h-4 w-4 text-cyan" />
										<span className="text-xs font-semibold text-white/90">
											{t("apiKeys.addModal.hyperliquidTier.title")}
										</span>
									</div>
									<span className="text-[10px] font-mono uppercase tracking-wider text-cyan bg-cyan/10 border border-cyan/30 px-2 py-0.5 rounded-full">
										{activeTier.multiplier} Mining Speed
									</span>
								</div>
								<p className="text-[11px] text-white/60 leading-normal">
									{t("apiKeys.addModal.hyperliquidTier.subtitle")}
								</p>

								{/* Tier Selection Cards */}
								<div className="grid grid-cols-3 gap-2">
									{HL_TIERS.map((tier) => {
										const isSelected = selectedFeeRate === tier.rate;
										const IconComp = tier.icon;
										return (
											<button
												key={tier.rate}
												type="button"
												onClick={() => setValue("builder_fee_rate", tier.rate)}
												className={`flex flex-col items-center justify-between text-center p-2.5 rounded-xl border transition-all text-xs relative ${
													isSelected
														? tier.activeBg
														: "border-white/10 bg-white/[0.03] hover:border-white/20 hover:bg-white/[0.05] text-white/70"
												}`}
											>
												<div className="flex items-center gap-1.5 mb-1.5">
													<IconComp className={`h-3.5 w-3.5 ${tier.accentColor}`} />
													<span className="font-bold text-white text-[11px]">
														{tier.title}
													</span>
												</div>
												<div className="text-sm font-extrabold text-white tracking-tight my-0.5">
													{tier.rate}
												</div>
												<div className={`text-[10px] font-medium ${tier.accentColor} mb-1`}>
													{tier.multiplier} Power
												</div>
												<span className="text-[9px] px-1.5 py-0.5 rounded-md bg-white/5 border border-white/10 text-white/60 line-clamp-1">
													{tier.badge}
												</span>
											</button>
										);
									})}
								</div>

								{/* Interactive Simulation Strip */}
								<div className="rounded-lg border border-white/5 bg-white/[0.02] p-2.5 space-y-2">
									<div className="flex items-center justify-between text-[11px]">
										<span className="text-white/60 flex items-center gap-1.5">
											<Calculator className="h-3 w-3 text-white/40" />
											{t("apiKeys.addModal.hyperliquidTier.calculator.volumeLabel")}
										</span>
										<div className="flex items-center gap-1.5">
											{[5000, 10000, 50000].map((v) => (
												<button
													key={v}
													type="button"
													onClick={() => setSimVolume(v)}
													className={`text-[10px] px-2 py-0.5 rounded font-mono transition-colors ${
														simVolume === v
															? "bg-cyan/20 border border-cyan/40 text-cyan font-bold"
															: "bg-white/5 border border-white/10 text-white/50 hover:text-white"
													}`}
												>
													${(v / 1000).toFixed(0)}k
												</button>
											))}
										</div>
									</div>

									<div className="grid grid-cols-2 gap-2 pt-1 border-t border-white/5 text-[11px]">
										<div>
											<span className="text-white/50 block text-[10px]">
												{t("apiKeys.addModal.hyperliquidTier.calculator.feePaidLabel")}
											</span>
											<span className="font-mono font-semibold text-white/90">
												${simulatedFee.toFixed(2)} USDC
											</span>
										</div>
										<div className="text-right">
											<span className="text-white/50 block text-[10px]">
												{t("apiKeys.addModal.hyperliquidTier.calculator.pointsEarnedLabel")}
											</span>
											<span className={`font-mono font-bold ${activeTier.accentColor}`}>
												+{simulatedPoints.toFixed(2)} pts
											</span>
										</div>
									</div>

									<div className="text-[10px] text-white/40 italic pt-1 border-t border-white/5 flex items-center gap-1">
										<Flame className="h-2.5 w-2.5 text-amber-400 shrink-0" />
										<span>{t("apiKeys.addModal.hyperliquidTier.calculator.burnNotice")}</span>
									</div>
								</div>
							</div>
						)}
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
