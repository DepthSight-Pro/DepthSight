// src/components/shared/PricingModal.tsx

import { useQueryClient } from "@tanstack/react-query";
import {
	ArrowLeft,
	Bitcoin,
	Check,
	CheckCircle2,
	CircleDollarSign,
	Clock,
	Coins,
	Copy,
	Info,
	Layers,
	Loader2,
	PartyPopper,
	Sparkles,
	Terminal,
	Zap,
} from "lucide-react";
import type React from "react";
import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";

import {
	Card,
	CardContent,
	CardDescription,
	CardFooter,
	CardHeader,
	CardTitle,
} from "@/components/ui/card";
import {
	Dialog,
	DialogContent,
	DialogDescription,
	DialogHeader,
	DialogTitle,
} from "@/components/ui/dialog";
import { Skeleton } from "@/components/ui/skeleton";
import { useToast } from "@/components/ui/use-toast";
import {
	type BitcartPayment,
	type CreatePaymentResponse,
	type Plan,
	useCreatePayment,
	usePlans,
} from "@/lib/api";
import { apiClient } from "@/lib/apiClient";
import { cn } from "@/lib/utils";

interface PricingModalProps {
	isOpen: boolean;
	onClose: () => void;
	currentPlan: string;
}

const getCoinIcon = (currency: string, payment_method?: string) => {
	const c = currency.toUpperCase();
	const n = (payment_method || currency).toLowerCase();

	if (c === "BTC" || n === "btc")
		return <Bitcoin className="h-5 w-5 text-orange-500" />;
	if (c === "LTC" || n === "ltc")
		return <Coins className="h-5 w-5 text-blue-400" />;

	// Stablecoins / Tokens (Aggressive mapping for TRX/BNB/MATIC networks to USDT)
	if (
		c === "USDT" ||
		c === "USDC" ||
		n === "trx" ||
		n === "bnb" ||
		n === "matic"
	) {
		if (n === "trx")
			return <CircleDollarSign className="h-5 w-5 text-[#27A17C]" />; // USDT Green
		if (n === "bnb")
			return <CircleDollarSign className="h-5 w-5 text-[#F3BA2F]" />; // BNB Yellow
		if (n === "matic")
			return <CircleDollarSign className="h-5 w-5 text-[#8247E5]" />; // Matic Purple
		return <CircleDollarSign className="h-5 w-5 text-green-500" />;
	}
	return <Coins className="h-5 w-5 text-muted-foreground" />;
};

const getNetworkName = (currency: string, payment_method?: string) => {
	const n = (payment_method || currency).toLowerCase();
	switch (n) {
		case "trx":
			return "TRC-20";
		case "bnb":
			return "BEP-20 (BSC)";
		case "matic":
			return "Polygon";
		case "eth":
			return "ERC-20";
		case "btc":
			return "Bitcoin";
		case "ltc":
			return "Litecoin";
		default:
			return n.toUpperCase();
	}
};

const getCurrencyDisplay = (currency: string, payment_method?: string) => {
	const c = currency.toUpperCase();
	const n = (payment_method || currency).toLowerCase();

	// If the currency or network is TRX/BNB/MATIC, it's USDT in this context
	if (n === "trx" || n === "bnb" || n === "matic") return "USDT";
	return c;
};

