// src/pages/Account.tsx

import { useQueryClient } from "@tanstack/react-query";
import {
	AlertTriangle,
	Award,
	Check,
	Copy,
	Dna,
	ExternalLink,
	Gauge,
	Gift,
	RefreshCw,
	Shield,
	ShieldAlert,
	ShieldCheck,
	Sparkles,
	Terminal,
	User,
	Wallet,
	Zap,
} from "lucide-react";
import type React from "react";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate, useSearchParams } from "react-router-dom";
import { SecuritySettings } from "@/components/account/SecuritySettings";
import { PageLayout } from "@/components/layout/PageLayout";
import Achievements from "@/components/research/Achievements";
import { ConfirmationModal } from "@/components/shared/ConfirmationModal";
import { PricingModal } from "@/components/shared/PricingModal";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Input } from "@/components/ui/input";
import {
	Badge,
	Bar,
	Btn,
	Panel,
	Segmented,
} from "@/components/ui/quant-ui";
import { useToast } from "@/components/ui/use-toast";
import { useAuth } from "@/context/AuthContext";
import {
	useAccountStatus,
	useDeleteAccount,
	useGeneStats,
	useMyGenes,
	usePaperWallet,
	useResetPaperAccount,
} from "@/lib/api";
import { cn } from "@/lib/utils";

type AccountTab = "account" | "security" | "achievements";

