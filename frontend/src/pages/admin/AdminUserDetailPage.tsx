// src/pages/admin/AdminUserDetailPage.tsx

import { ArrowLeft, Save } from "lucide-react";
import React, { useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate, useParams } from "react-router-dom";
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
import { useToast } from "@/components/ui/use-toast";
import {
	useAdminIssueBonus,
	useAdminUpdateUser,
	useAdminUserDetails,
	useAvailableBonuses,
} from "@/lib/api";
import type { AdminUserUpdatePayload, BonusInfo, TaskData } from "@/types/api";

const AdminUserDetailPage: React.FC = () => {
	const { id } = useParams<{ id: string }>();
	const navigate = useNavigate();
	const { toast } = useToast();
	const { t } = useTranslation(["admin", "common"]);
	const userId = parseInt(id || "0", 10);

	const { data: userDetails, isLoading } = useAdminUserDetails(userId);
	const updateUserMutation = useAdminUpdateUser();
	const issueBonusMutation = useAdminIssueBonus();
	const { data: availableBonuses } = useAvailableBonuses();

	const [editData, setEditData] = useState<AdminUserUpdatePayload>({});
	const [selectedBonus, setSelectedBonus] = useState("");
	const [bonusQuantity, setBonusQuantity] = useState(1);

	React.useEffect(() => {
		if (userDetails?.user) {
			setEditData({
				plan: userDetails.user.plan,
				isActive: userDetails.user.isActive,
				role: userDetails.user.role,
				affiliateCommissionRate: userDetails.user.affiliateCommissionRate ?? 0,
			});
		}
	}, [userDetails]);

	const handleSave = async () => {
		try {
			const payloadToSave = { ...editData };
			await updateUserMutation.mutateAsync({ userId, payload: payloadToSave });
			toast({
				title: t("userUpdateSuccessTitle"),
				description: t("userUpdateSuccessDescription"),
			});
		} catch (error) {
			const err = error as Error;
			toast({
				variant: "destructive",
				title: t("userUpdateFailedTitle"),
				description: err.message,
			});
		}
	};

	const handleIssueBonus = async () => {
		if (!selectedBonus) return;
		try {
			await issueBonusMutation.mutateAsync({
				userId,
				payload: { featureName: selectedBonus, quantity: bonusQuantity },
			});
			toast({
				title: t("bonusIssueSuccessTitle"),
				description: t("bonusIssueSuccessDescription"),
			});
			setSelectedBonus("");
			setBonusQuantity(1);
		} catch (error) {
			const err = error as Error;
			toast({
				variant: "destructive",
				title: t("bonusIssueFailedTitle"),
				description: err.message,
			});
		}
	};

	if (isLoading) {
		return (
			<div className="space-y-4">
				<Skeleton className="h-8 w-64" />
				<Skeleton className="h-96 w-full" />
			</div>
		);
	}

	if (!userDetails) {
		return <div>User not found</div>;
	}

	const { user, recentTasks, paperWallets, bonuses } = userDetails;

	return (
		<div className="space-y-6">
			<div className="flex items-center gap-4">
				<Button
					variant="ghost"
					size="icon"
					onClick={() => navigate("/admin/users")}
				>
					<ArrowLeft className="h-4 w-4" />
				</Button>
				<div>
					<h1 className="text-3xl font-bold">{user.username}</h1>
					<p className="text-muted-foreground">{user.email}</p>
				</div>
			</div>

			<div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
				{/* User Info & Paper Wallet */}
				<div className="lg:col-span-1 space-y-6">
					<Card>
						<CardHeader>
							<CardTitle>User Information</CardTitle>
						</CardHeader>
						<CardContent className="space-y-3">
							<div className="flex justify-between">
								<span className="text-sm text-muted-foreground">User ID:</span>
								<span className="text-sm font-medium">{user.id}</span>
							</div>
							<div className="flex justify-between">
								<span className="text-sm text-muted-foreground">Plan:</span>
								<Badge>{user.plan}</Badge>
							</div>
							<div className="flex justify-between">
								<span className="text-sm text-muted-foreground">Status:</span>
								<Badge variant={user.isActive ? "default" : "destructive"}>
									{user.isActive ? "Active" : "Inactive"}
								</Badge>
							</div>
							<div className="flex justify-between">
								<span className="text-sm text-muted-foreground">Role:</span>
								<Badge variant="outline">{user.role}</Badge>
							</div>
							<div className="flex justify-between">
								<span className="text-sm text-muted-foreground">Created:</span>
								<span className="text-sm">
									{new Date(user.createdAt).toLocaleDateString()}
								</span>
							</div>
						</CardContent>
					</Card>

					<Card>
						<CardHeader>
							<CardTitle>Paper Wallet</CardTitle>
						</CardHeader>
						<CardContent>
							{paperWallets && paperWallets.length > 0 ? (
								<div className="space-y-2">
									{paperWallets.map((wallet) => (
										<div
											key={wallet.asset}
											className="flex justify-between items-center py-2 border-b last:border-0"
										>
											<span className="text-sm font-medium">
												{wallet.asset}
											</span>
											<span className="text-sm">
												{wallet.balance.toFixed(2)}
											</span>
										</div>
									))}
								</div>
							) : (
								<p className="text-sm text-muted-foreground">
									No paper wallet data
								</p>
							)}
						</CardContent>
					</Card>
				</div>

				{/* Main Content Area */}
				<div className="lg:col-span-2 space-y-6">
					{/* User Settings */}
					<Card>
						<CardHeader>
							<CardTitle>User Settings</CardTitle>
							<CardDescription>
								Update user permissions and plan
							</CardDescription>
						</CardHeader>
						<CardContent>
							<div className="grid grid-cols-1 md:grid-cols-2 gap-4">
								<div className="space-y-2">
									<Label>Plan</Label>
									<Select
										value={editData.plan}
										onValueChange={(value) =>
											setEditData({ ...editData, plan: value })
										}
									>
										<SelectTrigger>
											<SelectValue />
										</SelectTrigger>
										<SelectContent>
											<SelectItem value="free">Free</SelectItem>
											<SelectItem value="standard">Standard</SelectItem>
											<SelectItem value="pro">Pro</SelectItem>
										</SelectContent>
									</Select>
								</div>

								<div className="space-y-2">
									<Label>Status</Label>
									<Select
										value={editData.isActive ? "active" : "inactive"}
										onValueChange={(value) =>
											setEditData({ ...editData, isActive: value === "active" })
										}
									>
										<SelectTrigger>
											<SelectValue />
										</SelectTrigger>
										<SelectContent>
											<SelectItem value="active">Active</SelectItem>
											<SelectItem value="inactive">Inactive</SelectItem>
										</SelectContent>
									</Select>
								</div>

								<div className="space-y-2">
									<Label>Role</Label>
									<Select
										value={editData.role}
										onValueChange={(value) =>
											setEditData({
												...editData,
												role: value as "admin" | "user" | "affiliate",
											})
										}
									>
										<SelectTrigger>
											<SelectValue />
										</SelectTrigger>
										<SelectContent>
											<SelectItem value="user">User</SelectItem>
											<SelectItem value="admin">Admin</SelectItem>
											<SelectItem value="affiliate">Affiliate</SelectItem>
										</SelectContent>
									</Select>
								</div>

								{editData.role === "affiliate" && (
									<div className="space-y-2">
										<Label>Commission Rate (%)</Label>
										<Input
											type="number"
											min="0"
											max="100"
											step="1"
											value={(editData.affiliateCommissionRate ?? 0) * 100}
											onChange={(e) =>
												setEditData({
													...editData,
													affiliateCommissionRate:
														parseFloat(e.target.value) / 100,
												})
											}
										/>
									</div>
								)}
							</div>

							<Button
								onClick={handleSave}
								disabled={updateUserMutation.isPending}
								className="mt-4"
							>
								<Save className="mr-2 h-4 w-4" />
								Save Changes
							</Button>
						</CardContent>
					</Card>

					{/* Issue Bonus */}
					<Card>
						<CardHeader>
							<CardTitle>Issue Bonus</CardTitle>
							<CardDescription>Grant bonuses to the user</CardDescription>
						</CardHeader>
						<CardContent>
							<div className="grid grid-cols-1 md:grid-cols-2 gap-4">
								<div className="space-y-2">
									<Label>Bonus Type</Label>
									<Select
										value={selectedBonus}
										onValueChange={setSelectedBonus}
									>
										<SelectTrigger>
											<SelectValue placeholder="Select bonus" />
										</SelectTrigger>
										<SelectContent>
											{availableBonuses?.map((bonus) => (
												<SelectItem
													key={bonus.featureName}
													value={bonus.featureName}
												>
													{bonus.description}
												</SelectItem>
											))}
										</SelectContent>
									</Select>
								</div>

								<div className="space-y-2">
									<Label>Quantity</Label>
									<Input
										type="number"
										min="1"
										value={bonusQuantity}
										onChange={(e) =>
											setBonusQuantity(parseInt(e.target.value, 10))
										}
									/>
								</div>
							</div>

							<Button
								onClick={handleIssueBonus}
								disabled={!selectedBonus || issueBonusMutation.isPending}
								className="mt-4"
							>
								Issue Bonus
							</Button>
						</CardContent>
					</Card>

					{/* Bonuses */}
					<Card>
						<CardHeader>
							<CardTitle>Active Bonuses</CardTitle>
						</CardHeader>
						<CardContent>
							{bonuses && bonuses.length > 0 ? (
								<Table>
									<TableHeader>
										<TableRow>
											<TableHead>Feature</TableHead>
											<TableHead>Quantity</TableHead>
											<TableHead>Status</TableHead>
										</TableRow>
									</TableHeader>
									<TableBody>
										{bonuses.map((bonus: BonusInfo) => (
											<TableRow key={bonus.featureName}>
												<TableCell>{bonus.featureName}</TableCell>
												<TableCell>{bonus.quantity}</TableCell>
												<TableCell>
													<Badge
														variant={
															bonus.status === "active"
																? "default"
																: "secondary"
														}
													>
														{bonus.status}
													</Badge>
												</TableCell>
											</TableRow>
										))}
									</TableBody>
								</Table>
							) : (
								<p className="text-sm text-muted-foreground text-center py-4">
									No bonuses issued
								</p>
							)}
						</CardContent>
					</Card>

					{/* Recent Tasks */}
					<Card>
						<CardHeader>
							<CardTitle>Recent Tasks</CardTitle>
							<CardDescription>Last 10 tasks submitted by user</CardDescription>
						</CardHeader>
						<CardContent>
							{recentTasks && recentTasks.length > 0 ? (
								<Table>
									<TableHeader>
										<TableRow>
											<TableHead>Type</TableHead>
											<TableHead>Status</TableHead>
											<TableHead>Submitted</TableHead>
										</TableRow>
									</TableHeader>
									<TableBody>
										{recentTasks.map(
											(
												task: TaskData & { id?: string; task_type?: string },
											) => (
												<TableRow key={task.id || task.task_id}>
													<TableCell className="font-medium">
														{task.task_type || "Unknown"}
													</TableCell>
													<TableCell>
														<Badge
															variant={
																task.status === "completed"
																	? "default"
																	: task.status === "failed"
																		? "destructive"
																		: "secondary"
															}
														>
															{task.status}
														</Badge>
													</TableCell>
													<TableCell>
														{new Date(task.submitted_at).toLocaleString()}
													</TableCell>
												</TableRow>
											),
										)}
									</TableBody>
								</Table>
							) : (
								<p className="text-sm text-muted-foreground text-center py-4">
									No tasks found
								</p>
							)}
						</CardContent>
					</Card>
				</div>
			</div>
		</div>
	);
};

export default AdminUserDetailPage;
