// src/pages/Account.tsx

import { useQueryClient } from "@tanstack/react-query";
import {
	AlertTriangle,
	Award,
	Copy,
	Dna,
	Gift,
	Terminal,
	User,
	Wallet,
} from "lucide-react";
import type React from "react";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate, useSearchParams } from "react-router-dom";
import Achievements from "@/components/research/Achievements";
import { ConfirmationModal } from "@/components/shared/ConfirmationModal";
import { PricingModal } from "@/components/shared/PricingModal";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
	Card,
	CardContent,
	CardDescription,
	CardHeader,
	CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Progress } from "@/components/ui/progress";
import { Separator } from "@/components/ui/separator";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
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
	const [searchParams] = useSearchParams();
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

	const copyToClipboard = (text: string, type: string) => {
		navigator.clipboard.writeText(text).then(() => {
			toast({
				title: t("common:copied"),
				description: `${type} ${t("common:copiedToClipboard")}`,
			});
		});
	};

	const referralLink = user?.referralCode
		? `${window.location.origin}/register?ref=${user.referralCode}`
		: "";

	const handleResetConfirm = () => {
		resetPaperAccount(undefined, {
			onSuccess: () => setShowResetConfirm(false),
		});
	};

	const handleDeleteConfirm = () => {
		deleteAccount(undefined, {
			onSuccess: () => {
				// Logout and redirect are now handled by the AuthContext wrapper around logout
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
			<div className="p-4 md:p-8 space-y-6">
				<h1 className="text-3xl font-bold tracking-tight">{t("pageTitle")}</h1>
				<div className="grid gap-6 md:grid-cols-2">
					{[...Array(4)].map((_, i) => (
						<Card key={i}>
							<CardHeader>
								<Skeleton className="h-6 w-3/4" />
							</CardHeader>
							<CardContent>
								<Skeleton className="h-20 w-full" />
							</CardContent>
						</Card>
					))}
				</div>
			</div>
		);
	}

	if (isError) {
		return (
			<div className="p-4 md:p-8">
				<Alert variant="destructive">
					<Terminal className="h-4 w-4" />
					<AlertTitle>{t("common:errorTitle")}</AlertTitle>
					<AlertDescription>{error.message}</AlertDescription>
				</Alert>
			</div>
		);
	}

	return (
		<div className="p-4 md:p-8 space-y-6">
			<h1 className="text-3xl font-bold tracking-tight flex items-center">
				<User className="mr-3 h-8 w-8 text-primary" />
				{t("pageTitle")}
			</h1>

			<Tabs defaultValue="account">
				<TabsList>
					<TabsTrigger value="account">
						<User className="mr-2 h-4 w-4" />
						{t("accountTab")}
					</TabsTrigger>
					<TabsTrigger value="achievements">
						<Award className="mr-2 h-4 w-4" />
						{t("achievementsTab")}
					</TabsTrigger>
				</TabsList>
				<TabsContent value="account">
					<div className="grid gap-6 md:grid-cols-2 mt-4">
						{/* Card 1: My Plan */}
						<Card>
							<CardHeader>
								<CardTitle>{t("myPlanCard.title")}</CardTitle>
								<CardDescription>
									{accountStatus?.planExpiresAt
										? `${t("myPlanCard.planActiveUntil")} ${new Date(accountStatus.planExpiresAt).toLocaleDateString()}`
										: t("myPlanCard.description")}
								</CardDescription>
							</CardHeader>
							<CardContent className="flex items-center justify-between">
								<span className="text-2xl font-bold capitalize">
									{t(`plans.${accountStatus?.planName}`, {
										defaultValue: accountStatus?.planName,
									})}
								</span>
								<Button onClick={() => setIsPricingModalOpen(true)}>
									{t("myPlanCard.changePlanButton")}
								</Button>
							</CardContent>
						</Card>

						{/* Card 2: Paper Account */}
						<Card>
							<CardHeader>
								<CardTitle className="flex items-center">
									<Wallet className="mr-2" /> {t("paperAccountCard.title")}
								</CardTitle>
								<CardDescription>
									{t("paperAccountCard.description")}
								</CardDescription>
							</CardHeader>
							<CardContent className="flex items-center justify-between">
								{isLoadingPaperWallet ? (
									<Skeleton className="h-8 w-32" />
								) : (
									<span className="text-2xl font-bold font-mono">
										$
										{usdtBalance.toLocaleString("en-US", {
											minimumFractionDigits: 2,
											maximumFractionDigits: 2,
										})}
									</span>
								)}
								<Button
									variant="outline"
									onClick={() => setShowResetConfirm(true)}
									disabled={isReseting}
								>
									{t("paperAccountCard.resetButton")}
								</Button>
							</CardContent>
						</Card>

						{/* Card 3: Quotas & Bonuses */}
						<Card>
							<CardHeader>
								<CardTitle>{t("quotaUsageCard.title")}</CardTitle>
								<CardDescription>
									{t("quotaUsageCard.description")}
								</CardDescription>
							</CardHeader>
							<CardContent className="space-y-4">
								{accountStatus?.quotas.map((quota) => (
									<div key={quota.name}>
										<div className="flex justify-between text-sm mb-1">
											<span className="font-medium">
												{t(`quotas.${quota.name}`, {
													defaultValue: quota.name,
												})}
											</span>
											<span className="text-muted-foreground">
												{quota.limit === -1
													? `${quota.used} / ${t("quotaUsageCard.unlimited")}`
													: `${quota.used} / ${quota.limit}`}
											</span>
										</div>
										{quota.limit !== -1 && (
											<Progress value={(quota.used / quota.limit) * 100} />
										)}
									</div>
								))}
							</CardContent>
						</Card>

						{/* Card 4: Referrals */}
						<Card>
							<CardHeader>
								<CardTitle>{t("referralCard.title")}</CardTitle>
								<CardDescription>
									{t("referralCard.description", {
										referrerBonus:
											accountStatus?.referralProgram?.referrer_bonus?.quantity,
										referredBonus:
											accountStatus?.referralProgram?.referred_user_bonus
												?.quantity,
									})}
								</CardDescription>
							</CardHeader>
							<CardContent className="space-y-4">
								<div>
									<label className="text-sm font-medium">
										{t("referralCard.codeLabel")}
									</label>
									<div className="flex items-center space-x-2 mt-1">
										<Input
											readOnly
											value={user?.referralCode || "..."}
											className="font-mono"
										/>
										<Button
											variant="outline"
											size="icon"
											onClick={() =>
												copyToClipboard(
													user?.referralCode || "",
													t("referralCard.codeLabel"),
												)
											}
										>
											<Copy className="h-4 w-4" />
										</Button>
									</div>
								</div>
								<div>
									<label className="text-sm font-medium">
										{t("referralCard.linkLabel")}
									</label>
									<div className="flex items-center space-x-2 mt-1">
										<Input
											readOnly
											value={referralLink}
											className="font-mono"
										/>
										<Button
											variant="outline"
											size="icon"
											onClick={() =>
												copyToClipboard(
													referralLink,
													t("referralCard.linkLabel"),
												)
											}
										>
											<Copy className="h-4 w-4" />
										</Button>
									</div>
								</div>

								{((activeBonuses && activeBonuses.length > 0) ||
									(pendingBonuses && pendingBonuses.length > 0)) && (
									<>
										<Separator className="my-4" />
										<div className="space-y-3">
											<h4 className="flex items-center text-sm font-semibold">
												<Gift className="mr-2 h-4 w-4" />
												{t("bonusesCard.title")}
											</h4>
											<p className="text-sm text-muted-foreground">
												{t("bonusesCard.description")}
											</p>

											{activeBonuses && activeBonuses.length > 0 && (
												<ul className="space-y-2 pt-2">
													{activeBonuses.map((bonus) => (
														<li
															key={`active-${bonus.featureName}`}
															className="flex justify-between items-center p-2 bg-green-50 dark:bg-green-950/20 border border-green-200 dark:border-green-800 rounded-md text-sm"
														>
															<span className="font-medium">
																{t(
																	`bonusesCard.features.${bonus.featureName}`,
																	{ defaultValue: bonus.featureName },
																)}
															</span>
															<span className="font-bold text-base text-green-700 dark:text-green-400">
																{bonus.quantity}
															</span>
														</li>
													))}
												</ul>
											)}

											{pendingBonuses && pendingBonuses.length > 0 && (
												<div className="space-y-2">
													<p className="text-xs text-muted-foreground italic">
														{t("bonusesCard.pendingNote")}
													</p>
													<ul className="space-y-2">
														{pendingBonuses.map((bonus) => (
															<li
																key={`pending-${bonus.featureName}`}
																className="flex justify-between items-center p-2 bg-amber-50 dark:bg-amber-950/20 border border-amber-200 dark:border-amber-800 rounded-md text-sm opacity-70"
															>
																<span className="font-medium">
																	{t(
																		`bonusesCard.features.${bonus.featureName}`,
																		{ defaultValue: bonus.featureName },
																	)}{" "}
																	({t("bonusesCard.pending")})
																</span>
																<span className="font-bold text-base text-amber-700 dark:text-amber-400">
																	{bonus.quantity}
																</span>
															</li>
														))}
													</ul>
												</div>
											)}
										</div>
									</>
								)}
							</CardContent>
						</Card>

						{/* Card: Genetics Laboratory */}
						<Card className="hover:shadow-lg transition-shadow">
							<CardHeader>
								<CardTitle className="flex items-center">
									<Dna className="mr-2 text-green-500" />{" "}
									{t("geneticsLabCard.title")}
								</CardTitle>
								<CardDescription>
									{t("geneticsLabCard.description")}
								</CardDescription>
							</CardHeader>
							<CardContent className="space-y-3">
								<div className="flex items-center justify-between">
									<span className="text-sm text-muted-foreground">
										{t("geneticsLabCard.genesDiscovered")}
									</span>
									<span className="text-2xl font-bold text-green-500">
										{genesData?.total || 0}
									</span>
								</div>
								<div className="flex justify-around pt-2">
									<div className="text-center">
										<Badge
											variant="outline"
											className="bg-yellow-500/10 text-yellow-500 border-yellow-500/30"
										>
											{geneStats?.rarityBreakdown?.LEGENDARY || 0}
										</Badge>
										<div className="text-xs text-muted-foreground mt-1">
											{t("geneticsLabCard.legend")}
										</div>
									</div>
									<div className="text-center">
										<Badge
											variant="outline"
											className="bg-purple-500/10 text-purple-500 border-purple-500/30"
										>
											{geneStats?.rarityBreakdown?.EPIC || 0}
										</Badge>
										<div className="text-xs text-muted-foreground mt-1">
											{t("geneticsLabCard.epic")}
										</div>
									</div>
									<div className="text-center">
										<Badge
											variant="outline"
											className="bg-blue-500/10 text-blue-500 border-blue-500/30"
										>
											{geneStats?.rarityBreakdown?.RARE || 0}
										</Badge>
										<div className="text-xs text-muted-foreground mt-1">
											{t("geneticsLabCard.rare")}
										</div>
									</div>
									<div className="text-center">
										<Badge
											variant="outline"
											className="bg-gray-500/10 text-gray-500 border-gray-500/30"
										>
											{geneStats?.rarityBreakdown?.COMMON || 0}
										</Badge>
										<div className="text-xs text-muted-foreground mt-1">
											{t("geneticsLabCard.common")}
										</div>
									</div>
								</div>
								<Button
									variant="outline"
									className="w-full mt-2"
									onClick={() => (window.location.href = "/lab")}
								>
									{t("geneticsLabCard.viewCollectionButton")}
								</Button>
							</CardContent>
						</Card>

						{/* Danger Zone Card */}
						<Card className="border-destructive">
							<CardHeader>
								<CardTitle className="flex items-center text-destructive">
									<AlertTriangle className="mr-2" /> {t("dangerZone.title")}
								</CardTitle>
								<CardDescription>{t("dangerZone.description")}</CardDescription>
							</CardHeader>
							<CardContent>
								<div>
									<p className="font-semibold">
										{t("dangerZone.deleteAccount.title")}
									</p>
									<p className="text-sm text-muted-foreground">
										{t("dangerZone.deleteAccount.description")}
									</p>
								</div>
								<div className="flex justify-end mt-10">
									<Button
										variant="destructive"
										onClick={() => setShowDeleteConfirm(true)}
										disabled={isDeleting}
									>
										{t("dangerZone.deleteAccount.button")}
									</Button>
								</div>
							</CardContent>
						</Card>
					</div>
				</TabsContent>
				<TabsContent value="achievements">
					<Achievements />
				</TabsContent>
			</Tabs>

			{/* Modal windows */}
			<ConfirmationModal
				open={showResetConfirm}
				onOpenChange={setShowResetConfirm}
				title={t("paperAccountCard.confirmReset.title")}
				description={t("paperAccountCard.confirmReset.description")}
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
				title={t("dangerZone.deleteAccount.confirm.title")}
				description={t("dangerZone.deleteAccount.confirm.description")}
				onConfirm={handleDeleteConfirm}
				loading={isDeleting}
			/>
		</div>
	);
};

export default AccountPage;
