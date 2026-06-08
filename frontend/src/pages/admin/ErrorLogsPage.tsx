// src/pages/admin/ErrorLogsPage.tsx

import { AlertCircle, Clock, RefreshCw, Terminal, User } from "lucide-react";
import React, { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
	Card,
	CardContent,
	CardDescription,
	CardHeader,
	CardTitle,
} from "@/components/ui/card";
import {
	Select,
	SelectContent,
	SelectItem,
	SelectTrigger,
	SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { useAdminErrorLogs, useAdminGetUsers } from "@/lib/api";
import type { LogEntry } from "@/types/api";

const getLevelBadge = (level: LogEntry["level"]) => {
	const styles: Record<string, string> = {
		ERROR: "bg-red-500/20 text-red-600 border-red-500/30",
		WARNING: "bg-yellow-500/20 text-yellow-600 border-yellow-500/30",
		INFO: "",
		SUCCESS: "",
		DEBUG: "",
	};
	return (
		<Badge
			variant="outline"
			className={`whitespace-nowrap ${styles[level] || ""}`}
		>
			{level}
		</Badge>
	);
};

const ErrorLogsPage: React.FC = () => {
	const navigate = useNavigate();
	const [level, setLevel] = useState<"ERROR" | "WARNING">("ERROR");
	const [limit, setLimit] = useState(100);

	const {
		data: errorLogs,
		isLoading,
		refetch,
	} = useAdminErrorLogs(limit, level);
	const { data: usersData } = useAdminGetUsers(1, 1000, undefined, undefined);

	// Create a map of user IDs to usernames
	const userMap = React.useMemo(() => {
		const map = new Map<number, string>();
		if (usersData?.users) {
			usersData.users.forEach((user) => {
				map.set(user.id, user.username);
			});
		}
		return map;
	}, [usersData]);

	const getUsernameById = React.useCallback(
		(userId: number) => {
			return userMap.get(userId) || `User #${userId}`;
		},
		[userMap],
	);

	const groupedByUser = React.useMemo(() => {
		const groups: Record<number, LogEntry[]> = {};
		if (errorLogs) {
			errorLogs.forEach((log) => {
				const userId = (log as LogEntry & { user_id?: number }).user_id || 0;
				if (!groups[userId]) {
					groups[userId] = [];
				}
				groups[userId].push(log);
			});
		}
		return groups;
	}, [errorLogs]);

	const errorsByUser = React.useMemo(() => {
		return Object.entries(groupedByUser)
			.map(([userId, logs]) => ({
				userId: parseInt(userId, 10),
				username: getUsernameById(parseInt(userId, 10)),
				count: logs.length,
				latestError: logs[0],
			}))
			.sort((a, b) => b.count - a.count);
	}, [groupedByUser, getUsernameById]);

	return (
		<div className="space-y-6">
			<div>
				<h1 className="text-3xl font-bold mb-2">Error Logs</h1>
				<p className="text-muted-foreground">
					Monitor errors and warnings across all users
				</p>
			</div>

			{/* Controls */}
			<Card>
				<CardContent className="pt-6">
					<div className="flex flex-wrap items-center gap-4">
						<div className="flex items-center gap-2">
							<span className="text-sm font-medium">Level:</span>
							<Select
								value={level}
								onValueChange={(val) => setLevel(val as "ERROR" | "WARNING")}
							>
								<SelectTrigger className="w-[140px]">
									<SelectValue />
								</SelectTrigger>
								<SelectContent>
									<SelectItem value="ERROR">Errors Only</SelectItem>
									<SelectItem value="WARNING">Warnings Only</SelectItem>
								</SelectContent>
							</Select>
						</div>

						<div className="flex items-center gap-2">
							<span className="text-sm font-medium">Limit:</span>
							<Select
								value={limit.toString()}
								onValueChange={(val) => setLimit(parseInt(val, 10))}
							>
								<SelectTrigger className="w-[100px]">
									<SelectValue />
								</SelectTrigger>
								<SelectContent>
									<SelectItem value="50">50</SelectItem>
									<SelectItem value="100">100</SelectItem>
									<SelectItem value="200">200</SelectItem>
									<SelectItem value="500">500</SelectItem>
								</SelectContent>
							</Select>
						</div>

						<Button
							variant="outline"
							size="sm"
							onClick={() => refetch()}
							disabled={isLoading}
						>
							<RefreshCw
								className={`h-4 w-4 mr-2 ${isLoading ? "animate-spin" : ""}`}
							/>
							Refresh
						</Button>
					</div>
				</CardContent>
			</Card>

			{/* Stats */}
			<div className="grid grid-cols-1 md:grid-cols-3 gap-4">
				<Card>
					<CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
						<CardTitle className="text-sm font-medium">
							Total {level === "ERROR" ? "Errors" : "Warnings"}
						</CardTitle>
						<AlertCircle className="h-4 w-4 text-red-600" />
					</CardHeader>
					<CardContent>
						{isLoading ? (
							<Skeleton className="h-8 w-20" />
						) : (
							<div className="text-2xl font-bold">{errorLogs?.length || 0}</div>
						)}
					</CardContent>
				</Card>

				<Card>
					<CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
						<CardTitle className="text-sm font-medium">
							Affected Users
						</CardTitle>
						<User className="h-4 w-4 text-orange-600" />
					</CardHeader>
					<CardContent>
						{isLoading ? (
							<Skeleton className="h-8 w-20" />
						) : (
							<div className="text-2xl font-bold">{errorsByUser.length}</div>
						)}
					</CardContent>
				</Card>

				<Card>
					<CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
						<CardTitle className="text-sm font-medium">Avg per User</CardTitle>
						<Terminal className="h-4 w-4 text-blue-600" />
					</CardHeader>
					<CardContent>
						{isLoading ? (
							<Skeleton className="h-8 w-20" />
						) : (
							<div className="text-2xl font-bold">
								{errorsByUser.length > 0
									? ((errorLogs?.length || 0) / errorsByUser.length).toFixed(1)
									: "0"}
							</div>
						)}
					</CardContent>
				</Card>
			</div>

			{/* Errors by User */}
			<Card>
				<CardHeader>
					<CardTitle>Errors by User</CardTitle>
					<CardDescription>Users with the most errors</CardDescription>
				</CardHeader>
				<CardContent>
					{isLoading ? (
						<div className="space-y-2">
							{[...Array(5)].map((_, i) => (
								<Skeleton key={i} className="h-16 w-full" />
							))}
						</div>
					) : errorsByUser.length === 0 ? (
						<div className="text-center py-8 text-muted-foreground">
							No {level === "ERROR" ? "errors" : "warnings"} found
						</div>
					) : (
						<div className="space-y-3">
							{errorsByUser.map(({ userId, username, count, latestError }) => (
								<div
									key={userId}
									className="p-4 border rounded-lg hover:bg-muted/50 transition-colors cursor-pointer"
									onClick={() => navigate(`/admin/users/${userId}`)}
								>
									<div className="flex items-start justify-between">
										<div className="flex-1">
											<div className="flex items-center gap-2 mb-2">
												<span className="font-medium">{username}</span>
												<Badge variant="secondary">{count} errors</Badge>
												{getLevelBadge(latestError.level)}
											</div>
											<div className="flex items-center gap-2 text-xs text-muted-foreground mb-2">
												<Clock className="h-3 w-3" />
												{new Date(latestError.timestamp).toLocaleString()}
											</div>
											<div className="text-sm text-muted-foreground">
												<span className="font-mono text-xs bg-muted px-2 py-1 rounded">
													{latestError.component}
												</span>
												<span className="ml-2">{latestError.message}</span>
											</div>
										</div>
										<Button variant="ghost" size="sm">
											View User
										</Button>
									</div>
								</div>
							))}
						</div>
					)}
				</CardContent>
			</Card>

			{/* All Logs */}
			<Card>
				<CardHeader>
					<CardTitle>All Error Logs</CardTitle>
					<CardDescription>Complete list of recent errors</CardDescription>
				</CardHeader>
				<CardContent>
					{isLoading ? (
						<div className="space-y-1">
							{[...Array(10)].map((_, i) => (
								<Skeleton key={i} className="h-12 w-full" />
							))}
						</div>
					) : errorLogs && errorLogs.length > 0 ? (
						<div className="space-y-1 max-h-[600px] overflow-y-auto">
							{errorLogs.map((log, index) => {
								const userId =
									(log as LogEntry & { user_id?: number }).user_id || 0;
								return (
									<div
										key={`${log.id}-${index}`}
										className="flex items-start gap-3 p-2 rounded-md hover:bg-accent text-xs font-mono"
									>
										<span className="text-muted-foreground whitespace-nowrap">
											{new Date(log.timestamp).toLocaleTimeString()}
										</span>
										<span>{getLevelBadge(log.level)}</span>
										<span
											className="text-blue-600 font-medium cursor-pointer hover:underline"
											onClick={() => navigate(`/admin/users/${userId}`)}
										>
											{getUsernameById(userId)}
										</span>
										<span className="text-primary font-medium w-36 truncate">
											[{log.component}]
										</span>
										<span className="text-foreground flex-1 whitespace-pre-wrap break-words">
											{log.message}
										</span>
									</div>
								);
							})}
						</div>
					) : (
						<div className="text-center py-8 text-muted-foreground">
							No {level === "ERROR" ? "errors" : "warnings"} found
						</div>
					)}
				</CardContent>
			</Card>
		</div>
	);
};

export default ErrorLogsPage;
