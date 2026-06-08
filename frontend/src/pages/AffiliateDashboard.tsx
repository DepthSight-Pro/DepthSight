// src/pages/AffiliateDashboard.tsx

import { Copy, Link as LinkIcon, Loader2 } from "lucide-react";
import type React from "react";
import { useState } from "react";
import { Controller, useForm } from "react-hook-form";
import { useTranslation } from "react-i18next";
import { Pagination } from "@/components/shared/Pagination";
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
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import {
	Table,
	TableBody,
	TableCell,
	TableHead,
	TableHeader,
	TableRow,
} from "@/components/ui/table";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useToast } from "@/components/ui/use-toast";
import { useAuth } from "@/context/AuthContext";
import {
	useAffiliateCommissions,
	useAffiliateDashboardStats,
	useAffiliatePayouts,
	useAffiliateReferrals,
	useRequestPayout,
	useUpdatePayoutDetails,
} from "@/lib/api";
import type {
	AffiliateCommission,
	AffiliatePayout,
	AffiliateReferral,
	PayoutDetailsPayload,
} from "@/types/api";

const StatCard = ({
	title,
	value,
	prefix = "",
	suffix = "",
	isLoading,
}: {
	title: string;
	value: string | number;
	prefix?: string;
	suffix?: string;
	isLoading: boolean;
}) => (
	<Card>
		<CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
			<CardTitle className="text-sm font-medium">{title}</CardTitle>
		</CardHeader>
		<CardContent>
			{isLoading ? (
				<Skeleton className="h-8 w-1/2" />
			) : (
				<div className="text-2xl font-bold">
					{prefix}
					{value}
					{suffix}
				</div>
			)}
		</CardContent>
	</Card>
);

