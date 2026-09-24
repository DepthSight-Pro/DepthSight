// src/pages/AffiliateDashboard.tsx

import {
	Check,
	Coins,
	Copy,
	CreditCard,
	DollarSign,
	Link as LinkIcon,
	Loader2,
	MousePointerClick,
	UserCheck,
	UserPlus,
	Users,
	Wallet,
} from "lucide-react";
import type React from "react";
import { useEffect, useState } from "react";
import { Controller, useForm } from "react-hook-form";
import { useTranslation } from "react-i18next";
import { PageLayout } from "@/components/layout/PageLayout";
import { Pagination } from "@/components/shared/Pagination";
import { Input } from "@/components/ui/input";
import {
	Badge,
	Btn,
	Panel,
	Segmented,
} from "@/components/ui/quant-ui";
import { Skeleton } from "@/components/ui/skeleton";
import {
	Table,
	TableBody,
	TableCell,
	TableHead,
	TableHeader,
	TableRow,
} from "@/components/ui/table";
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

type AffiliateTab = "commissions" | "referrals" | "payouts";

const CyberStatCard = ({
	title,
	value,
	prefix = "",
	suffix = "",
	isLoading,
	accent = "#00d4ff",
	icon,
}: {
	title: string;
	value: string | number;
	prefix?: string;
	suffix?: string;
	isLoading: boolean;
	accent?: string;
	icon?: React.ReactNode;
}) => (
	<div className="glass relative rounded-2xl p-4 overflow-hidden border border-white/10 hover:border-white/20 transition-all animate-fade-up">
		<div
			className="pointer-events-none absolute -right-8 -top-8 h-28 w-28 rounded-full blur-2xl opacity-20"
			style={{ background: accent }}
		/>
		<div className="flex items-center justify-between">
			<span className="text-[11px] font-semibold uppercase tracking-wider text-white/40 font-mono">
				{title}
			</span>
			{icon && <span className="text-white/30">{icon}</span>}
		</div>
		<div className="mt-2.5">
			{isLoading ? (
				<div className="h-8 w-28 rounded-lg bg-white/10 animate-pulse" />
			) : (
				<div className="text-2xl font-bold font-mono tracking-tight text-white">
					{prefix}
					{typeof value === "number" ? value.toLocaleString() : value}
					{suffix}
				</div>
			)}
		</div>
	</div>
);

