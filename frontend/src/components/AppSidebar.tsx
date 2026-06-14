// src/components/AppSidebar.tsx

import {
	BarChart3,
	BrainCircuit,
	Briefcase,
	Cog,
	Crown,
	Dna,
	FlaskConical,
	Globe,
	Home,
	Loader2,
	Microscope,
	PencilRuler,
	Settings as SettingsIcon,
	Terminal,
	TestTube2,
	Trophy,
	Zap,
} from "lucide-react";
import React, { useMemo } from "react";
import { useTranslation } from "react-i18next";
import { Link, useLocation } from "react-router-dom";
import { toast } from "sonner";
import { LanguageSwitcher } from "@/components/LanguageSwitcher";
import { ThemeSwitcher } from "@/components/ThemeSwitcher";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Logo } from "@/components/ui/logo";
import {
	Popover,
	PopoverContent,
	PopoverTrigger,
} from "@/components/ui/popover";
import {
	Sidebar,
	SidebarContent,
	SidebarFooter,
	SidebarHeader,
} from "@/components/ui/sidebar";
import {
	Tooltip,
	TooltipContent,
	TooltipProvider,
	TooltipTrigger,
} from "@/components/ui/tooltip";
import { useAuth } from "@/context/AuthContext";
import { useAccountStatus, useSystemStatus } from "@/lib/api";
import { apiClient } from "@/lib/apiClient";
import { cn } from "@/lib/utils";

// Define navigation item structure
// Define navigation item structure
interface NavItemConfig {
	key: string; // For translation key
	url: string;
	icon: React.ElementType;
	adminOnly?: boolean;
}

const navigationItemConfigs: NavItemConfig[] = [
	{ key: "dashboard", url: "/", icon: Home },
	{ key: "communityHub", url: "/hub", icon: Globe },
	{ key: "positions", url: "/positions", icon: Briefcase },
	{ key: "strategies", url: "/strategies", icon: Cog },
	{ key: "strategyEditor", url: "/editor", icon: PencilRuler },
	{ key: "analytics", url: "/analytics", icon: BarChart3 },
	{ key: "leaderboard", url: "/leaderboard", icon: Trophy },
	{ key: "research", url: "/research", icon: FlaskConical },
	{ key: "laboratory", url: "/lab", icon: Dna },
	{ key: "modelLab", url: "/model-lab", icon: BrainCircuit },
	{ key: "discoveryLab", url: "/discovery", icon: Microscope },
	{
		key: "foundationVisualizer",
		url: "/diagnostics/foundation-visualizer",
		icon: TestTube2,
	},
	{ key: "hftDashboard", url: "/hft", icon: Zap, adminOnly: true },
	{ key: "eventLog", url: "/logs", icon: Terminal },
];

const bottomItemConfigs: NavItemConfig[] = [
	{ key: "settings", url: "/settings", icon: SettingsIcon },
];

interface NavItemProps {
	config: NavItemConfig;
	title: string; // Translated title
	pathname: string;
}

const NavItem: React.FC<NavItemProps> = ({ config, title, pathname }) => {
	const isActive =
		config.url === "/" ? pathname === "/" : pathname.startsWith(config.url);

	return (
		<Tooltip>
			<TooltipTrigger asChild>
				<Link to={config.url}>
					<Button
						variant="ghost"
						size="icon"
						className={cn(
							"rounded-lg",
							isActive && "bg-accent text-accent-foreground",
						)}
					>
						<config.icon className="h-5 w-5" />
					</Button>
				</Link>
			</TooltipTrigger>
			<TooltipContent side="right">{title}</TooltipContent>
		</Tooltip>
	);
};

