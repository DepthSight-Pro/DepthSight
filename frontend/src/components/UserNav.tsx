// src/components/UserNav.tsx

import {
	Crown,
	LifeBuoy,
	Link as LinkIcon,
	LogOut,
	ShieldCheck,
	User,
} from "lucide-react";
import React from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Button } from "@/components/ui/button";
import {
	DropdownMenu,
	DropdownMenuContent,
	DropdownMenuGroup,
	DropdownMenuItem,
	DropdownMenuLabel,
	DropdownMenuSeparator,
	DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Skeleton } from "@/components/ui/skeleton";
import { useAuth } from "@/context/AuthContext";
import { useAccountStatus } from "@/lib/api";

export function UserNav() {
	// --- Adding 'account' namespace for quota translation ---
	const { t } = useTranslation(["common", "navigation", "account"]);
	const { user, logout } = useAuth();
	const { data: accountStatus, isLoading } = useAccountStatus();

	// Calculate the number of remaining plan days
	const daysLeft = React.useMemo(() => {
		if (!accountStatus?.planExpiresAt) return null;
		const expiresAt = new Date(accountStatus.planExpiresAt);
		const now = new Date();
		const diffTime = expiresAt.getTime() - now.getTime();
		return Math.ceil(diffTime / (1000 * 60 * 60 * 24));
	}, [accountStatus]);

	if (!user) {
		return null;
	}

	// Find the most relevant quota to display (e.g., backtests)
	const relevantQuota = accountStatus?.quotas.find((q) =>
		q.name.toLowerCase().includes("backtest"),
	);

	return (
		<DropdownMenu>
			<DropdownMenuTrigger asChild>
				<Button variant="ghost" className="relative h-8 w-8 rounded-full">
					<Avatar className="h-8 w-8">
						<AvatarFallback>
							{user.username.charAt(0).toUpperCase()}
						</AvatarFallback>
					</Avatar>
				</Button>
			</DropdownMenuTrigger>
			<DropdownMenuContent className="w-64" align="end" forceMount>
				{/* --- BLOCK 1: USER INFORMATION --- */}
				<DropdownMenuLabel className="font-normal">
					<div className="flex flex-col space-y-1">
						<p className="text-sm font-medium leading-none">{user.username}</p>
						<p className="text-xs leading-none text-muted-foreground">
							{user.email}
						</p>
					</div>
				</DropdownMenuLabel>
				<DropdownMenuSeparator />

				{/* --- BLOCK 2: ACCOUNT STATUS --- */}
				<DropdownMenuGroup>
					<div className="px-2 py-1.5 text-sm">
						<div className="flex justify-between items-center">
							<span className="font-medium text-muted-foreground">
								{t("common:plan")}:
							</span>
							{isLoading ? (
								<Skeleton className="h-5 w-1/3" />
							) : (
								<div className="flex items-center gap-2">
									<span className="font-bold capitalize">
										{t(`account:plans.${accountStatus?.planName}`, {
											defaultValue: accountStatus?.planName,
										})}
									</span>
									{daysLeft !== null && daysLeft >= 0 && (
										<span
											className={
												"text-[10px] px-1.5 py-0.5 rounded-sm font-semibold " +
												(daysLeft <= 3
													? "bg-red-500/10 text-red-500"
													: "bg-emerald-500/10 text-emerald-500")
											}
										>
											{daysLeft} {t("common:days", "days")}
										</span>
									)}
								</div>
							)}
						</div>
						{relevantQuota && (
							<div className="flex justify-between items-center mt-1">
								<span className="text-muted-foreground text-xs">
									{t(`account:quotas.${relevantQuota.name}`, {
										defaultValue: relevantQuota.name,
									})}
									:
								</span>
								{isLoading ? (
									<Skeleton className="h-4 w-1/4" />
								) : (
									<span className="text-xs">
										{relevantQuota.limit === -1
											? "∞"
											: `${relevantQuota.used}/${relevantQuota.limit}`}
									</span>
								)}
							</div>
						)}

						{!isLoading && user.plan !== "pro" && (
							<div className="mt-3 mb-1">
								<DropdownMenuItem asChild>
									<Link
										to="/account"
										className="w-full flex items-center justify-center h-8 rounded-md bg-gradient-to-r from-amber-500 to-orange-600 hover:from-amber-600 focus:from-amber-600 hover:to-orange-700 focus:to-orange-700 text-white shadow-sm font-medium cursor-pointer"
									>
										<Crown className="mr-2 h-3.5 w-3.5" />
										{t("common:upgradeToPro", "Upgrade to PRO")}
									</Link>
								</DropdownMenuItem>
							</div>
						)}
					</div>
				</DropdownMenuGroup>
				<DropdownMenuSeparator />

				{/* --- BLOCK 3: NAVIGATION --- */}
				<DropdownMenuGroup>
					{/* CONDITIONAL LINK TO ADMIN PANEL */}
					{user.role === "admin" && (
						<DropdownMenuItem asChild>
							<Link to="/admin">
								<ShieldCheck className="mr-2 h-4 w-4" />
								<span>{t("navigation:adminPanel")}</span>
							</Link>
						</DropdownMenuItem>
					)}

					{/* LINK TO AFFILIATE PANEL */}
					<DropdownMenuItem asChild>
						<Link to="/affiliate-dashboard">
							<LinkIcon className="mr-2 h-4 w-4" />
							<span>{t("navigation:affiliateDashboard")}</span>
						</Link>
					</DropdownMenuItem>

					<DropdownMenuItem asChild>
						<Link to="/account">
							<User className="mr-2 h-4 w-4" />
							<span>{t("navigation:account")}</span>
						</Link>
					</DropdownMenuItem>

					{/* You can add other links here, for example, to documentation */}
					<DropdownMenuItem asChild>
						<Link to="/support">
							<LifeBuoy className="mr-2 h-4 w-4" />
							<span>{t("navigation:support")}</span>
						</Link>
					</DropdownMenuItem>
				</DropdownMenuGroup>
				<DropdownMenuSeparator />

				{/* --- BLOCK 4: LOGOUT --- */}
				<DropdownMenuItem onSelect={() => logout()}>
					<LogOut className="mr-2 h-4 w-4" />
					<span>{t("common:logout")}</span>
				</DropdownMenuItem>
			</DropdownMenuContent>
		</DropdownMenu>
	);
}