// --- Bitcoin Checkout Screen ---
const PaymentCheckout: React.FC<{
	paymentData: CreatePaymentResponse;
	onBack: () => void;
	onSuccess: () => void;
}> = ({ paymentData, onBack, onSuccess }) => {
	const { t } = useTranslation("common");
	const { toast } = useToast();
	const [copied, setCopied] = useState<"address" | "amount" | null>(null);
	const [timeLeft, setTimeLeft] = useState(paymentData.expiration_seconds);
	const [isPaid, setIsPaid] = useState(false);
	const pollingInterval = useRef<ReturnType<typeof setInterval> | null>(null);
	const [selectedMethod, setSelectedMethod] = useState<BitcartPayment | null>(
		null,
	);
	const [prevPayments, setPrevPayments] = useState<
		BitcartPayment[] | undefined
	>(undefined);

	if (paymentData.payments !== prevPayments) {
		setPrevPayments(paymentData.payments);
		if (paymentData.payments && paymentData.payments.length === 1) {
			setSelectedMethod(paymentData.payments[0]);
		} else if (!paymentData.payments || paymentData.payments.length === 0) {
			// Fallback for older API or single-method setup
			setSelectedMethod({
				payment_address: paymentData.payment_address!,
				payment_url: paymentData.payment_url!,
				amount: paymentData.amount!,
				currency: paymentData.currency!,
			});
		} else {
			setSelectedMethod(null);
		}
	}

	// Polling for payment status
	useEffect(() => {
		if (isPaid) return;

		const checkStatus = async () => {
			try {
				const response = await apiClient<{ status: string; message: string }>(
					`/payments/check/${paymentData.invoice_id}`,
				);
				if (response.status === "completed") {
					setIsPaid(true);
					onSuccess();
					if (pollingInterval.current) clearInterval(pollingInterval.current);
				}
			} catch (err) {
				console.error("Polling error:", err);
			}
		};

		checkStatus();
		pollingInterval.current = setInterval(checkStatus, 10000);

		return () => {
			if (pollingInterval.current) clearInterval(pollingInterval.current);
		};
	}, [paymentData.invoice_id, isPaid, onSuccess]);

	useEffect(() => {
		if (timeLeft <= 0 || isPaid) return;
		const timer = setInterval(
			() => setTimeLeft((prev) => Math.max(0, prev - 1)),
			1000,
		);
		return () => clearInterval(timer);
	}, [timeLeft, isPaid]);

	const copyToClipboard = useCallback(
		(text: string, type: "address" | "amount") => {
			navigator.clipboard.writeText(text).then(() => {
				setCopied(type);
				toast({ title: t("copied", { defaultValue: "Copied!" }) });
				setTimeout(() => setCopied(null), 2000);
			});
		},
		[toast, t],
	);

	const minutes = Math.floor(timeLeft / 60);
	const seconds = timeLeft % 60;

	if (isPaid) {
		return (
			<div className="py-12 flex flex-col items-center text-center space-y-6">
				<div className="w-20 h-20 bg-green-500/10 rounded-full flex items-center justify-center">
					<PartyPopper className="h-10 w-10 text-green-500" />
				</div>
				<div className="space-y-2">
					<h3 className="text-2xl font-bold text-green-500">
						Payment Successful!
					</h3>
					<p className="text-muted-foreground">
						Your subscription has been activated. Enjoy your new features!
					</p>
				</div>
				<Button onClick={onBack} className="mt-4">
					Go to Account
				</Button>
			</div>
		);
	}

	if (!selectedMethod) {
		return (
			<div className="space-y-6 py-4">
				<div className="flex items-center gap-3">
					<Button
						variant="ghost"
						size="icon"
						onClick={onBack}
						className="shrink-0"
					>
						<ArrowLeft className="h-4 w-4" />
					</Button>
					<h3 className="text-xl font-bold">
						{t("pricingModal.selectCurrency", {
							defaultValue: "Select Payment Method",
						})}
					</h3>
				</div>
				<div className="grid gap-3">
					{paymentData.payments?.map((method) => (
						<Button
							key={`${method.currency}-${method.payment_method}`}
							variant="outline"
							className="h-20 justify-start gap-4 px-6 border-2 hover:border-primary hover:bg-primary/5 transition-all"
							onClick={() => setSelectedMethod(method)}
						>
							<div className="bg-muted p-2 rounded-lg">
								{getCoinIcon(method.currency, method.payment_method)}
							</div>
							<div className="text-left flex-1">
								<div className="font-bold text-lg">
									{getCurrencyDisplay(method.currency, method.payment_method)}
								</div>
								<div className="text-xs text-muted-foreground">
									{getNetworkName(method.currency, method.payment_method)}
								</div>
							</div>
							<div className="text-right font-mono text-sm font-semibold">
								{method.amount}{" "}
								{getCurrencyDisplay(method.currency, method.payment_method)}
							</div>
						</Button>
					))}
				</div>
			</div>
		);
	}

	return (
		<div className="space-y-6 py-4">
			{/* Header */}
			<div className="flex items-center gap-3">
				<Button
					variant="ghost"
					size="icon"
					onClick={() => setSelectedMethod(null)}
					className="shrink-0"
					disabled={paymentData.payments?.length === 1}
				>
					<ArrowLeft className="h-4 w-4" />
				</Button>
				<div>
					<h3 className="text-lg font-semibold flex items-center gap-2">
						{getCoinIcon(
							selectedMethod.currency,
							selectedMethod.payment_method,
						)}
						{getCurrencyDisplay(
							selectedMethod.currency,
							selectedMethod.payment_method,
						)}{" "}
						{t("payment", { defaultValue: "Payment" })}
						<span className="text-xs bg-muted px-2 py-0.5 rounded text-muted-foreground font-normal">
							{getNetworkName(
								selectedMethod.currency,
								selectedMethod.payment_method,
							)}
						</span>
					</h3>
					<p className="text-sm text-muted-foreground">
						{t("pricingModal.sendExactAmount", {
							defaultValue:
								"Send exactly the amount below to complete your payment",
						})}
					</p>
				</div>
			</div>

			{/* Timer & Polling Info */}
			<div className="flex flex-col items-center gap-2">
				<div
					className={cn(
						"inline-flex items-center gap-2 px-4 py-2 rounded-full text-sm font-mono font-medium",
						timeLeft > 300
							? "bg-green-500/10 text-green-500"
							: timeLeft > 60
								? "bg-yellow-500/10 text-yellow-500"
								: "bg-red-500/10 text-red-500 animate-pulse",
					)}
				>
					<Clock className="h-4 w-4" />
					{minutes.toString().padStart(2, "0")}:
					{seconds.toString().padStart(2, "0")}
				</div>
				<div className="flex items-center gap-2 text-xs text-muted-foreground">
					<Loader2 className="h-3 w-3 animate-spin" />
					{t("pricingModal.waitingConfirmation", {
						defaultValue: "Waiting for confirmation...",
					})}
				</div>
			</div>

			{/* Price Summary */}
			<div className="text-center space-y-1">
				<p className="text-sm text-muted-foreground">
					{t("pricingModal.totalLabel", { defaultValue: "Total" })}: $
					{paymentData.price_usd} USD
				</p>
				<p className="text-3xl font-bold font-mono text-primary">
					{selectedMethod.amount}{" "}
					{getCurrencyDisplay(
						selectedMethod.currency,
						selectedMethod.payment_method,
					)}
				</p>
			</div>

			{/* QR Code */}
			{selectedMethod.payment_url && (
				<div className="flex justify-center">
					<div className="bg-white p-4 rounded-xl shadow-sm border">
						<img
							src={`https://api.qrserver.com/v1/create-qr-code/?size=200x200&data=${encodeURIComponent(selectedMethod.payment_url)}`}
							alt="Payment QR Code"
							className="w-48 h-48"
						/>
					</div>
				</div>
			)}

			{/* Payment Details */}
			<div className="space-y-4">
				{selectedMethod.payment_address && (
					<div className="space-y-2">
						<label className="text-xs font-medium text-muted-foreground uppercase tracking-wider">
							{t("pricingModal.paymentAddress", {
								defaultValue: "Payment Address",
							})}
						</label>
						<div className="flex items-center gap-2">
							<code className="flex-1 p-3 bg-muted rounded-lg text-sm font-mono break-all select-all">
								{selectedMethod.payment_address}
							</code>
							<Button
								variant="outline"
								size="icon"
								className="shrink-0"
								onClick={() =>
									copyToClipboard(selectedMethod.payment_address!, "address")
								}
							>
								{copied === "address" ? (
									<Check className="h-4 w-4 text-green-500" />
								) : (
									<Copy className="h-4 w-4" />
								)}
							</Button>
						</div>
					</div>
				)}

				{selectedMethod.amount && (
					<div className="space-y-2">
						<label className="text-xs font-medium text-muted-foreground uppercase tracking-wider">
							{t("pricingModal.amountLabel", { defaultValue: "Amount" })}
						</label>
						<div className="flex items-center gap-2">
							<code className="flex-1 p-3 bg-muted rounded-lg text-sm font-mono">
								{selectedMethod.amount}{" "}
								{getCurrencyDisplay(
									selectedMethod.currency,
									selectedMethod.payment_method,
								)}
							</code>
							<Button
								variant="outline"
								size="icon"
								className="shrink-0"
								onClick={() =>
									copyToClipboard(selectedMethod.amount!, "amount")
								}
							>
								{copied === "amount" ? (
									<Check className="h-4 w-4 text-green-500" />
								) : (
									<Copy className="h-4 w-4" />
								)}
							</Button>
						</div>
					</div>
				)}
			</div>

			{/* Info */}
			<Alert className="bg-muted/50 border-none">
				<Info className="h-4 w-4 text-primary" />
				<AlertDescription className="text-xs">
					{t("pricingModal.automaticActivationNote", {
						defaultValue:
							"Your subscription will be activated automatically. Please do not close this window until the payment is confirmed.",
					})}
				</AlertDescription>
			</Alert>

			{timeLeft === 0 && (
				<Alert variant="destructive">
					<Terminal className="h-4 w-4" />
					<AlertTitle>
						{t("pricingModal.invoiceExpired", {
							defaultValue: "Invoice Expired",
						})}
					</AlertTitle>
					<AlertDescription>
						{t("pricingModal.invoiceExpiredDescription", {
							defaultValue:
								"This invoice has expired. Please go back and create a new payment.",
						})}
					</AlertDescription>
				</Alert>
			)}
		</div>
	);
};

