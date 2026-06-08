// src/pages/admin/affiliates/AdminAffiliateDetailPage.tsx

import type React from "react";
import { useState } from "react";
import { useParams } from "react-router-dom";
import { Pagination } from "@/components/shared/Pagination";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
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
	useAdminAffiliateCommissions,
	useAdminAffiliateReferrals,
} from "@/lib/api";
import type {
	AdminAffiliateCommission,
	AdminAffiliateReferral,
} from "@/types/api";

const AdminAffiliateDetailPage: React.FC = () => {
	const { id } = useParams<{ id: string }>();
	const userId = Number(id);

	const [commissionsPage, setCommissionsPage] = useState(1);
	const [referralsPage, setReferralsPage] = useState(1);

	const { data: commissionsData, isLoading: isLoadingCommissions } =
		useAdminAffiliateCommissions(userId, commissionsPage, 10);
	const { data: referralsData, isLoading: isLoadingReferrals } =
		useAdminAffiliateReferrals(userId, referralsPage, 10);

	// TODO: Fetch affiliate details to get username for the title
	const affiliateUsername = `User #${id}`;

	const formatCurrency = (amount: number) =>
		new Intl.NumberFormat("en-US", {
			style: "currency",
			currency: "USD",
		}).format(amount);
	const formatDate = (dateString: string) =>
		new Date(dateString).toLocaleDateString();

	return (
		<div>
			<h1 className="text-3xl font-bold mb-6">
				Affiliate Stats: {affiliateUsername}
			</h1>

			<Tabs defaultValue="commissions">
				<TabsList className="mb-4">
					<TabsTrigger value="commissions">Commissions</TabsTrigger>
					<TabsTrigger value="referrals">Referrals</TabsTrigger>
				</TabsList>

				<TabsContent value="commissions">
					<Card>
						<CardHeader>
							<CardTitle>Commission History</CardTitle>
						</CardHeader>
						<CardContent>
							<Table>
								<TableHeader>
									<TableRow>
										<TableHead>Date</TableHead>
										<TableHead>Amount</TableHead>
										<TableHead>Referral ID</TableHead>
										<TableHead>Status</TableHead>
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
												(commission: AdminAffiliateCommission) => (
													<TableRow key={commission.id}>
														<TableCell>
															{formatDate(commission.createdAt)}
														</TableCell>
														<TableCell>
															{formatCurrency(commission.amount)}
														</TableCell>
														<TableCell>{commission.referralId}</TableCell>
														<TableCell>
															<Badge>{commission.status}</Badge>
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
							<CardTitle>Referred Users</CardTitle>
						</CardHeader>
						<CardContent>
							<Table>
								<TableHeader>
									<TableRow>
										<TableHead>ID</TableHead>
										<TableHead>Username</TableHead>
										<TableHead>Email</TableHead>
										<TableHead>Registration Date</TableHead>
										<TableHead>Plan</TableHead>
									</TableRow>
								</TableHeader>
								<TableBody>
									{isLoadingReferrals
										? [...Array(5)].map((_, i) => (
												<TableRow key={i}>
													<TableCell colSpan={5}>
														<Skeleton className="h-8 w-full" />
													</TableCell>
												</TableRow>
											))
										: referralsData?.referrals.map(
												(referral: AdminAffiliateReferral) => (
													<TableRow key={referral.id}>
														<TableCell>{referral.id}</TableCell>
														<TableCell>{referral.username}</TableCell>
														<TableCell>{referral.email}</TableCell>
														<TableCell>
															{formatDate(referral.registeredAt)}
														</TableCell>
														<TableCell>
															<Badge variant="outline">{referral.plan}</Badge>
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
			</Tabs>
		</div>
	);
};

export default AdminAffiliateDetailPage;