const AffiliateDashboard: React.FC = () => {
	const { t } = useTranslation(["affiliate", "common"]);
	const { user } = useAuth();
	const { toast } = useToast();
	const [commissionsPage, setCommissionsPage] = useState(1);
	const [referralsPage, setReferralsPage] = useState(1);
	const [payoutsPage, setPayoutsPage] = useState(1);

	const { data: stats, isLoading: isLoadingStats } =
		useAffiliateDashboardStats();
	const { data: commissionsData, isLoading: isLoadingCommissions } =
		useAffiliateCommissions(commissionsPage, 10);
	const { data: referralsData, isLoading: isLoadingReferrals } =
		useAffiliateReferrals(referralsPage, 10);
	const { data: payoutsData, isLoading: isLoadingPayouts } =
		useAffiliatePayouts(payoutsPage, 10);

	const { mutate: updatePayoutDetails, isPending: isUpdatingDetails } =
		useUpdatePayoutDetails();
	const { mutate: requestPayout, isPending: isRequestingPayout } =
		useRequestPayout();

	const {
		control,
		handleSubmit,
		formState: { errors },
	} = useForm<PayoutDetailsPayload>({
		defaultValues: { usdtTrc20Address: "" },
	});

	const referralLink = `${window.location.protocol}//${window.location.host}/r/${user?.referralCode}`;

	const handleCopyLink = () => {
		navigator.clipboard.writeText(referralLink);
		toast({
			title: t("toast.copiedTitle"),
			description: t("toast.copiedDescription"),
		});
	};

	const onPayoutDetailsSubmit = (data: PayoutDetailsPayload) => {
		updatePayoutDetails(data);
	};

	const formatCurrency = (amount: number) =>
		new Intl.NumberFormat("en-US", {
			style: "currency",
			currency: "USD",
		}).format(amount);
	const formatDate = (dateString: string) =>
		new Date(dateString).toLocaleDateString();

	return (
		<div className="container mx-auto p-4 md:p-6">
			<h1 className="text-3xl font-bold mb-6 flex items-center">
				<LinkIcon className="mr-3 h-8 w-8 text-primary" />
				{t("pageTitle")}
			</h1>

			<Card className="mb-6">
				<CardHeader>
					<CardTitle>{t("referralLinkCard.title")}</CardTitle>
				</CardHeader>
				<CardContent className="flex items-center gap-4">
					<Input value={referralLink} readOnly className="flex-1" />
					<Button onClick={handleCopyLink} size="icon" variant="outline">
						<Copy className="h-4 w-4" />
					</Button>
				</CardContent>
			</Card>

			<h2 className="text-2xl font-semibold mb-4">
				{t("financialsSection.title")}
			</h2>
			<div className="grid gap-4 md:grid-cols-3 mb-6">
				<StatCard
					title={t("financialsSection.pending")}
					value={formatCurrency(stats?.pendingAmount ?? 0)}
					isLoading={isLoadingStats}
				/>
				<StatCard
					title={t("financialsSection.available")}
					value={formatCurrency(stats?.availableAmount ?? 0)}
					isLoading={isLoadingStats}
				/>
				<StatCard
					title={t("financialsSection.paidOut")}
					value={formatCurrency(stats?.totalPaidOut ?? 0)}
					isLoading={isLoadingStats}
				/>
			</div>

			<h2 className="text-2xl font-semibold mb-4">
				{t("funnelSection.title")}
			</h2>
			<div className="grid gap-4 md:grid-cols-3 mb-6">
				<StatCard
					title={t("funnelSection.clicks")}
					value={stats?.clicks ?? 0}
					isLoading={isLoadingStats}
				/>
				<StatCard
					title={t("funnelSection.registrations")}
					value={stats?.registrations ?? 0}
					isLoading={isLoadingStats}
				/>
				<StatCard
					title={t("funnelSection.payingCustomers")}
					value={stats?.payingCustomers ?? 0}
					isLoading={isLoadingStats}
				/>
			</div>

			<Tabs defaultValue="commissions">
				<TabsList className="mb-4">
					<TabsTrigger value="commissions">{t("tabs.commissions")}</TabsTrigger>
					<TabsTrigger value="referrals">{t("tabs.referrals")}</TabsTrigger>
					<TabsTrigger value="payouts">{t("tabs.payouts")}</TabsTrigger>
				</TabsList>

				<TabsContent value="commissions">
					<Card>
						<CardHeader>
							<CardTitle>{t("commissionsTable.title")}</CardTitle>
						</CardHeader>
						<CardContent>
							<Table>
								<TableHeader>
									<TableRow>
										<TableHead>{t("commissionsTable.headers.date")}</TableHead>
										<TableHead>
											{t("commissionsTable.headers.amount")}
										</TableHead>
										<TableHead>
											{t("commissionsTable.headers.description")}
										</TableHead>
										<TableHead>
											{t("commissionsTable.headers.status")}
										</TableHead>
									</TableRow>
								</TableHeader>
								<TableBody>
									{isLoadingCommissions
										? [...Array(5)].map((_, i) => (
												<TableRow key={i}>
													<TableCell colSpan={4}>
														<Skeleton className="h-8 w-full" />
													</TableCell>
												</TableRow>
											))
										: commissionsData?.commissions.map(
												(commission: AffiliateCommission) => (
													<TableRow key={commission.id}>
														<TableCell>
															{formatDate(commission.createdAt)}
														</TableCell>
														<TableCell>
															{formatCurrency(commission.amount)}
														</TableCell>
														<TableCell>{commission.description}</TableCell>
														<TableCell>
															<Badge>
																{t(
																	`statuses.${commission.status}`,
																	commission.status,
																)}
															</Badge>
														</TableCell>
													</TableRow>
												),
											)}
								</TableBody>
							</Table>
							{commissionsData && commissionsData.total > 10 && (
								<Pagination
									currentPage={commissionsPage}
									totalPages={Math.ceil(commissionsData.total / 10)}
									onPageChange={setCommissionsPage}
								/>
							)}
						</CardContent>
					</Card>
				</TabsContent>

				<TabsContent value="referrals">
					<Card>
						<CardHeader>
							<CardTitle>{t("referralsTable.title")}</CardTitle>
						</CardHeader>
						<CardContent>
							<Table>
								<TableHeader>
									<TableRow>
										<TableHead>
											{t("referralsTable.headers.username")}
										</TableHead>
										<TableHead>
											{t("referralsTable.headers.registrationDate")}
										</TableHead>
										<TableHead>
											{t("referralsTable.headers.isPaying")}
										</TableHead>
									</TableRow>
								</TableHeader>
								<TableBody>
									{isLoadingReferrals
										? [...Array(5)].map((_, i) => (
												<TableRow key={i}>
													<TableCell colSpan={3}>
														<Skeleton className="h-8 w-full" />
													</TableCell>
												</TableRow>
											))
										: referralsData?.referrals.map(
												(referral: AffiliateReferral) => (
													<TableRow key={referral.id}>
														<TableCell>{referral.username}</TableCell>
														<TableCell>
															{formatDate(referral.registeredAt)}
														</TableCell>
														<TableCell>
															{referral.isPaying ? (
																<Badge>{t("referralsTable.payingYes")}</Badge>
															) : (
																<Badge variant="secondary">
																	{t("referralsTable.payingNo")}
																</Badge>
															)}
														</TableCell>
													</TableRow>
												),
											)}
								</TableBody>
							</Table>
							{referralsData && referralsData.total > 10 && (
								<Pagination
									currentPage={referralsPage}
									totalPages={Math.ceil(referralsData.total / 10)}
									onPageChange={setReferralsPage}
								/>
							)}
						</CardContent>
					</Card>
				</TabsContent>

				<TabsContent value="payouts">
					<div className="grid md:grid-cols-2 gap-6">
						<Card>
							<CardHeader>
								<CardTitle>{t("payoutsSection.request.title")}</CardTitle>
								<CardDescription>
									{t("payoutsSection.request.description")}
								</CardDescription>
							</CardHeader>
							<CardContent className="space-y-4">
								<div className="text-lg">
									{t("payoutsSection.request.available")}:{" "}
									<span className="font-bold">
										{formatCurrency(stats?.availableAmount ?? 0)}
									</span>
								</div>
								<Button
									onClick={() => requestPayout()}
									disabled={
										isRequestingPayout || (stats?.availableAmount ?? 0) <= 0
									}
								>
									{isRequestingPayout ? (
										<>
											<Loader2 className="mr-2 h-4 w-4 animate-spin" />
											{t("payoutsSection.request.requestingButton")}
										</>
									) : (
										t("payoutsSection.request.requestButton")
									)}
								</Button>
							</CardContent>
						</Card>
						<Card>
							<CardHeader>
								<CardTitle>{t("payoutsSection.details.title")}</CardTitle>
								<CardDescription>
									{t("payoutsSection.details.description")}
								</CardDescription>
							</CardHeader>
							<CardContent>
								<form
									onSubmit={handleSubmit(onPayoutDetailsSubmit)}
									className="space-y-4"
								>
									<div className="space-y-2">
										<Label htmlFor="usdt-address">
											{t("payoutsSection.details.addressLabel")}
										</Label>
										<Controller
											name="usdtTrc20Address"
											control={control}
											rules={{
												required: t("payoutsSection.details.addressRequired"),
											}}
											render={({ field }) => (
												<Input id="usdt-address" {...field} />
											)}
										/>
										{errors.usdtTrc20Address && (
											<p className="text-sm text-destructive">
												{errors.usdtTrc20Address.message}
											</p>
										)}
									</div>
									<Button type="submit" disabled={isUpdatingDetails}>
										{isUpdatingDetails ? (
											<>
												<Loader2 className="mr-2 h-4 w-4 animate-spin" />
												{t("payoutsSection.details.savingButton")}
											</>
										) : (
											t("payoutsSection.details.saveButton")
										)}
									</Button>
								</form>
							</CardContent>
						</Card>
					</div>
					<Card className="mt-6">
						<CardHeader>
							<CardTitle>{t("payoutsTable.title")}</CardTitle>
						</CardHeader>
						<CardContent>
							<Table>
								<TableHeader>
									<TableRow>
										<TableHead>{t("payoutsTable.headers.date")}</TableHead>
										<TableHead>{t("payoutsTable.headers.amount")}</TableHead>
										<TableHead>{t("payoutsTable.headers.status")}</TableHead>
										<TableHead>
											{t("payoutsTable.headers.transactionId")}
										</TableHead>
									</TableRow>
								</TableHeader>
								<TableBody>
									{isLoadingPayouts
										? [...Array(3)].map((_, i) => (
												<TableRow key={i}>
													<TableCell colSpan={4}>
														<Skeleton className="h-8 w-full" />
													</TableCell>
												</TableRow>
											))
										: payoutsData?.payouts.map((payout: AffiliatePayout) => (
												<TableRow key={payout.id}>
													<TableCell>{formatDate(payout.createdAt)}</TableCell>
													<TableCell>{formatCurrency(payout.amount)}</TableCell>
													<TableCell>
														<Badge>
															{t(`statuses.${payout.status}`, payout.status)}
														</Badge>
													</TableCell>
													<TableCell>
														{payout.transactionId || t("common:na")}
													</TableCell>
												</TableRow>
											))}
								</TableBody>
							</Table>
							{payoutsData && payoutsData.total > 10 && (
								<Pagination
									currentPage={payoutsPage}
									totalPages={Math.ceil(payoutsData.total / 10)}
									onPageChange={setPayoutsPage}
								/>
							)}
						</CardContent>
					</Card>
				</TabsContent>
			</Tabs>
		</div>
	);
};

export default AffiliateDashboard;