// --- Plan Card (Styled matching AdminPlansPage and NodeLeaderboard) ---
const PlanCard: React.FC<{
	plan: Plan;
	isCurrent: boolean;
	onSelect: (planKey: string) => void;
	isUpgrading: boolean;
	selectedPlan: string | null;
}> = ({ plan, isCurrent, onSelect, isUpgrading, selectedPlan }) => {
	const { t } = useTranslation(["common", "account"]);
	const isActionPending = isUpgrading && selectedPlan === plan.key;
	const isLifetime =
		(plan.billing_mode === "lifetime" && plan.period_label === "lifetime") ||
		Boolean(plan.billing?.lifetime?.enabled);
	const isSoldOut = Boolean(
		isLifetime && plan.slots && plan.slots.available <= 0,
	);
	const priceSuffix =
		isLifetime && plan.period_label === "lifetime"
			? t("pricingModal.lifetimeSuffix", { defaultValue: "lifetime" })
			: "/month";

	const isPro = plan.key === "pro" || plan.key === "ultra" || plan.key === "vip";
	const effectivePrice = plan.price_usd ?? 0;

	return (
		<Card
			className={cn(
				"relative flex flex-col justify-between border-2 transition-all duration-200 overflow-hidden bg-card/60 backdrop-blur-sm rounded-xl",
				isCurrent
					? "border-primary ring-2 ring-primary bg-primary/[0.04] shadow-md"
					: isPro
						? "border-primary/40 hover:border-primary/80 shadow-sm bg-primary/[0.02]"
						: "border-border/60 hover:border-border shadow-sm",
				!plan.active && "opacity-60",
			)}
		>
			{/* Top Badges (Current Plan or Popular) */}
			{isCurrent ? (
				<div className="absolute top-0 right-0">
					<div className="bg-primary text-primary-foreground text-[10px] font-bold uppercase tracking-wider px-3 py-0.5 rounded-bl-md shadow-sm">
						{t("pricingModal.currentPlan", { defaultValue: "Current Plan" })}
					</div>
				</div>
			) : isPro ? (
				<div className="absolute top-0 right-0 bg-primary/90 text-primary-foreground text-[9px] font-bold uppercase tracking-wider px-2.5 py-0.5 rounded-bl-md flex items-center gap-1">
					<Sparkles className="w-2.5 h-2.5" />
					{t("pricingModal.popular", { defaultValue: "Popular" })}
				</div>
			) : null}

			<CardHeader className="pb-3 pt-4">
				<div className="flex justify-between items-start pr-12">
					<div>
						<Badge
							variant={isPro || isCurrent ? "default" : "secondary"}
							className="text-[10px] font-mono font-bold tracking-wider uppercase mb-1.5"
						>
							{plan.key.toUpperCase()}
						</Badge>
						<CardTitle className="text-xl font-bold">{plan.name}</CardTitle>
					</div>
				</div>
				<div className="mt-1 flex items-baseline justify-between">
					<div className="text-left">
						<span className="text-3xl font-black text-primary">${effectivePrice}</span>
						<span className="text-xs text-muted-foreground ml-1 font-mono">{priceSuffix}</span>
					</div>
				</div>
				<CardDescription className="text-xs text-muted-foreground line-clamp-2 mt-1 min-h-[2.25rem]">
					{plan.description || "Subscription tier"}
				</CardDescription>
			</CardHeader>

			<CardContent className="space-y-3.5 flex-1 pb-4">
				{/* Badges / Highlights */}
				<div className="flex flex-wrap gap-1.5">
					{isLifetime && (plan.billing?.lifetime?.enabled || plan.slots) && (
						<Badge
							variant="outline"
							className="bg-amber-500/10 text-amber-500 border-amber-500/30 text-[10px] font-mono flex items-center gap-1"
						>
							<Zap className="w-3 h-3 text-amber-400" />
							Lifetime: ${plan.billing?.lifetime?.price_usd ?? plan.price_usd}
							{plan.slots?.limit ? ` (${plan.slots.available} / ${plan.slots.limit} slots)` : plan.billing?.lifetime?.slot_limit ? ` (${plan.billing.lifetime.slot_limit} slots)` : ""}
						</Badge>
					)}
					{plan.limits?.allow_real_trading ? (
						<Badge
							variant="outline"
							className="bg-emerald-500/10 text-emerald-500 border-emerald-500/30 text-[10px] font-mono flex items-center gap-1"
						>
							<Check className="w-3 h-3" />
							Live Bots: {plan.limits?.max_live_strategies ?? 1}
						</Badge>
					) : (
						<Badge
							variant="outline"
							className="bg-zinc-500/10 text-zinc-400 border-zinc-500/20 text-[10px] font-mono"
						>
							Simulation Only
						</Badge>
					)}
					{plan.limits?.allow_intracandle_triggers && (
						<Badge
							variant="outline"
							className="bg-purple-500/10 text-purple-400 border-purple-500/30 text-[10px] font-mono"
						>
							Intracandle
						</Badge>
					)}
				</div>

				{/* Quotas & Operational Limits Box (styled identically to Admin & Hub) */}
				<div className="text-xs bg-muted/40 border border-border/30 p-2.5 rounded-md space-y-1.5 font-mono">
					<div className="flex justify-between">
						<span className="text-muted-foreground">Backtests / day:</span>
						<span className="font-semibold text-foreground">
							{plan.quotas?.run_vector_backtest_per_day === -1
								? "Unlimited"
								: plan.quotas?.run_vector_backtest_per_day ?? (plan.key === "free" ? 20 : plan.key === "standard" ? 50 : "Unlimited")}
						</span>
					</div>
					<div className="flex justify-between">
						<span className="text-muted-foreground">AI queries / day:</span>
						<span className="font-semibold text-foreground">
							{plan.quotas?.use_ai_assistant_per_day === -1
								? "Unlimited"
								: plan.quotas?.use_ai_assistant_per_day ?? (plan.key === "free" ? 10 : plan.key === "standard" ? 35 : "Unlimited")}
						</span>
					</div>
					<div className="flex justify-between">
						<span className="text-muted-foreground">Live strategies:</span>
						<span className="font-semibold text-foreground">
							{plan.limits?.allow_real_trading
								? `${plan.limits?.max_live_strategies ?? (plan.key === "standard" ? 10 : 30)} active bots`
								: "Sim only"}
						</span>
					</div>
					<div className="flex justify-between">
						<span className="text-muted-foreground">History depth:</span>
						<span className="font-semibold text-foreground">
							{plan.limits?.max_backtest_duration_days === -1
								? "Full history"
								: `${plan.limits?.max_backtest_duration_days ?? (plan.key === "free" ? 90 : 365)} days`}
						</span>
					</div>
				</div>

				{/* Features Checklist */}
				{(plan.features || []).length > 0 && (
					<div className="space-y-1.5">
						<span className="text-[10px] font-bold text-muted-foreground uppercase tracking-wider block">
							Plan Features ({plan.features.length}):
						</span>
						<ul className="text-xs space-y-1.5">
							{plan.features.map((feature, index) => {
								const lower = feature.toLowerCase();
								const isUnlimited = lower.includes("unlimited");
								const isLimitation =
									!isUnlimited &&
									(lower.includes("limited") ||
										lower.includes("limit") ||
										lower.includes("days") ||
										lower.includes("restricted"));
								const Icon = isLimitation ? Clock : Check;
								const iconColor = isUnlimited
									? "text-purple-400"
									: isLimitation
										? "text-amber-400"
										: "text-emerald-500";

								return (
									<li key={index} className="flex items-start gap-1.5 text-muted-foreground">
										<Icon className={cn("h-3.5 w-3.5 mt-0.5 flex-shrink-0", iconColor)} />
										<span className="text-foreground/90">{feature}</span>
									</li>
								);
							})}
						</ul>
					</div>
				)}
			</CardContent>

			<CardFooter className="pt-2 pb-4">
				<Button
					className="w-full font-bold shadow-sm"
					variant={isCurrent ? "outline" : "default"}
					onClick={() => onSelect(plan.key)}
					disabled={
						isCurrent || isUpgrading || plan.key === "free" || isSoldOut
					}
				>
					{isActionPending && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
					{isCurrent
						? t("pricingModal.currentPlan", { defaultValue: "Current Plan" })
						: plan.key === "free"
							? t("pricingModal.downgradeNotAvailable", { defaultValue: "Free Plan" })
							: isSoldOut
								? t("pricingModal.soldOut", { defaultValue: "Sold out" })
								: isActionPending
									? t("pricingModal.upgrading", { defaultValue: "Processing..." })
									: t("pricingModal.selectPlan", { defaultValue: "Select Plan" })}
				</Button>
			</CardFooter>
		</Card>
	);
};


export const PricingModal: React.FC<PricingModalProps> = ({
	isOpen,
	onClose,
	currentPlan,
}) => {
	const { t } = useTranslation("common");
	const queryClient = useQueryClient();
	const {
		data: plansData,
		isLoading,
		isError,
		error,
	} = usePlans({ refetchInterval: isOpen ? 10000 : false });
	const {
		mutate: createPayment,
		isPending: isCreatingPayment,
		data: paymentData,
		reset: resetPayment,
	} = useCreatePayment();

	const [selectedPlan, setSelectedPlan] = useState<string | null>(null);
	const [prevIsOpen, setPrevIsOpen] = useState(isOpen);

	if (isOpen !== prevIsOpen) {
		setPrevIsOpen(isOpen);
		if (!isOpen) {
			setSelectedPlan(null);
		}
	}

	// Always refresh plans from server when modal is opened
	useEffect(() => {
		if (isOpen) {
			queryClient.invalidateQueries({ queryKey: ["plans"] });
		}
	}, [isOpen, queryClient]);

	// Reset payment data when modal closes
	useEffect(() => {
		if (!isOpen) {
			resetPayment();
		}
	}, [isOpen, resetPayment]);

	const handleSelectPlan = (planKey: string) => {
		setSelectedPlan(planKey);
		createPayment({ plan_name: planKey });
	};

	const handleBackToPlans = () => {
		resetPayment();
		setSelectedPlan(null);
		queryClient.invalidateQueries({ queryKey: ["accountStatus"] });
	};

	const handlePaymentSuccess = () => {
		queryClient.invalidateQueries({ queryKey: ["accountStatus"] });
	};

	// Show checkout if payment was created successfully
	const checkoutData =
		paymentData && (paymentData.payment_address || paymentData.payments?.length)
			? paymentData
			: null;
	const showCheckout = Boolean(checkoutData);
	const activePlans = plansData?.filter((plan) => plan.active) ?? [];
	const lifetimePlans =
		activePlans.filter(
			(plan) =>
				plan.billing_mode === "lifetime" &&
				plan.period_label === "lifetime",
		);
	const isLifetimeMode = lifetimePlans.length > 0;
	const totalLifetimeSeats = lifetimePlans.reduce(
		(sum, plan) => sum + (plan.slots?.limit ?? 0),
		0,
	);

	const dialogMaxWidthClass = showCheckout
		? "max-w-lg"
		: activePlans.length > 3
			? "max-w-5xl"
			: "max-w-4xl";

	return (
		<Dialog open={isOpen} onOpenChange={onClose}>
			<DialogContent className={cn(dialogMaxWidthClass, "transition-all")}>
				<DialogHeader>
					<DialogTitle className="text-3xl font-bold">
						{showCheckout ? "" : t("pricingModal.title")}
					</DialogTitle>
					{!showCheckout && (
						<DialogDescription>
							{t("pricingModal.description")}
						</DialogDescription>
					)}
				</DialogHeader>

				{checkoutData ? (
					<PaymentCheckout
						paymentData={checkoutData}
						onBack={handleBackToPlans}
						onSuccess={handlePaymentSuccess}
					/>
				) : (
					<div className="py-6">
						<Alert className="mb-6 bg-muted/50 border-none">
							<Info className="h-4 w-4 text-primary" />
							<AlertDescription className="text-sm font-medium">
								{t("pricingModal.agreementNotice.blocksNote")}
							</AlertDescription>
						</Alert>

						{isLoading && (
							<div className="grid grid-cols-1 md:grid-cols-3 gap-6">
								{[...Array(3)].map((_, i) => (
									<Card key={i}>
										<CardHeader>
											<Skeleton className="h-6 w-1/2" />
										</CardHeader>
										<CardContent className="space-y-3">
											<Skeleton className="h-5 w-3/4" />
											<Skeleton className="h-16 w-full" />
											<Skeleton className="h-10 w-full" />
										</CardContent>
									</Card>
								))}
							</div>
						)}
						{isError && (
							<Alert variant="destructive">
								<Terminal className="h-4 w-4" />
								<AlertTitle>{t("errorTitle")}</AlertTitle>
								<AlertDescription>{error.message}</AlertDescription>
							</Alert>
						)}
						{plansData && (
							<div className="space-y-5">
								{isLifetimeMode && (
									<div className="flex flex-wrap items-center justify-center gap-2">
										<span className="rounded-full border border-green-500/30 bg-green-500/10 px-3 py-1 text-xs font-bold uppercase tracking-wide text-green-600">
											{t("pricingModal.lifetimeAccessBadge", {
												defaultValue: "Lifetime access",
											})}
										</span>
										{totalLifetimeSeats > 0 && (
											<span className="rounded-full border border-primary/30 bg-primary/10 px-3 py-1 text-xs font-bold uppercase tracking-wide text-primary">
												{t("pricingModal.lifetimeSeatsBadge", {
													defaultValue: "{{count}} seats total",
													count: totalLifetimeSeats,
												})}
											</span>
										)}
										<span className="rounded-full border border-amber-500/30 bg-amber-500/10 px-3 py-1 text-xs font-bold uppercase tracking-wide text-amber-600">
											{t("pricingModal.oneTimePaymentBadge", {
												defaultValue: "One-time payment",
											})}
										</span>
									</div>
								)}

								<div
									className={cn(
										"grid gap-6",
										activePlans.length === 1 && "grid-cols-1 max-w-sm mx-auto",
										activePlans.length === 2 && "grid-cols-1 md:grid-cols-2 max-w-2xl mx-auto",
										activePlans.length === 3 && "grid-cols-1 md:grid-cols-3",
										activePlans.length >= 4 && "grid-cols-1 sm:grid-cols-2 lg:grid-cols-4",
									)}
								>
									{activePlans.map((plan) => (
										<PlanCard
											key={plan.key}
											plan={plan}
											isCurrent={currentPlan === plan.key}
											onSelect={handleSelectPlan}
											isUpgrading={isCreatingPayment}
											selectedPlan={selectedPlan}
										/>
									))}
								</div>
							</div>
						)}
					</div>
				)}


				{!showCheckout && (
					<div className="text-center text-xs text-muted-foreground mt-4">
						{t("pricingModal.agreementNotice.part1")}{" "}
						<a
							href={`${import.meta.env.VITE_APP_URL || "https://depthsight.pro"}/terms-of-service`}
							target="_blank"
							rel="noopener noreferrer"
							className="underline hover:text-primary"
						>
							{t("common:termsOfService")}
						</a>{" "}
						{t("pricingModal.agreementNotice.part2")}{" "}
						<a
							href={`${import.meta.env.VITE_APP_URL || "https://depthsight.pro"}/privacy-policy`}
							target="_blank"
							rel="noopener noreferrer"
							className="underline hover:text-primary"
						>
							{t("common:privacyPolicy")}
						</a>
						.
					</div>
				)}
			</DialogContent>
		</Dialog>
	);
};