const AccountPage: React.FC = () => {
	const { t } = useTranslation(["account", "common"]);
	const { data: accountStatus, isLoading, isError, error } = useAccountStatus();
	const { data: paperWalletAssets, isLoading: isLoadingPaperWallet } =
		usePaperWallet();
	const { data: genesData } = useMyGenes();
	const { data: geneStats } = useGeneStats();

	// Extract USDT balance from the assets array
	const usdtBalance =
		paperWalletAssets?.find((a) => a.asset === "USDT")?.balance ?? 0;

	const { mutate: resetPaperAccount, isPending: isReseting } =
		useResetPaperAccount();
	const { user, logout } = useAuth();
	const { toast } = useToast();
	const { mutate: deleteAccount, isPending: isDeleting } = useDeleteAccount();

	const [showResetConfirm, setShowResetConfirm] = useState(false);
	const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);
	const [isPricingModalOpen, setIsPricingModalOpen] = useState(false);
	const [copiedField, setCopiedField] = useState<string | null>(null);

	const [searchParams] = useSearchParams();
	const tabParam = searchParams.get("tab");
	const [activeTab, setActiveTab] = useState<AccountTab>(
		tabParam === "security" || tabParam === "achievements" ? tabParam : "account",
	);

	const navigate = useNavigate();
	const queryClient = useQueryClient();

	useEffect(() => {
		const paymentStatus = searchParams.get("payment");

		if (paymentStatus) {
			switch (paymentStatus) {
				case "success":
					toast({
						title: t("paymentStatus.success.title"),
						description: t("paymentStatus.success.description"),
					});
					queryClient.invalidateQueries({ queryKey: ["accountStatus"] });
					break;
				case "failed":
					toast({
						variant: "destructive",
						title: t("paymentStatus.failed.title"),
						description: t("paymentStatus.failed.description"),
					});
					break;
				case "cancelled":
					toast({
						title: t("paymentStatus.cancelled.title"),
						description: t("paymentStatus.cancelled.description"),
					});
					break;
			}
			navigate("/account", { replace: true });
		}
	}, [navigate, queryClient, searchParams, t, toast]);

	const copyToClipboard = (text: string, fieldName: string) => {
		navigator.clipboard.writeText(text).then(() => {
			setCopiedField(fieldName);
			toast({
				title: t("common:copied", "Copied"),
				description: `${fieldName} ${t("common:copiedToClipboard", "copied to clipboard")}`,
			});
			setTimeout(() => setCopiedField(null), 2500);
		});
	};

	const referralLink = user?.referralCode
		? `${window.location.protocol}//${window.location.host}/r/${user.referralCode}`
		: "";

	const handleResetConfirm = () => {
		resetPaperAccount(undefined, {
			onSuccess: () => setShowResetConfirm(false),
		});
	};

	const handleDeleteConfirm = () => {
		deleteAccount(undefined, {
			onSuccess: () => {
				logout();
			},
		});
	};

	const activeBonuses = accountStatus?.bonuses?.filter(
		(b) => b.status === "active" && b.quantity > 0,
	);
	const pendingBonuses = accountStatus?.bonuses?.filter(
		(b) => b.status === "pending" && b.quantity > 0,
	);

	if (isLoading) {
		return (
			<PageLayout title={t("pageTitle", "Account")} hideHeader>
				<div className="space-y-6">
					<div className="h-28 rounded-2xl bg-white/[0.03] animate-pulse border border-white/5" />
					<div className="grid grid-cols-1 md:grid-cols-2 gap-5">
						{[...Array(4)].map((_, i) => (
							<div
								key={i}
								className="h-56 rounded-2xl bg-white/[0.03] animate-pulse border border-white/5"
							/>
						))}
					</div>
				</div>
			</PageLayout>
		);
	}

	if (isError) {
		return (
			<PageLayout title={t("pageTitle", "Account")} hideHeader>
				<Alert variant="destructive" className="glass border-rose-500/30">
					<Terminal className="h-4 w-4" />
					<AlertTitle>{t("common:errorTitle", "Error")}</AlertTitle>
					<AlertDescription>{error?.message}</AlertDescription>
				</Alert>
			</PageLayout>
		);
	}

	const planTone =
		accountStatus?.planName === "pro"
			? "cyan"
			: accountStatus?.planName === "standard"
				? "azure"
				: "neutral";

	return (
		<PageLayout title={t("pageTitle", "Account")} hideHeader>
			<div className="space-y-6">
				{/* Top Hero Profile Card */}
				<div className="glass relative overflow-hidden rounded-2xl border border-white/10 p-5 md:p-6 shadow-2xl backdrop-blur-xl animate-fade-up">
					{/* Ambient background glow */}
					<div className="pointer-events-none absolute -right-20 -top-20 h-64 w-64 rounded-full bg-cyan/15 blur-3xl" />
					<div className="pointer-events-none absolute -left-20 -bottom-20 h-64 w-64 rounded-full bg-azure/10 blur-3xl" />

					<div className="relative flex flex-col md:flex-row md:items-center justify-between gap-5">
						{/* User identity info */}
						<div className="flex items-center gap-4">
							<div className="relative flex h-14 w-14 shrink-0 items-center justify-center rounded-2xl bg-gradient-to-br from-cyan/20 to-azure/20 border border-cyan/40 shadow-[0_0_24px_-6px_rgba(0,212,255,0.5)]">
								<span className="font-mono text-xl font-bold text-cyan">
									{user?.username ? user.username.charAt(0).toUpperCase() : "U"}
								</span>
								<div className="absolute -bottom-1 -right-1 h-3.5 w-3.5 rounded-full border-2 border-[#07080b] bg-emerald-400 shadow-[0_0_8px_#10e0a0]" />
							</div>

							<div className="min-w-0 space-y-1">
								<div className="flex items-center gap-2.5 flex-wrap">
									<h2 className="text-lg md:text-xl font-bold tracking-tight text-white truncate">
										{user?.username || "Quant Trader"}
									</h2>
									<Badge
										tone={planTone}
										dot
										pulse={accountStatus?.planName === "pro"}
									>
										{t(`plans.${accountStatus?.planName || "free"}`, {
											defaultValue: (accountStatus?.planName || "free").toUpperCase(),
										})}
									</Badge>
									{user?.role === "admin" && (
										<Badge tone="amber">ADMIN</Badge>
									)}
								</div>
								<div className="flex items-center gap-3 text-xs text-white/50 flex-wrap">
									<span className="truncate">{user?.email}</span>
									<span className="text-white/20">•</span>
									<span className="font-mono text-white/70 flex items-center gap-1.5">
										{user?.isTotpEnabled ? (
											<>
												<ShieldCheck className="w-3.5 h-3.5 text-emerald-400" />
												<span className="text-emerald-400">
													{t("twoFactor.badgeEnabled", "2FA Active")}
												</span>
											</>
										) : (
											<>
												<ShieldAlert className="w-3.5 h-3.5 text-amber-400" />
												<span className="text-amber-400/80">
													{t("twoFactor.badgeDisabled", "2FA Off")}
												</span>
											</>
										)}
									</span>
								</div>
							</div>
						</div>

						{/* Quick stats & upgrade action */}
						<div className="flex items-center gap-3 flex-wrap md:justify-end">
							<div className="flex items-center gap-2.5">
								<div className="rounded-xl border border-white/5 bg-white/[0.02] px-3.5 py-2">
									<div className="text-[10px] uppercase tracking-wider text-white/40 font-mono">
										{t("paperAccountCard.title", "Demo Balance")}
									</div>
									<div className="font-mono text-base font-bold text-emerald-400">
										{isLoadingPaperWallet
											? "..."
											: `$${usdtBalance.toLocaleString("en-US", {
													minimumFractionDigits: 2,
													maximumFractionDigits: 2,
												})}`}
									</div>
								</div>

								<div className="rounded-xl border border-white/5 bg-white/[0.02] px-3.5 py-2">
									<div className="text-[10px] uppercase tracking-wider text-white/40 font-mono">
										{t("geneticsLabCard.title", "Genes")}
									</div>
									<div className="font-mono text-base font-bold text-cyan">
										{genesData?.total || 0}
									</div>
								</div>
							</div>

							<Btn
								variant="primary"
								size="md"
								icon={<Zap className="w-4 h-4" />}
								onClick={() => setIsPricingModalOpen(true)}
							>
								{t("myPlanCard.changePlanButton", "Upgrade Plan")}
							</Btn>
						</div>
					</div>
				</div>

				{/* Tab Navigation */}
				<div className="flex items-center justify-between gap-4 flex-wrap pb-1">
					<Segmented<AccountTab>
						size="md"
						value={activeTab}
						onChange={setActiveTab}
						options={[
							{
								value: "account",
								label: t("accountTab", "Account"),
								icon: <User className="h-4 w-4" />,
							},
							{
								value: "security",
								label: t("securityTab", "Security (2FA)"),
								icon: <Shield className="h-4 w-4" />,
							},
							{
								value: "achievements",
								label: t("achievementsTab", "Achievements"),
								icon: <Award className="h-4 w-4" />,
							},
						]}
					/>
				</div>

				{/* TAB 1: Account overview */}
				{activeTab === "account" && (
					<div className="grid grid-cols-1 md:grid-cols-2 gap-5 animate-fade-up">
						{/* Card 1: My Plan */}
						<Panel
							title={
								<span className="flex items-center gap-2">
									<Sparkles className="w-4 h-4 text-cyan" />
									{t("myPlanCard.title", "My Plan")}
								</span>
							}
							subtitle={
								accountStatus?.planExpiresAt
									? `${t("myPlanCard.planActiveUntil", "Active until")} ${new Date(
											accountStatus.planExpiresAt,
										).toLocaleDateString()}`
									: t("myPlanCard.description", "Current subscription tier")
							}
							actions={
								<Btn
									variant="subtle"
									size="sm"
									icon={<Zap className="w-3.5 h-3.5" />}
									onClick={() => setIsPricingModalOpen(true)}
								>
									{t("myPlanCard.changePlanButton", "Change Plan")}
								</Btn>
							}
						>
							<div className="space-y-4 pt-1">
								<div className="flex items-center justify-between p-4 rounded-xl bg-white/[0.02] border border-white/5">
									<div>
										<div className="text-[11px] uppercase tracking-wider text-white/40 font-mono">
											{t("myPlanCard.title", "Current Tier")}
										</div>
										<div className="text-2xl font-bold font-mono tracking-tight text-white capitalize mt-0.5">
											{t(`plans.${accountStatus?.planName}`, {
												defaultValue: accountStatus?.planName || "Free",
											})}
										</div>
									</div>
									<Badge tone={planTone} dot className="text-xs px-2.5 py-1">
										{accountStatus?.planName === "pro"
											? "ULTRA QUANT"
											: accountStatus?.planName === "standard"
												? "TRADER"
												: "BASIC"}
									</Badge>
								</div>

								<div className="text-xs text-white/50 leading-relaxed">
									{accountStatus?.planExpiresAt ? (
										<div className="flex items-center gap-2 text-white/70">
											<div className="h-2 w-2 rounded-full bg-emerald-400" />
											<span>
												{t("myPlanCard.planActiveUntil", "Plan active until")}:{" "}
												<span className="font-mono font-medium text-white">
													{new Date(accountStatus.planExpiresAt).toLocaleDateString()}
												</span>
											</span>
										</div>
									) : (
										<span>{t("myPlanCard.description", "Full algorithmic trading suite access.")}</span>
									)}
								</div>
							</div>
						</Panel>

						{/* Card 2: Paper Account */}
						<Panel
							title={
								<span className="flex items-center gap-2">
									<Wallet className="w-4 h-4 text-emerald-400" />
									{t("paperAccountCard.title", "Paper Account")}
								</span>
							}
							subtitle={t(
								"paperAccountCard.description",
								"Practice risk-free trading with a simulated balance.",
							)}
							actions={
								<Btn
									variant="outline"
									size="sm"
									icon={<RefreshCw className="w-3.5 h-3.5" />}
									onClick={() => setShowResetConfirm(true)}
									disabled={isReseting}
								>
									{t("paperAccountCard.resetButton", "Reset")}
								</Btn>
							}
						>
							<div className="space-y-4 pt-1">
								<div className="flex items-center justify-between p-4 rounded-xl bg-white/[0.02] border border-white/5">
									<div>
										<div className="text-[11px] uppercase tracking-wider text-white/40 font-mono">
											USDT Paper Balance
										</div>
										{isLoadingPaperWallet ? (
											<div className="h-8 w-36 rounded bg-white/10 animate-pulse mt-1" />
										) : (
											<div className="text-2xl sm:text-3xl font-bold font-mono tracking-tight text-emerald-400 mt-0.5">
												$
												{usdtBalance.toLocaleString("en-US", {
													minimumFractionDigits: 2,
													maximumFractionDigits: 2,
												})}
											</div>
										)}
									</div>
									<Badge tone="profit" dot>
										SIMULATED
									</Badge>
								</div>

								<div className="flex items-center justify-between text-xs text-white/40">
									<span>Simulated exchange environment</span>
									<span className="font-mono text-white/60">Risk: 0.00%</span>
								</div>
							</div>
						</Panel>

						{/* Card 3: Quotas & Limits */}
						<Panel
							title={
								<span className="flex items-center gap-2">
									<Gauge className="w-4 h-4 text-cyan" />
									{t("quotaUsageCard.title", "Quota Usage")}
								</span>
							}
							subtitle={t("quotaUsageCard.description", "Your limits reset periodically.")}
						>
							<div className="space-y-4 pt-1">
								{accountStatus?.quotas && accountStatus.quotas.length > 0 ? (
									accountStatus.quotas.map((quota) => {
										const isUnlimited = quota.limit === -1;
										const ratio = isUnlimited ? 0 : quota.used / quota.limit;
										const isNearLimit = !isUnlimited && ratio >= 0.8;

										return (
											<div key={quota.name} className="space-y-1.5">
												<div className="flex justify-between items-center text-xs">
													<span className="font-medium text-white/80">
														{t(`quotas.${quota.name}`, {
															defaultValue: quota.name,
														})}
													</span>
													<span className="font-mono text-white/60 text-[11px]">
														{isUnlimited ? (
															<span className="text-cyan">
																{quota.used} / {t("quotaUsageCard.unlimited", "Unlimited")}
															</span>
														) : (
															<span className={cn(isNearLimit && "text-amber-400 font-semibold")}>
																{quota.used} / {quota.limit}
															</span>
														)}
													</span>
												</div>
												{!isUnlimited && (
													<Bar
														value={ratio}
														color={
															isNearLimit
																? "linear-gradient(90deg, #f59e0b, #ef4444)"
																: "linear-gradient(90deg, #0066ff, #00d4ff)"
														}
														height={5}
													/>
												)}
											</div>
										);
									})
								) : (
									<div className="text-xs text-white/40 italic py-2">
										No quota restrictions found for this plan.
									</div>
								)}

								{/* Bonuses section if any exist */}
								{(activeBonuses && activeBonuses.length > 0) ||
								(pendingBonuses && pendingBonuses.length > 0) ? (
									<div className="pt-3 border-t border-white/5 space-y-2">
										<div className="text-[11px] font-semibold text-white/60 uppercase tracking-wider font-mono">
											{t("bonusesCard.title", "Bonus Quotas")}
										</div>
									{activeBonuses?.map((b, idx) => {
										const featureKey =
											(b as unknown as Record<string, unknown>)
												.featureName ??
											(b as unknown as Record<string, unknown>)
												.feature_name ??
											(b as unknown as Record<string, unknown>).feature ??
											"unknown";
										const feature = String(featureKey);
										return (
											<div key={idx} className="flex justify-between items-center text-xs">
												<span className="text-white/70">
													{t(`bonusesCard.features.${feature}`, {
														defaultValue: feature,
													})}
												</span>
												<Badge tone="profit">+{b.quantity}</Badge>
											</div>
										);
									})}
									{pendingBonuses?.map((b, idx) => {
										const featureKey =
											(b as unknown as Record<string, unknown>)
												.featureName ??
											(b as unknown as Record<string, unknown>)
												.feature_name ??
											(b as unknown as Record<string, unknown>).feature ??
											"unknown";
										const feature = String(featureKey);
										return (
											<div key={idx} className="flex justify-between items-center text-xs">
												<span className="text-white/40">
													{t(`bonusesCard.features.${feature}`, {
														defaultValue: feature,
													})}{" "}
													({t("bonusesCard.pending", "pending")})
												</span>
												<Badge tone="amber">+{b.quantity}</Badge>
											</div>
										);
									})}
									</div>
								) : null}
							</div>
						</Panel>

						{/* Card 4: Referrals */}
						<Panel
							title={
								<span className="flex items-center gap-2">
									<Gift className="w-4 h-4 text-violet-400" />
									{t("referralCard.title", "Affiliate Program")}
								</span>
							}
							subtitle={t(
								"referralCard.description",
								"Invite traders and earn commissions on subscription payments.",
							)}
							actions={
								<Btn
									variant="outline"
									size="sm"
									icon={<ExternalLink className="w-3.5 h-3.5" />}
									onClick={() => navigate("/affiliate-dashboard")}
								>
									{t("referralCard.dashboardButton", "Affiliate Panel")}
								</Btn>
							}
						>
							<div className="space-y-4 pt-1">
								<div>
									<label className="text-xs font-mono text-white/60 uppercase tracking-wider">
										{t("referralCard.codeLabel", "Your Referral Code")}
									</label>
									<div className="flex items-center gap-2 mt-1.5">
										<div className="relative flex-1">
											<Input
												readOnly
												value={user?.referralCode || "..."}
												className="font-mono text-cyan bg-white/[0.03] border-white/10 text-xs h-9 tracking-wider"
											/>
										</div>
										<Btn
											variant="outline"
											size="sm"
											className="h-9 px-3 shrink-0"
											icon={
												copiedField === "code" ? (
													<Check className="h-3.5 w-3.5 text-emerald-400" />
												) : (
													<Copy className="h-3.5 w-3.5" />
												)
											}
											onClick={() =>
												copyToClipboard(
													user?.referralCode || "",
													"code",
												)
											}
										>
											{copiedField === "code" ? "OK" : "Copy"}
										</Btn>
									</div>
								</div>

								<div>
									<label className="text-xs font-mono text-white/60 uppercase tracking-wider">
										{t("referralCard.linkLabel", "Your Referral Link")}
									</label>
									<div className="flex items-center gap-2 mt-1.5">
										<div className="relative flex-1">
											<Input
												readOnly
												value={referralLink}
												className="font-mono text-white/80 bg-white/[0.03] border-white/10 text-xs h-9"
											/>
										</div>
										<Btn
											variant="outline"
											size="sm"
											className="h-9 px-3 shrink-0"
											icon={
												copiedField === "link" ? (
													<Check className="h-3.5 w-3.5 text-emerald-400" />
												) : (
													<Copy className="h-3.5 w-3.5" />
												)
											}
											onClick={() => copyToClipboard(referralLink, "link")}
										>
											{copiedField === "link" ? "OK" : "Copy"}
										</Btn>
									</div>
								</div>

								<div className="pt-1">
									<Btn
										variant="subtle"
										size="md"
										className="w-full"
										icon={<Gift className="w-4 h-4" />}
										onClick={() => navigate("/affiliate-dashboard")}
									>
										{t("referralCard.dashboardButton", "Open Affiliate Dashboard")}
									</Btn>
								</div>
							</div>
						</Panel>

						{/* Card 5: Genetics Lab */}
						<Panel
							title={
								<span className="flex items-center gap-2">
									<Dna className="w-4 h-4 text-emerald-400" />
									{t("geneticsLabCard.title", "Genetics Laboratory")}
								</span>
							}
							subtitle={t("geneticsLabCard.description", "Discovered strategy genes and DNA collection.")}
							actions={
								<Btn
									variant="outline"
									size="sm"
									icon={<ExternalLink className="w-3.5 h-3.5" />}
									onClick={() => navigate("/lab")}
								>
									{t("geneticsLabCard.viewCollectionButton", "View Lab")}
								</Btn>
							}
						>
							<div className="space-y-4 pt-1">
								<div className="flex items-center justify-between p-4 rounded-xl bg-white/[0.02] border border-white/5">
									<div>
										<div className="text-[11px] uppercase tracking-wider text-white/40 font-mono">
											{t("geneticsLabCard.genesDiscovered", "Total Discovered")}
										</div>
										<div className="text-3xl font-bold font-mono tracking-tight text-emerald-400 mt-0.5">
											{genesData?.total || 0}
										</div>
									</div>
									<Badge tone="profit" dot>
										LAB ACTIVE
									</Badge>
								</div>

								<div className="grid grid-cols-4 gap-2 pt-1">
									<div className="rounded-xl border border-amber-500/20 bg-amber-500/[0.04] p-2.5 text-center">
										<div className="font-mono text-lg font-bold text-amber-400">
											{geneStats?.rarityBreakdown?.LEGENDARY || 0}
										</div>
										<div className="text-[10px] uppercase font-mono tracking-wider text-amber-400/70 mt-0.5">
											{t("geneticsLabCard.legend", "Legendary")}
										</div>
									</div>
									<div className="rounded-xl border border-violet-500/20 bg-violet-500/[0.04] p-2.5 text-center">
										<div className="font-mono text-lg font-bold text-violet-400">
											{geneStats?.rarityBreakdown?.EPIC || 0}
										</div>
										<div className="text-[10px] uppercase font-mono tracking-wider text-violet-400/70 mt-0.5">
											{t("geneticsLabCard.epic", "Epic")}
										</div>
									</div>
									<div className="rounded-xl border border-cyan/20 bg-cyan/[0.04] p-2.5 text-center">
										<div className="font-mono text-lg font-bold text-cyan">
											{geneStats?.rarityBreakdown?.RARE || 0}
										</div>
										<div className="text-[10px] uppercase font-mono tracking-wider text-cyan/70 mt-0.5">
											{t("geneticsLabCard.rare", "Rare")}
										</div>
									</div>
									<div className="rounded-xl border border-white/10 bg-white/[0.02] p-2.5 text-center">
										<div className="font-mono text-lg font-bold text-white/70">
											{geneStats?.rarityBreakdown?.COMMON || 0}
										</div>
										<div className="text-[10px] uppercase font-mono tracking-wider text-white/40 mt-0.5">
											{t("geneticsLabCard.common", "Common")}
										</div>
									</div>
								</div>

								<div className="pt-1">
									<Btn
										variant="outline"
										size="md"
										className="w-full"
										icon={<Dna className="w-4 h-4 text-emerald-400" />}
										onClick={() => navigate("/lab")}
									>
										{t("geneticsLabCard.viewCollectionButton", "Explore Strategy DNA")}
									</Btn>
								</div>
							</div>
						</Panel>

						{/* Card 6: Danger Zone */}
						<Panel
							className="border-rose-500/25 bg-rose-500/[0.02] hover:border-rose-500/40"
							title={
								<span className="flex items-center gap-2 text-rose-400">
									<AlertTriangle className="w-4 h-4" />
									{t("dangerZone.title", "Danger Zone")}
								</span>
							}
							subtitle={t(
								"dangerZone.description",
								"Irreversible account deletion and data wipe.",
							)}
						>
							<div className="space-y-4 pt-1">
								<div className="p-3.5 rounded-xl border border-rose-500/20 bg-rose-500/[0.04]">
									<p className="text-xs font-semibold text-rose-300">
										{t("dangerZone.deleteAccount.title", "Delete Account")}
									</p>
									<p className="text-xs text-rose-400/70 mt-1 leading-relaxed">
										{t(
											"dangerZone.deleteAccount.description",
											"Permanently erase your account, trading configurations, api keys, and historical records.",
										)}
									</p>
								</div>

								<div className="flex justify-end pt-1">
									<Btn
										variant="danger"
										size="md"
										icon={<AlertTriangle className="w-4 h-4" />}
										onClick={() => setShowDeleteConfirm(true)}
										disabled={isDeleting}
									>
										{t("dangerZone.deleteAccount.button", "Delete My Account")}
									</Btn>
								</div>
							</div>
						</Panel>
					</div>
				)}

				{/* TAB 2: Security & 2FA */}
				{activeTab === "security" && (
					<div className="animate-fade-up">
						<SecuritySettings />
					</div>
				)}

				{/* TAB 3: Achievements */}
				{activeTab === "achievements" && (
					<div className="animate-fade-up">
						<Achievements />
					</div>
				)}
			</div>

			{/* Modal windows */}
			<ConfirmationModal
				open={showResetConfirm}
				onOpenChange={setShowResetConfirm}
				title={t("paperAccountCard.confirmReset.title", "Reset Paper Account?")}
				description={t(
					"paperAccountCard.confirmReset.description",
					"This will reset your paper account balance to default and clear simulated trades.",
				)}
				onConfirm={handleResetConfirm}
				loading={isReseting}
			/>

			<PricingModal
				isOpen={isPricingModalOpen}
				onClose={() => setIsPricingModalOpen(false)}
				currentPlan={accountStatus?.planName || "free"}
			/>

			<ConfirmationModal
				open={showDeleteConfirm}
				onOpenChange={setShowDeleteConfirm}
				title={t("dangerZone.deleteAccount.confirm.title", "Are you absolutely sure?")}
				description={t(
					"dangerZone.deleteAccount.confirm.description",
					"This action cannot be undone. Your account and all data will be permanently deleted.",
				)}
				onConfirm={handleDeleteConfirm}
				loading={isDeleting}
			/>
		</PageLayout>
	);
};

export default AccountPage;
