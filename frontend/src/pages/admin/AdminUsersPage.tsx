// src/pages/admin/AdminUsersPage.tsx

import { LogIn } from "lucide-react";
import type React from "react";
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Pagination } from "@/components/shared/Pagination";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
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
import { useAuth } from "@/context/AuthContext";
import { useAdminGetUsers, useImpersonateUser } from "@/lib/api";

const AdminUsersPage: React.FC = () => {
	const navigate = useNavigate();
	const [page, setPage] = useState(1);
	const [search, setSearch] = useState("");
	const [plan, setPlan] = useState("all");

	const { data, isLoading } = useAdminGetUsers(
		page,
		10,
		search,
		plan === "all" ? undefined : plan,
	);
	const { impersonate } = useAuth();
	const { mutate: impersonateMutation, isPending } = useImpersonateUser();

	const handleImpersonate = (userId: number) => {
		impersonateMutation(userId, {
			onSuccess: (tokenData) => {
				impersonate(tokenData.access_token);
			},
		});
	};

	return (
		<div className="space-y-6">
			<div>
				<h1 className="text-3xl font-bold mb-2">User Management</h1>
				<p className="text-muted-foreground">
					Manage users, plans, and permissions
				</p>
			</div>

			<div className="flex gap-4">
				<Input
					placeholder="Search by username or email..."
					value={search}
					onChange={(e) => setSearch(e.target.value)}
				/>
				<Select value={plan} onValueChange={setPlan}>
					<SelectTrigger className="w-[180px]">
						<SelectValue placeholder="Filter by plan" />
					</SelectTrigger>
					<SelectContent>
						<SelectItem value="all">All Plans</SelectItem>
						<SelectItem value="free">Free</SelectItem>
						<SelectItem value="standard">Standard</SelectItem>
						<SelectItem value="pro">Pro</SelectItem>
					</SelectContent>
				</Select>
			</div>

			<Table>
				<TableHeader>
					<TableRow>
						<TableHead>ID</TableHead>
						<TableHead>Username</TableHead>
						<TableHead>Email</TableHead>
						<TableHead>Plan</TableHead>
						<TableHead>Status</TableHead>
						<TableHead>Actions</TableHead>
					</TableRow>
				</TableHeader>
				<TableBody>
					{isLoading
						? [...Array(5)].map((_, i) => (
								<TableRow key={i}>
									<TableCell colSpan={6}>
										<Skeleton className="h-8 w-full" />
									</TableCell>
								</TableRow>
							))
						: data?.users.map((user) => (
								<TableRow key={user.id}>
									<TableCell>{user.id}</TableCell>
									<TableCell>{user.username}</TableCell>
									<TableCell>{user.email}</TableCell>
									<TableCell>
										<Badge variant="outline">{user.plan}</Badge>
									</TableCell>
									<TableCell>
										<Badge variant={user.isActive ? "default" : "destructive"}>
											{user.isActive ? "Active" : "Inactive"}
										</Badge>
									</TableCell>
									<TableCell className="flex gap-2">
										<Button
											variant="outline"
											size="sm"
											onClick={() => navigate(`/admin/users/${user.id}`)}
										>
											View
										</Button>
										<Button
											variant="ghost"
											size="sm"
											onClick={() => handleImpersonate(user.id)}
											disabled={isPending}
										>
											<LogIn className="h-4 w-4 mr-2" />
											Login As
										</Button>
									</TableCell>
								</TableRow>
							))}
				</TableBody>
			</Table>

			{data && data.total > 10 && (
				<Pagination
					currentPage={page}
					totalPages={Math.ceil(data.total / 10)}
					onPageChange={setPage}
				/>
			)}
		</div>
	);
};

export default AdminUsersPage;