export function AppSidebar() {
	const { pathname } = useLocation();
	const { t } = useTranslation(["navigation", "common"]); // Load namespaces
	const { user } = useAuth();
	const { data: accountStatus } = useAccountStatus();
	const { data: systemStatus } = useSystemStatus();

	const localVersion = systemStatus?.version || "1.0.1";
	const [masterVersion, setMasterVersion] = React.useState<string | null>(null);

	React.useEffect(() => {
		const hubApiUrl =
			import.meta.env.VITE_HUB_API_URL ||
			"https://app.depthsight.pro/api/v1/hub";
		fetch(`${hubApiUrl}/nodes`)
			.then((res) => {
				if (!res.ok) throw new Error();
				return res.json();
			})
			.then((data) => {
				if (Array.isArray(data)) {
					const masterNode = data.find((n) => n.is_master);
					if (masterNode?.version) {
						setMasterVersion(masterNode.version);
					}
				}
			})
			.catch(() => {});
	}, []);

	const isOutdated = masterVersion !== null && localVersion !== masterVersion;

	const [isUpdating, setIsUpdating] = React.useState(false);

	const handleTriggerUpdate = async () => {
		setIsUpdating(true);
		const updatePromise = apiClient("/admin/system/update", { method: "POST" });
		toast.promise(updatePromise, {
			loading: t(
				"common:systemUpdate.startUpdateToast",
				"Starting platform update...",
			),
			success: () => {
				return t(
					"common:systemUpdate.updateTriggeredToast",
					"Update triggered. The system will restart within a minute.",
				);
			},
			error: (err: unknown) => {
				setIsUpdating(false);
				const errMsg = err instanceof Error ? err.message : String(err);
				return t("common:systemUpdate.updateFailedToast", {
					defaultValue: `Failed to trigger update: ${errMsg}`,
					error: errMsg,
				});
			},
		});
	};

	// Calculate the number of remaining plan days
	const daysLeft = useMemo(() => {
		if (!accountStatus?.planExpiresAt) return null;
		const expiresAt = new Date(accountStatus.planExpiresAt);
		const now = new Date();
		const diffTime = expiresAt.getTime() - now.getTime();
		return Math.ceil(diffTime / (1000 * 60 * 60 * 24));
	}, [accountStatus]);

	// Map configs to items with translated titles and filter by role
	const navigationItems = navigationItemConfigs
		.filter((config) => !config.adminOnly || (user && user.role === "admin"))
		.map((config) => ({
			...config,
			title: t(config.key),
		}));

	const bottomItems = bottomItemConfigs.map((config) => ({
		...config,
		title: t(config.key),
	}));

	return (
		<Sidebar variant="sidebar" collapsible="icon">
			<TooltipProvider delayDuration={0}>
				<div className="flex h-full flex-col items-center w-full">
					<SidebarHeader className="h-20 flex items-center justify-center border-b w-full">
						<Link to="/" className="relative top-[-6px] left-[-9px]">
							<Logo iconOnly className="h-12 w-12" />
						</Link>
					</SidebarHeader>

					<SidebarContent className="flex-1 p-2 w-full">
						<nav className="flex flex-col items-center gap-2">
							{navigationItems.map((item) => (
								<NavItem
									key={item.key}
									config={item}
									title={item.title}
									pathname={pathname}
								/>
							))}
						</nav>
					</SidebarContent>

					<SidebarFooter className="p-2 w-full mt-auto">
						<nav className="flex flex-col items-center gap-2">
							{/* Version Display */}
							{user &&
								user.role === "admin" &&
								(isOutdated ? (
									<Popover>
										<PopoverTrigger asChild>
											<div className="flex justify-center w-full cursor-pointer">
												<Badge
													variant="outline"
													className={cn(
														"text-[9px] font-mono w-12 px-1 py-0.5 flex justify-center tracking-tight transition-all",
														"bg-amber-500/10 text-amber-500 border-amber-500/30 animate-pulse hover:bg-amber-500/20",
													)}
												>
													v{localVersion}
												</Badge>
											</div>
										</PopoverTrigger>
										<PopoverContent
											side="right"
											className="flex flex-col gap-2 text-xs p-3 w-56"
										>
											<div className="flex flex-col gap-0.5">
												<span className="font-semibold text-foreground">
													{t("common:version", "Version")}: {localVersion}
												</span>
												{masterVersion && (
													<span className="text-amber-600 dark:text-amber-400 font-medium animate-pulse">
														{t("common:systemUpdate.updateAvailable", {
															defaultValue: `Update available: v${masterVersion}`,
															version: masterVersion,
														})}
													</span>
												)}
											</div>
											<Button
												size="sm"
												className="w-full mt-1 font-medium bg-amber-500 hover:bg-amber-600 text-white dark:bg-amber-600 dark:hover:bg-amber-700 flex items-center justify-center gap-1.5"
												onClick={handleTriggerUpdate}
												disabled={isUpdating}
											>
												{isUpdating ? (
													<>
														<Loader2 className="h-3 w-3 animate-spin" />
														<span>
															{t(
																"common:systemUpdate.updatingStatus",
																"Updating...",
															)}
														</span>
													</>
												) : (
													<span>
														{t(
															"common:systemUpdate.updatePlatform",
															"Update Platform",
														)}
													</span>
												)}
											</Button>
										</PopoverContent>
									</Popover>
								) : (
									<Tooltip>
										<TooltipTrigger asChild>
											<div className="flex justify-center w-full">
												<Badge
													variant="outline"
													className={cn(
														"text-[9px] font-mono w-12 px-1 py-0.5 flex justify-center tracking-tight transition-all",
														"bg-emerald-500/10 text-emerald-500 border-emerald-500/20",
													)}
												>
													v{localVersion}
												</Badge>
											</div>
										</TooltipTrigger>
										<TooltipContent
											side="right"
											className="flex flex-col gap-0.5 text-xs"
										>
											<span>
												{t("common:version", "Version")}: {localVersion}
											</span>
											<span className="text-emerald-550">
												{t("common:systemUpdate.latestVersion", "Up to date")}
											</span>
										</TooltipContent>
									</Tooltip>
								))}

							{/* Display the user's plan */}
							{user && (
								<Tooltip>
									<TooltipTrigger asChild>
										<Link to="/account" className="w-full flex justify-center">
											<Badge
												variant="outline"
												className={cn(
													"capitalize transition-colors w-12 px-1 flex justify-center overflow-hidden",
													user.plan !== "pro" &&
														"hover:bg-amber-500/10 hover:text-amber-500 hover:border-amber-500/50 cursor-pointer",
												)}
											>
												{user.plan !== "pro" && (
													<Crown className="mr-0.5 h-3 w-3 shrink-0 text-amber-500" />
												)}
												<span className="truncate text-[10px]">
													{user.plan.substring(0, 3)}
												</span>
											</Badge>
										</Link>
									</TooltipTrigger>
									<TooltipContent side="right" className="flex flex-col gap-1">
										<span>
											{user.plan !== "pro"
												? t("upgradePlan", "Upgrade plan")
												: t("currentPlan", { plan: user.plan })}
										</span>
										{daysLeft !== null && daysLeft >= 0 && (
											<span className="text-xs text-muted-foreground border-t border-border/50 pt-1 mt-0.5">
												{t("common:daysLeft", "Days left:")}{" "}
												<span
													className={
														daysLeft <= 3
															? "text-red-400 font-bold"
															: "font-medium text-foreground"
													}
												>
													{daysLeft}
												</span>
											</span>
										)}
									</TooltipContent>
								</Tooltip>
							)}
							<ThemeSwitcher />
							<LanguageSwitcher />
							{bottomItems.map((item) => (
								<NavItem
									key={item.key}
									config={item}
									title={item.title}
									pathname={pathname}
								/>
							))}
						</nav>
					</SidebarFooter>
				</div>
			</TooltipProvider>
		</Sidebar>
	);
}