const AffiliateDashboard: React.FC = () => {
	const { t } = useTranslation(["affiliate", "common"]);
	const { user } = useAuth();
	const { toast } = useToast();
	const [activeTab, setActiveTab] = useState<AffiliateTab>("commissions");
	const [isCopied, setIsCopied] = useState(false);

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
		reset,
		formState: { errors },
	} = useForm<PayoutDetailsPayload>({
		defaultValues: { usdtTrc20Address: "" },
	});

	useEffect(() => {
		if (stats?.payoutAddress) {
			reset({ usdtTrc20Address: stats.payoutAddress });
		}
	}, [stats?.payoutAddress, reset]);

	const referralLink = `${window.location.protocol}//${window.location.host}/r/${user?.referralCode}`;

	const handleCopyLink = () => {
		navigator.clipboard.writeText(referralLink).then(() => {
			setIsCopied(true);
			toast({
				title: t("toast.copiedTitle", "Copied!"),
				description: t(
					"toast.copiedDescription",
					"Referral link copied to clipboard",
				),
			});
			setTimeout(() => setIsCopied(false), 2500);
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
		<PageLayout title={t("pageTitle", "Affiliate Dashboard")} hideHeader>
			<div className="space-y-6">
				{/* Referral link card */}
				<Panel
					title={
						<span className="flex items-center gap-2">
							<LinkIcon className="w-4 h-4 text-cyan" />
							{t("referralLinkCard.title", "Affiliate Link")}
						</span>
					}
					subtitle={t(
						"referralLinkCard.description",
						"Share this link with other traders and earn 40% recurring commissions.",
					)}
				>
					<div className="flex items-center gap-2.5 pt-1">
						<Input
							value={referralLink}
							readOnly
							className="flex-1 font-mono text-cyan bg-white/[0.03] border-white/10 text-xs h-10 tracking-wide"
						/>
						<Btn
							variant="outline"
							size="md"
							className="h-10 px-4 shrink-0"
							icon={
								isCopied ? (
									<Check className="w-4 h-4 text-emerald-400" />
								) : (
									<Copy className="w-4 h-4" />
								)
							}
							onClick={handleCopyLink}
						>
							{isCopied ? "OK" : t("common:copy", "Copy")}
						</Btn>
					</div>
				</Panel>

				{/* Financials stats row */}
				<div className="space-y-2.5">
					<div className="text-xs font-semibold uppercase tracking-wider text-white/50 font-mono">
						{t("financialsSection.title", "Financial Overview")}
					</div>
					<div className="grid gap-3.5 md:grid-cols-3">
						<CyberStatCard
							title={t("financialsSection.pending", "Pending Payout")}
							value={formatCurrency(stats?.pendingAmount ?? 0)}
							isLoading={isLoadingStats}
							accent="#f59e0b"
							icon={<Coins className="w-4 h-4 text-amber-400" />}
						/>
						<CyberStatCard
							title={t("financialsSection.available", "Available Balance")}
							value={formatCurrency(stats?.availableAmount ?? 0)}
							isLoading={isLoadingStats}
							accent="#10e0a0"
							icon={<Wallet className="w-4 h-4 text-emerald-400" />}
						/>
						<CyberStatCard
							title={t("financialsSection.paidOut", "Total Paid Out")}
							value={formatCurrency(stats?.totalPaidOut ?? 0)}
							isLoading={isLoadingStats}
							accent="#00d4ff"
							icon={<CreditCard className="w-4 h-4 text-cyan" />}
						/>
					</div>
				</div>

				{/* Funnel stats row */}
				<div className="space-y-2.5">
					<div className="text-xs font-semibold uppercase tracking-wider text-white/50 font-mono">
						{t("funnelSection.title", "Conversion Funnel")}
					</div>
					<div className="grid gap-3.5 md:grid-cols-3">
						<CyberStatCard
							title={t("funnelSection.clicks", "Total Clicks")}
							value={stats?.clicks ?? 0}
							isLoading={isLoadingStats}
							accent="#6366f1"
							icon={<MousePointerClick className="w-4 h-4 text-indigo-400" />}
						/>
						<CyberStatCard
							title={t("funnelSection.registrations", "Registrations")}
							value={stats?.registrations ?? 0}
							isLoading={isLoadingStats}
							accent="#a855f7"
							icon={<UserPlus className="w-4 h-4 text-purple-400" />}
						/>
						<CyberStatCard
							title={t("funnelSection.payingCustomers", "Active Subscribers")}
							value={stats?.payingCustomers ?? 0}
							isLoading={isLoadingStats}
							accent="#10e0a0"
							icon={<UserCheck className="w-4 h-4 text-emerald-400" />}
						/>
					</div>
				</div>

				{/* Tabs Navigation */}
				<div className="pt-2">
					<Segmented<AffiliateTab>
						size="md"
						value={activeTab}
						onChange={setActiveTab}
						options={[
							{
								value: "commissions",
								label: t("tabs.commissions", "Commissions"),
								icon: <DollarSign className="w-3.5 h-3.5" />,
							},
							{
								value: "referrals",
								label: t("tabs.referrals", "Referrals"),
								icon: <Users className="w-3.5 h-3.5" />,
							},
							{
								value: "payouts",
								label: t("tabs.payouts", "Payouts"),
								icon: <Wallet className="w-3.5 h-3.5" />,
							},
						]}
					/>
				</div>

				{/* TAB 1: Commissions Table */}
				{activeTab === "commissions" && (
					<Panel
						noPad
						title={t("commissionsTable.title", "Commissions History")}
					>
						<div className="overflow-x-auto">
							<Table>
								<TableHeader>
									<TableRow className="border-white/5 hover:bg-transparent">
										<TableHead className="font-mono text-[11px] uppercase tracking-wider text-white/50">
											{t("commissionsTable.headers.date", "Date")}
										</TableHead>
										<TableHead className="font-mono text-[11px] uppercase tracking-wider text-white/50">
											{t("commissionsTable.headers.amount", "Amount")}
										</TableHead>
										<TableHead className="font-mono text-[11px] uppercase tracking-wider text-white/50">
											{t("commissionsTable.headers.description", "Description")}
										</TableHead>
										<TableHead className="font-mono text-[11px] uppercase tracking-wider text-white/50">
											{t("commissionsTable.headers.status", "Status")}
										</TableHead>
									</TableRow>
								</TableHeader>
								<TableBody>
									{isLoadingCommissions
										? [...Array(5)].map((_, i) => (
												<TableRow key={i} className="border-white/5">
													<TableCell colSpan={4}>
														<Skeleton className="h-7 w-full bg-white/5" />
													</TableCell>
												</TableRow>
											))
										: commissionsData?.commissions.map(
												(commission: AffiliateCommission) => {
													const statusTone =
														commission.status === "paid"
															? "profit"
															: commission.status === "pending"
																? "amber"
																: "loss";

													return (
														<TableRow
															key={commission.id}
															className="border-white/5 hover:bg-white/[0.03] transition-colors"
														>
															<TableCell className="font-mono text-xs text-white/70">
																{formatDate(commission.createdAt)}
															</TableCell>
															<TableCell className="font-mono text-sm font-semibold text-emerald-400">
																{formatCurrency(commission.amount)}
															</TableCell>
															<TableCell className="text-xs text-white/80">
																{commission.description}
															</TableCell>
															<TableCell>
																<Badge tone={statusTone} dot>
																	{t(
																		`statuses.${commission.status}`,
																		commission.status,
																	)}
																</Badge>
															</TableCell>
														</TableRow>
													);
												},
											)}
									{commissionsData &&
										commissionsData.commissions.length === 0 && (
											<TableRow>
												<TableCell
													colSpan={4}
													className="text-center py-8 text-xs text-white/40 italic"
												>
													No commissions recorded yet.
												</TableCell>
											</TableRow>
										)}
								</TableBody>
							</Table>
						</div>
						{commissionsData && commissionsData.total > 10 && (
							<div className="p-4 border-t border-white/5">
								<Pagination
									currentPage={commissionsPage}
									totalPages={Math.ceil(commissionsData.total / 10)}
									onPageChange={setCommissionsPage}
								/>
							</div>
						)}
					</Panel>
				)}

				{/* TAB 2: Referrals Table */}
				{activeTab === "referrals" && (
					<Panel noPad title={t("referralsTable.title", "Referred Users")}>
						<div className="overflow-x-auto">
							<Table>
								<TableHeader>
									<TableRow className="border-white/5 hover:bg-transparent">
										<TableHead className="font-mono text-[11px] uppercase tracking-wider text-white/50">
											{t("referralsTable.headers.username", "Username")}
										</TableHead>
										<TableHead className="font-mono text-[11px] uppercase tracking-wider text-white/50">
											{t("referralsTable.headers.registrationDate", "Registered")}
										</TableHead>
										<TableHead className="font-mono text-[11px] uppercase tracking-wider text-white/50">
											{t("referralsTable.headers.isPaying", "Paying Customer")}
										</TableHead>
									</TableRow>
								</TableHeader>
								<TableBody>
									{isLoadingReferrals
										? [...Array(5)].map((_, i) => (
												<TableRow key={i} className="border-white/5">
													<TableCell colSpan={3}>
														<Skeleton className="h-7 w-full bg-white/5" />
													</TableCell>
												</TableRow>
											))
										: referralsData?.referrals.map(
												(referral: AffiliateReferral) => (
													<TableRow
														key={referral.id}
														className="border-white/5 hover:bg-white/[0.03] transition-colors"
													>
														<TableCell className="font-mono text-xs text-white">
															{referral.username}
														</TableCell>
														<TableCell className="font-mono text-xs text-white/60">
															{formatDate(referral.registeredAt)}
														</TableCell>
														<TableCell>
															{referral.isPaying ? (
																<Badge tone="profit" dot>
																	{t("referralsTable.payingYes", "Active Subscriber")}
																</Badge>
															) : (
																<Badge tone="neutral">
																	{t("referralsTable.payingNo", "Free Tier")}
																</Badge>
															)}
														</TableCell>
													</TableRow>
												),
											)}
									{referralsData && referralsData.referrals.length === 0 && (
										<TableRow>
											<TableCell
												colSpan={3}
												className="text-center py-8 text-xs text-white/40 italic"
											>
												No referred users yet. Share your link to start earning!
											</TableCell>
										</TableRow>
									)}
								</TableBody>
							</Table>
						</div>
						{referralsData && referralsData.total > 10 && (
							<div className="p-4 border-t border-white/5">
								<Pagination
									currentPage={referralsPage}
									totalPages={Math.ceil(referralsData.total / 10)}
									onPageChange={setReferralsPage}
								/>
							</div>
						)}
					</Panel>
				)}

				{/* TAB 3: Payouts */}
				{activeTab === "payouts" && (
					<div className="space-y-6">
						<div className="grid md:grid-cols-2 gap-5">
							{/* Request Payout Panel */}
							<Panel
								title={t("payoutsSection.request.title", "Request Payout")}
								subtitle={t(
									"payoutsSection.request.description",
									"Withdraw accumulated commissions to your USDT TRC-20 wallet.",
								)}
							>
								<div className="space-y-4 pt-1">
									<div className="p-4 rounded-xl bg-white/[0.02] border border-white/5 flex items-center justify-between">
										<div>
											<div className="text-[11px] uppercase tracking-wider font-mono text-white/40">
												{t("payoutsSection.request.available", "Available Balance")}
											</div>
											<div className="text-2xl font-bold font-mono text-emerald-400 mt-0.5">
												{formatCurrency(stats?.availableAmount ?? 0)}
											</div>
										</div>
										<Badge
											tone={
												(stats?.availableAmount ?? 0) >= 50 ? "profit" : "amber"
											}
											dot
										>
											{(stats?.availableAmount ?? 0) >= 50
												? "READY TO WITHDRAW"
												: "MIN $50.00"}
										</Badge>
									</div>

									<Btn
										variant="primary"
										size="md"
										className="w-full"
										onClick={() => requestPayout()}
										disabled={
											isRequestingPayout ||
											(stats?.availableAmount ?? 0) < 50 ||
											!stats?.payoutAddress
										}
										icon={
											isRequestingPayout ? (
												<Loader2 className="w-4 h-4 animate-spin" />
											) : (
												<Wallet className="w-4 h-4" />
											)
										}
									>
										{isRequestingPayout
											? t("payoutsSection.request.requestingButton", "Requesting...")
											: t("payoutsSection.request.requestButton", "Withdraw Funds")}
									</Btn>

									{!stats?.payoutAddress && (
										<p className="text-xs text-amber-400/90 font-mono">
											Please specify and save your USDT TRC-20 payout address below first.
										</p>
									)}
									{stats?.payoutAddress && (stats?.availableAmount ?? 0) < 50 && (
										<p className="text-xs text-white/40 font-mono">
											Minimum payout threshold: $50.00.
										</p>
									)}
								</div>
							</Panel>

							{/* Payout Details Panel */}
							<Panel
								title={t("payoutsSection.details.title", "Payout Details")}
								subtitle={t(
									"payoutsSection.details.description",
									"Specify your TRC-20 wallet address for commission payouts.",
								)}
							>
								<form
									onSubmit={handleSubmit(onPayoutDetailsSubmit)}
									className="space-y-4 pt-1"
								>
									<div className="space-y-1.5">
										<label
											htmlFor="usdt-address"
											className="text-xs font-mono uppercase tracking-wider text-white/60"
										>
											{t("payoutsSection.details.addressLabel", "USDT TRC-20 Address")}
										</label>
										<Controller
											name="usdtTrc20Address"
											control={control}
											rules={{
												required: t(
													"payoutsSection.details.addressRequired",
													"Address is required",
												),
											}}
											render={({ field }) => (
												<Input
													id="usdt-address"
													{...field}
													placeholder="T..."
													className="font-mono text-xs bg-white/[0.03] border-white/10 text-cyan h-10 tracking-wider"
												/>
											)}
										/>
										{errors.usdtTrc20Address && (
											<p className="text-xs text-rose-400 font-mono">
												{errors.usdtTrc20Address.message}
											</p>
										)}
									</div>
									<Btn
										type="submit"
										variant="outline"
										size="md"
										className="w-full"
										disabled={isUpdatingDetails}
										icon={
											isUpdatingDetails ? (
												<Loader2 className="w-4 h-4 animate-spin" />
											) : undefined
										}
									>
										{isUpdatingDetails
											? t("payoutsSection.details.savingButton", "Saving...")
											: t("payoutsSection.details.saveButton", "Save Payout Address")}
									</Btn>
								</form>
							</Panel>
						</div>

						{/* Payouts Table */}
						<Panel noPad title={t("payoutsTable.title", "Payout History")}>
							<div className="overflow-x-auto">
								<Table>
									<TableHeader>
										<TableRow className="border-white/5 hover:bg-transparent">
											<TableHead className="font-mono text-[11px] uppercase tracking-wider text-white/50">
												{t("payoutsTable.headers.date", "Date")}
											</TableHead>
											<TableHead className="font-mono text-[11px] uppercase tracking-wider text-white/50">
												{t("payoutsTable.headers.amount", "Amount")}
											</TableHead>
											<TableHead className="font-mono text-[11px] uppercase tracking-wider text-white/50">
												{t("payoutsTable.headers.status", "Status")}
											</TableHead>
											<TableHead className="font-mono text-[11px] uppercase tracking-wider text-white/50">
												{t("payoutsTable.headers.transactionId", "TXID / Ref")}
											</TableHead>
										</TableRow>
									</TableHeader>
									<TableBody>
										{isLoadingPayouts
											? [...Array(3)].map((_, i) => (
													<TableRow key={i} className="border-white/5">
														<TableCell colSpan={4}>
															<Skeleton className="h-7 w-full bg-white/5" />
														</TableCell>
													</TableRow>
												))
											: payoutsData?.payouts.map((payout: AffiliatePayout) => {
													const statusTone =
														payout.status === "paid" ||
														payout.status === "completed"
															? "profit"
															: payout.status === "pending"
																? "amber"
																: "loss";

													return (
														<TableRow
															key={payout.id}
															className="border-white/5 hover:bg-white/[0.03] transition-colors"
														>
															<TableCell className="font-mono text-xs text-white/70">
																{formatDate(payout.createdAt)}
															</TableCell>
															<TableCell className="font-mono text-sm font-semibold text-emerald-400">
																{formatCurrency(payout.amount)}
															</TableCell>
															<TableCell>
																<Badge tone={statusTone} dot>
																	{t(
																		`statuses.${payout.status}`,
																		payout.status,
																	)}
																</Badge>
															</TableCell>
															<TableCell className="font-mono text-xs text-white/50">
																{payout.transactionId ? (
																	<span className="truncate max-w-[200px] inline-block text-cyan">
																		{payout.transactionId}
																	</span>
																) : (
																	t("common:na", "N/A")
																)}
															</TableCell>
														</TableRow>
													);
												})}
										{payoutsData && payoutsData.payouts.length === 0 && (
											<TableRow>
												<TableCell
													colSpan={4}
													className="text-center py-8 text-xs text-white/40 italic"
												>
													No payout requests yet.
												</TableCell>
											</TableRow>
										)}
									</TableBody>
								</Table>
							</div>
							{payoutsData && payoutsData.total > 10 && (
								<div className="p-4 border-t border-white/5">
									<Pagination
										currentPage={payoutsPage}
										totalPages={Math.ceil(payoutsData.total / 10)}
										onPageChange={setPayoutsPage}
									/>
								</div>
							)}
						</Panel>
					</div>
				)}
			</div>
		</PageLayout>
	);
};

export default AffiliateDashboard;
