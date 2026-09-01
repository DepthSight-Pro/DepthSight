// src/pages/admin/AdminAffiliatesPage.tsx

import type React from "react";
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Pagination } from "@/components/shared/Pagination";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
	Dialog,
	DialogContent,
	DialogDescription,
	DialogFooter,
	DialogHeader,
	DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
	Select,
	SelectContent,
	SelectItem,
	SelectTrigger,
	SelectValue,
} from "@/components/ui/select";
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
import {
	useAdminAffiliates,
	useAdminPayouts,
	useProcessAdminPayout,
} from "@/lib/api";
import type { AdminAffiliatePayout, AdminUser } from "@/types/api";

const AdminAffiliatesPage: React.FC = () => {
	const [page, setPage] = useState(1);
	const [payoutsPage, setPayoutsPage] = useState(1);
	const [payoutStatusFilter, setPayoutStatusFilter] = useState<string>("all");
	const [selectedPayout, setSelectedPayout] =
		useState<AdminAffiliatePayout | null>(null);
	const [transactionIdInput, setTransactionIdInput] = useState<string>("");
	const [isProcessDialogOpen, setIsProcessDialogOpen] = useState<boolean>(false);

	const navigate = useNavigate();

	const { data: affiliatesData, isLoading: isLoadingAffiliates } =
		useAdminAffiliates(page, 10);
	const { data: payoutsData, isLoading: isLoadingPayouts } = useAdminPayouts(
		payoutsPage,
		10,
		payoutStatusFilter,
	);
	const { mutate: processPayout, isPending: isProcessing } =
		useProcessAdminPayout();

	const formatCurrency = (amount: number) =>
		new Intl.NumberFormat("en-US", {
			style: "currency",
			currency: "USD",
		}).format(amount);

	const formatDate = (dateString?: string | null) => {
		if (!dateString) return "-";
		return new Date(dateString).toLocaleString();
	};

	const handleOpenProcessDialog = (payout: AdminAffiliatePayout) => {
		setSelectedPayout(payout);
		setTransactionIdInput("");
		setIsProcessDialogOpen(true);
	};

	const handleConfirmPayout = (status: "paid" | "rejected") => {
		if (!selectedPayout) return;
		processPayout(
			{
				payoutId: selectedPayout.id,
				payload: {
					status,
					transactionId: transactionIdInput.trim() || undefined,
				},
			},
			{
				onSuccess: () => {
					setIsProcessDialogOpen(false);
					setSelectedPayout(null);
				},
			},
		);
	};

	const getStatusBadge = (status: string) => {
		switch (status.toLowerCase()) {
			case "paid":
			case "completed":
				return <Badge className="bg-green-600">Paid</Badge>;
			case "pending":
				return <Badge variant="secondary" className="bg-yellow-600/20 text-yellow-500">Pending</Badge>;
			case "rejected":
			case "failed":
				return <Badge variant="destructive">Rejected</Badge>;
			default:
				return <Badge variant="outline">{status}</Badge>;
		}
	};

	return (
		<div className="space-y-6">
			<div>
				<h1 className="text-3xl font-bold mb-2">Affiliate & Payout Management</h1>
				<p className="text-muted-foreground">
					Track affiliate performance, commission earnings, and process payout requests
				</p>
			</div>

			<Tabs defaultValue="affiliates" className="space-y-4">
				<TabsList>
					<TabsTrigger value="affiliates">All Affiliates</TabsTrigger>
					<TabsTrigger value="payouts">Payout Requests</TabsTrigger>
				</TabsList>

				<TabsContent value="affiliates" className="space-y-4">
					<Card>
						<CardHeader>
							<CardTitle>All Affiliates</CardTitle>
						</CardHeader>
						<CardContent>
							<Table>
								<TableHeader>
									<TableRow>
										<TableHead>ID</TableHead>
										<TableHead>Username</TableHead>
										<TableHead>Commission Rate</TableHead>
										<TableHead>Registrations</TableHead>
										<TableHead>Paying Customers</TableHead>
										<TableHead>Total Earned</TableHead>
										<TableHead>Actions</TableHead>
									</TableRow>
								</TableHeader>
								<TableBody>
									{isLoadingAffiliates
										? [...Array(5)].map((_, i) => (
												<TableRow key={i}>
													<TableCell colSpan={7}>
														<Skeleton className="h-8 w-full" />
													</TableCell>
												</TableRow>
											))
										: affiliatesData?.users.map((affiliate: AdminUser) => (
												<TableRow key={affiliate.id}>
													<TableCell>{affiliate.id}</TableCell>
													<TableCell>{affiliate.username}</TableCell>
													<TableCell>
														{(affiliate.affiliateCommissionRate || 0.4) * 100}%
													</TableCell>
													<TableCell>
														{affiliate.stats?.referralCount ?? 0}
													</TableCell>
													<TableCell>
														{affiliate.stats?.payingReferralCount ?? 0}
													</TableCell>
													<TableCell>
														{formatCurrency(
															affiliate.stats?.totalEarnings ?? 0,
														)}
														{(affiliate.stats?.pendingEarnings ?? 0) > 0 && (
															<span className="text-muted-foreground ml-2 text-sm">
																(
																{formatCurrency(
																	affiliate.stats?.pendingEarnings ?? 0,
																)}{" "}
																pending)
															</span>
														)}
													</TableCell>
													<TableCell>
														<Button
															variant="outline"
															size="sm"
															onClick={() =>
																navigate(`/admin/affiliates/${affiliate.id}`)
															}
														>
															Details
														</Button>
													</TableCell>
												</TableRow>
											))}
								</TableBody>
							</Table>
						</CardContent>
					</Card>

					{affiliatesData && affiliatesData.total > 10 && (
						<Pagination
							currentPage={page}
							totalPages={Math.ceil(affiliatesData.total / 10)}
							onPageChange={setPage}
						/>
					)}
				</TabsContent>

				<TabsContent value="payouts" className="space-y-4">
					<Card>
						<CardHeader className="flex flex-row items-center justify-between">
							<CardTitle>Partner Payout Requests</CardTitle>
							<div className="flex items-center gap-2">
								<Label htmlFor="status-filter" className="text-sm">
									Filter by Status:
								</Label>
								<Select
									value={payoutStatusFilter}
									onValueChange={(val) => {
										setPayoutStatusFilter(val);
										setPayoutsPage(1);
									}}
								>
									<SelectTrigger id="status-filter" className="w-[140px]">
										<SelectValue placeholder="Status" />
									</SelectTrigger>
									<SelectContent>
										<SelectItem value="all">All</SelectItem>
										<SelectItem value="pending">Pending</SelectItem>
										<SelectItem value="paid">Paid</SelectItem>
										<SelectItem value="rejected">Rejected</SelectItem>
									</SelectContent>
								</Select>
							</div>
						</CardHeader>
						<CardContent>
							<Table>
								<TableHeader>
									<TableRow>
										<TableHead>Created</TableHead>
										<TableHead>Partner</TableHead>
										<TableHead>Amount</TableHead>
										<TableHead>USDT TRC-20 Address</TableHead>
										<TableHead>Status</TableHead>
										<TableHead>TXID</TableHead>
										<TableHead>Processed Date</TableHead>
										<TableHead>Actions</TableHead>
									</TableRow>
								</TableHeader>
								<TableBody>
									{isLoadingPayouts
										? [...Array(5)].map((_, i) => (
												<TableRow key={i}>
													<TableCell colSpan={8}>
														<Skeleton className="h-8 w-full" />
													</TableCell>
												</TableRow>
											))
										: !payoutsData?.payouts || payoutsData.payouts.length === 0 ? (
												<TableRow>
													<TableCell colSpan={8} className="text-center py-6 text-muted-foreground">
														No payout requests found.
													</TableCell>
												</TableRow>
											) : (
												payoutsData.payouts.map((payout: AdminAffiliatePayout) => (
													<TableRow key={payout.id}>
														<TableCell className="text-sm">
															{formatDate(payout.createdAt)}
														</TableCell>
														<TableCell>
															<div className="font-medium">
																{payout.username || `User #${payout.userId}`}
															</div>
															<div className="text-xs text-muted-foreground">
																{payout.email}
															</div>
														</TableCell>
														<TableCell className="font-semibold">
															{formatCurrency(payout.amount)}
														</TableCell>
														<TableCell className="font-mono text-xs max-w-[180px] truncate" title={payout.payoutAddress || ""}>
															{payout.payoutAddress || "N/A"}
														</TableCell>
														<TableCell>{getStatusBadge(payout.status)}</TableCell>
														<TableCell className="font-mono text-xs max-w-[150px] truncate" title={payout.transactionId || ""}>
															{payout.transactionId || "-"}
														</TableCell>
														<TableCell className="text-sm">
															{formatDate(payout.processedAt)}
														</TableCell>
														<TableCell>
															{payout.status === "pending" ? (
																<Button
																	size="sm"
																	onClick={() => handleOpenProcessDialog(payout)}
																>
																	Process
																</Button>
															) : (
																<span className="text-xs text-muted-foreground">
																	Completed
																</span>
															)}
														</TableCell>
													</TableRow>
												))
											)}
								</TableBody>
							</Table>
						</CardContent>
					</Card>

					{payoutsData && payoutsData.total > 10 && (
						<Pagination
							currentPage={payoutsPage}
							totalPages={Math.ceil(payoutsData.total / 10)}
							onPageChange={setPayoutsPage}
						/>
					)}
				</TabsContent>
			</Tabs>

			{/* Process Payout Dialog */}
			<Dialog open={isProcessDialogOpen} onOpenChange={setIsProcessDialogOpen}>
				<DialogContent>
					<DialogHeader>
						<DialogTitle>Process Payout Request</DialogTitle>
						<DialogDescription>
							Review payout details and specify the transaction hash before marking as paid.
						</DialogDescription>
					</DialogHeader>

					{selectedPayout && (
						<div className="space-y-4 py-2">
							<div className="grid grid-cols-2 gap-2 text-sm bg-muted/40 p-3 rounded-md">
								<div>
									<span className="text-muted-foreground">Partner:</span>{" "}
									<span className="font-medium">{selectedPayout.username}</span>
								</div>
								<div>
									<span className="text-muted-foreground">Amount:</span>{" "}
									<span className="font-bold text-green-500">
										{formatCurrency(selectedPayout.amount)}
									</span>
								</div>
								<div className="col-span-2">
									<span className="text-muted-foreground">USDT TRC-20 Address:</span>
									<div className="font-mono text-xs mt-1 p-2 bg-background border rounded break-all select-all">
										{selectedPayout.payoutAddress || "No address specified"}
									</div>
								</div>
							</div>

							<div className="space-y-2">
								<Label htmlFor="txid-input">Transaction Hash (TXID)</Label>
								<Input
									id="txid-input"
									placeholder="e.g. 7f8a9b...c4d2"
									value={transactionIdInput}
									onChange={(e) => setTransactionIdInput(e.target.value)}
								/>
								<p className="text-xs text-muted-foreground">
									Paste the blockchain transaction hash for the USDT transfer.
								</p>
							</div>
						</div>
					)}

					<DialogFooter className="gap-2 sm:gap-0">
						<Button
							variant="destructive"
							onClick={() => handleConfirmPayout("rejected")}
							disabled={isProcessing}
						>
							Reject Payout (Refund Commissions)
						</Button>
						<Button
							onClick={() => handleConfirmPayout("paid")}
							disabled={isProcessing || !transactionIdInput.trim()}
						>
							{isProcessing ? "Processing..." : "Confirm & Mark as Paid"}
						</Button>
					</DialogFooter>
				</DialogContent>
			</Dialog>
		</div>
	);
};

export default AdminAffiliatesPage;
