// src/pages/admin/AdminAffiliatesPage.tsx

import type React from "react";
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Pagination } from "@/components/shared/Pagination";
import { Button } from "@/components/ui/button";
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
import { useAdminAffiliates } from "@/lib/api";
import type { AdminUser } from "@/types/api";

const AdminAffiliatesPage: React.FC = () => {
	const [page, setPage] = useState(1);
	const navigate = useNavigate();

	// Hook returns paginated data
	const { data: affiliatesData, isLoading: isLoadingAffiliates } =
		useAdminAffiliates(page, 10);

	const formatCurrency = (amount: number) =>
		new Intl.NumberFormat("en-US", {
			style: "currency",
			currency: "USD",
		}).format(amount);

	return (
		<div className="space-y-6">
			<div>
				<h1 className="text-3xl font-bold mb-2">Affiliate Management</h1>
				<p className="text-muted-foreground">
					Track affiliate performance and commissions
				</p>
			</div>

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
								: // Use affiliatesData.users.map
									affiliatesData?.users.map((affiliate: AdminUser) => (
										<TableRow key={affiliate.id}>
											<TableCell>{affiliate.id}</TableCell>
											<TableCell>{affiliate.username}</TableCell>
											{/* Use correct fields */}
											<TableCell>
												{(affiliate.affiliateCommissionRate || 0) * 100}%
											</TableCell>
											<TableCell>
												{affiliate.stats?.referralCount ?? 0}
											</TableCell>
											<TableCell>
												{affiliate.stats?.payingReferralCount ?? 0}
											</TableCell>
											<TableCell>
												{formatCurrency(affiliate.stats?.totalEarnings ?? 0)}
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

			{/* Pass correct props to pagination */}
			{affiliatesData && affiliatesData.total > 10 && (
				<Pagination
					currentPage={page}
					totalPages={Math.ceil(affiliatesData.total / 10)}
					onPageChange={setPage}
				/>
			)}
		</div>
	);
};

export default AdminAffiliatesPage;
