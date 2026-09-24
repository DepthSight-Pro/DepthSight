import {
	BarChart3,
	BrainCircuit,
	Briefcase,
	ChevronsLeft,
	ChevronsRight,
	CircleDot,
	Cog,
	Cpu,
	Crown,
	Dna,
	FlaskConical,
	Globe,
	Home,
	Loader2,
	Microscope,
	PencilRuler,
	Pickaxe,
	Settings as SettingsIcon,
	Terminal,
	TestTube2,
	Trophy,
} from "lucide-react";
import React, { useMemo } from "react";
import { useTranslation } from "react-i18next";
import { Link, useLocation } from "react-router-dom";
import { toast } from "sonner";
import { LanguageSwitcher } from "@/components/LanguageSwitcher";
import { ThemeSwitcher } from "@/components/ThemeSwitcher";
import { Badge } from "@/components/ui/badge";
import { Logo } from "@/components/ui/logo";
import {
	Popover,
	PopoverContent,
	PopoverTrigger,
} from "@/components/ui/popover";
import { Radial } from "@/components/ui/quant-ui";
import {
	Sidebar,
	SidebarContent,
	SidebarFooter,
	SidebarHeader,
	useSidebar,
} from "@/components/ui/sidebar";
import {
	Tooltip,
	TooltipContent,
	TooltipProvider,
	TooltipTrigger,
} from "@/components/ui/tooltip";
import { useAuth } from "@/context/AuthContext";
import { usePortfolioMode } from "@/context/PortfolioModeContext";
import {
	useAccountStatus,
	useGetMiningStatus,
	useGetPromoStatus,
	usePositions,
	useStrategies,
	useSystemResources,
	useSystemStatus,
} from "@/lib/api";
import { apiClient } from "@/lib/apiClient";
import { cn } from "@/lib/utils";
import type { StrategyData } from "@/types/api";

interface NavItemConfig {
	key: string;
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
	{
		key: "modelLab",
		url: "/model-lab",
		icon: BrainCircuit,
		adminOnly: true,
	},
	{ key: "discoveryLab", url: "/discovery", icon: Microscope },
	{
		key: "foundationVisualizer",
		url: "/diagnostics/foundation-visualizer",
		icon: TestTube2,
	},
	{ key: "mining", url: "/mining", icon: Pickaxe },
	{ key: "eventLog", url: "/logs", icon: Terminal },
];

export function AppSidebar() {
	const { pathname } = useLocation();
	const { t } = useTranslation(["navigation", "common", "account"]);
	const { user } = useAuth();
	const { state, toggleSidebar } = useSidebar();
	const isExpanded = state === "expanded";

	const { data: accountStatus } = useAccountStatus();
	const { data: systemStatus } = useSystemStatus();
	const { data: miningStatus } = useGetMiningStatus();
	const { data: resources } = useSystemResources();
	const { mode } = usePortfolioMode();
	const { data: positions } = usePositions({ mode });
	const { data: strategies } = useStrategies({ mode });

	const openPositionsCount = positions?.length ?? 0;
	const runningStrategiesCount = useMemo(() => {
		if (!strategies) return 0;
		return strategies.filter((s: StrategyData) => {
			const st = String(s.status || "").toUpperCase();
			if (
				st === "RUNNING" ||
				st === "ACTIVE" ||
				st === "IN_POSITION" ||
				st === "IN-POSITION"
			)
				return true;
			return Number(s.open_positions ?? 0) > 0;
		}).length;
	}, [strategies]);

	// Promo fire dot next to Mining — same visibility as the Quests sub-tab:
	// shown only while a campaign is active; in admin-preview mode only admins see it
	// (backend already hides preview campaigns from non-admins, this is defense in depth).
	const miningNodeUuid =
		miningStatus?.nodeUuid ??
		(miningStatus as unknown as { node_uuid?: string })?.node_uuid;
	const { data: promoStatus } = useGetPromoStatus({
		nodeUuid: miningNodeUuid,
	});
	const showPromoFire = Boolean(
		promoStatus?.hasActiveCampaign &&
			(!promoStatus?.isAdminPreview || user?.role === "admin"),
	);

	const localVersion = systemStatus?.version || "1.0.1";
	const [masterVersion, setMasterVersion] = React.useState<string | null>(null);

	React.useEffect(() => {
		const hubApiUrl = import.meta.env.VITE_HUB_API_URL || "/api/v1/hub";
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
			loading: t("common:systemUpdate.startUpdateToast", "Starting platform update..."),
			success: () =>
				t(
					"common:systemUpdate.updateTriggeredToast",
					"Update triggered. The system will restart within a minute.",
				),
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

	const daysLeft = useMemo(() => {
		if (!accountStatus?.planExpiresAt) return null;
		const expiresAt = new Date(accountStatus.planExpiresAt);
		const now = new Date();
		const diffTime = expiresAt.getTime() - now.getTime();
		return Math.ceil(diffTime / (1000 * 60 * 60 * 24));
	}, [accountStatus]);

	const navigationItems = navigationItemConfigs
		.filter((config) => {
			if (config.adminOnly && (!user || user.role !== "admin")) {
				return false;
			}
			if (config.key === "mining" && miningStatus?.isGlobalMiningEnabled === false) {
				return false;
			}
			return true;
		})
		.map((config) => ({
			...config,
			title: t(config.key),
		}));

	// Metrics for compute grid
	const cpuPercent = resources?.system?.cpu_percent ?? 0;
	const cpuCount = resources?.system?.cpu_count ?? 0;
	const ramUsed = resources?.system?.ram_used_gb ?? 0;
	const ramTotal = resources?.system?.ram_total_gb ?? 0;
	const queueRunning = resources?.queue?.running ?? 0;
	const queuePending = resources?.queue?.pending ?? 0;

	return (
		<Sidebar
			variant="sidebar"
			collapsible="icon"
			className="border-r border-white/5 bg-obsidian/75 backdrop-blur-xl transition-[width] duration-300 ease-[cubic-bezier(.22,1,.36,1)]"
		>
			<TooltipProvider delayDuration={0}>
				<div className="relative flex h-full w-full flex-col overflow-hidden">
					{/* Neon spine on right edge */}
					<div className="pointer-events-none absolute inset-y-0 right-0 z-10 w-px bg-gradient-to-b from-transparent via-cyan/30 to-transparent" />

					{/* Header / Brand */}
					<SidebarHeader
						className={cn(
							"flex h-14 shrink-0 items-center border-b border-white/5 transition-all duration-300",
							isExpanded ? "justify-start px-3.5" : "justify-center px-0",
						)}
					>
						<Link
							to="/"
							className={cn(
								"flex items-center transition-transform hover:opacity-90 max-w-full overflow-hidden",
								isExpanded ? "justify-start" : "justify-center w-full",
							)}
						>
							{isExpanded ? (
								<Logo className="h-[42px] w-auto max-w-[185px] shrink-0" />
							) : (
								<Logo iconOnly className="h-9 w-9 shrink-0" />
							)}
						</Link>
					</SidebarHeader>

					{/* Navigation Content */}
					<SidebarContent className="flex-1 overflow-y-auto overflow-x-hidden p-2 space-y-1">
						<nav className="flex flex-col gap-0.5">
							{navigationItems.map((item) => {
								const isActive =
									item.url === "/"
										? pathname === "/"
										: pathname.startsWith(item.url);
								const Icon = item.icon;

								if (!isExpanded) {
									return (
										<Tooltip key={item.key}>
											<TooltipTrigger asChild>
												<Link
													to={item.url}
													className={cn(
														"group relative flex h-10 w-10 items-center justify-center rounded-lg transition-all mx-auto",
														isActive
															? "text-white bg-white/[0.08]"
															: "text-white/50 hover:text-white/90 hover:bg-white/[0.04]",
													)}
												>
													{isActive && (
														<span className="absolute left-0 top-1/2 h-5 w-[3px] -translate-y-1/2 rounded-r-full bg-gradient-to-b from-cyan to-azure shadow-[0_0_12px_rgba(0,212,255,0.9)]" />
													)}
													<Icon
														size={18}
														className={cn(
															"transition-colors",
															isActive
																? "text-cyan drop-shadow-[0_0_6px_rgba(0,212,255,0.8)]"
																: "text-white/45 group-hover:text-white/80",
														)}
													/>
													{item.key === "mining" && showPromoFire && (
														<span className="absolute right-1 top-1 text-[10px] leading-none animate-pulse">
															🔥
														</span>
													)}
												</Link>
											</TooltipTrigger>
											<TooltipContent
												side="right"
												className="bg-obsidian border border-white/10 text-white font-medium text-xs px-2.5 py-1"
											>
												{item.title}
											</TooltipContent>
										</Tooltip>
									);
								}

								return (
									<Link
										key={item.key}
										to={item.url}
										className={cn(
											"group relative flex w-full items-center gap-3.5 rounded-lg px-2.5 h-[38px] text-sm font-medium transition-all",
											isActive
												? "text-white bg-white/[0.08]"
												: "text-white/50 hover:text-white/90 hover:bg-white/[0.035]",
										)}
									>
										{isActive && (
											<span className="absolute left-0 top-1/2 h-5 w-[3px] -translate-y-1/2 rounded-r-full bg-gradient-to-b from-cyan to-azure shadow-[0_0_12px_rgba(0,212,255,0.9)]" />
										)}
										<Icon
											size={18}
											className={cn(
												"shrink-0 transition-colors",
												isActive
													? "text-cyan drop-shadow-[0_0_6px_rgba(0,212,255,0.8)]"
													: "text-white/45 group-hover:text-white/80",
											)}
										/>
										<span className="truncate flex-1 text-left">{item.title}</span>
										{item.key === "mining" && showPromoFire && (
											<span className="ml-auto text-xs leading-none animate-pulse shrink-0">
												🔥
											</span>
										)}
										{item.key === "positions" && (
											<span className="ml-auto inline-flex min-w-[22px] items-center justify-center rounded-md border border-cyan/20 bg-cyan/10 px-1.5 py-0.5 font-mono text-[10px] font-semibold text-cyan shrink-0">
												{openPositionsCount}
											</span>
										)}
										{item.key === "strategies" && (
											<span className="ml-auto inline-flex min-w-[22px] items-center justify-center rounded-md border border-emerald-500/20 bg-emerald-500/10 px-1.5 py-0.5 font-mono text-[10px] font-semibold text-emerald-400 shrink-0">
												{runningStrategiesCount}
											</span>
										)}
									</Link>
								);
							})}
						</nav>
					</SidebarContent>

					{/* Admin-only Compute Grid Widget */}
					{user?.role === "admin" && (
						<div
							className={cn(
								"border-t border-white/5 transition-all duration-300",
								isExpanded ? "p-3" : "p-2 flex justify-center",
							)}
						>
							{isExpanded ? (
								<div className="rounded-xl border border-white/5 bg-white/[0.02] p-3 shadow-inner">
									<div className="flex items-center justify-between text-[10px] uppercase tracking-[0.14em] text-white/35">
										<span>Compute Grid</span>
										<span className="flex items-center gap-1 text-emerald-400 font-semibold">
											<CircleDot size={10} className="animate-pulse" />
											online
										</span>
									</div>
									<div className="mt-2.5 flex items-center gap-3">
										<Radial value={cpuPercent / 100} size={44} stroke={4}>
											<span className="font-mono text-[10px] text-white/80">
												{Math.round(cpuPercent)}%
											</span>
										</Radial>
										<div className="flex-1 space-y-1 font-mono">
											<div className="flex justify-between text-[10px]">
												<span className="text-white/40 font-sans">CPU</span>
												<span className="text-white/70">{cpuCount} cores</span>
											</div>
											<div className="flex justify-between text-[10px]">
												<span className="text-white/40 font-sans">RAM</span>
												<span className="text-white/70">
													{ramUsed}/{ramTotal}G
												</span>
											</div>
											<div className="flex justify-between text-[10px]">
												<span className="text-white/40 font-sans">Queue</span>
												<span className="text-cyan font-semibold">
													{queueRunning} run · {queuePending}q
												</span>
											</div>
										</div>
									</div>
								</div>
							) : (
								<Tooltip>
									<TooltipTrigger asChild>
										<div className="cursor-pointer py-1">
											<Radial value={cpuPercent / 100} size={34} stroke={3}>
												<Cpu size={12} className="text-cyan" />
											</Radial>
										</div>
									</TooltipTrigger>
									<TooltipContent
										side="right"
										className="bg-obsidian border border-white/10 text-white text-xs p-2 space-y-0.5 font-mono"
									>
										<div className="font-semibold text-cyan">Compute Grid</div>
										<div>CPU: {Math.round(cpuPercent)}% ({cpuCount} cores)</div>
										<div>RAM: {ramUsed}/{ramTotal} GB</div>
										<div>Queue: {queueRunning} active · {queuePending} pending</div>
									</TooltipContent>
								</Tooltip>
							)}
						</div>
					)}

					{/* Sidebar Footer Controls */}
					<SidebarFooter className="border-t border-white/5 p-2 shrink-0">
						<div className="flex flex-col gap-2">
							{/* Settings Link */}
							{isExpanded ? (
								<Link
									to="/settings"
									className={cn(
										"group relative flex w-full items-center gap-3.5 rounded-lg px-2.5 h-[38px] text-sm font-medium transition-all",
										pathname.startsWith("/settings")
											? "text-white bg-white/[0.08]"
											: "text-white/50 hover:text-white/90 hover:bg-white/[0.035]",
									)}
								>
									<SettingsIcon
										size={18}
										className={cn(
											"shrink-0 transition-colors",
											pathname.startsWith("/settings")
												? "text-cyan"
												: "text-white/45 group-hover:text-white/80",
										)}
									/>
									<span className="truncate flex-1">{t("settings")}</span>
								</Link>
							) : (
								<Tooltip>
									<TooltipTrigger asChild>
										<Link
											to="/settings"
											className={cn(
												"flex h-9 w-9 items-center justify-center rounded-lg transition-all mx-auto",
												pathname.startsWith("/settings")
													? "text-white bg-white/[0.08]"
													: "text-white/50 hover:text-white/90 hover:bg-white/[0.04]",
											)}
										>
											<SettingsIcon
												size={17}
												className={cn(
													pathname.startsWith("/settings")
														? "text-cyan"
														: "text-white/45",
												)}
											/>
										</Link>
									</TooltipTrigger>
									<TooltipContent side="right" className="bg-obsidian border border-white/10 text-white text-xs">
										{t("settings")}
									</TooltipContent>
								</Tooltip>
							)}

							{/* Admin Version Check */}
							{user && user.role === "admin" && (
								<div className={cn("flex items-center", isExpanded ? "justify-between px-1" : "justify-center")}>
									{isOutdated ? (
										<Popover>
											<PopoverTrigger asChild>
												<Badge
													variant="outline"
													className="cursor-pointer border-amber-500/30 bg-amber-500/10 font-mono text-[9px] text-amber-400 hover:bg-amber-500/20 animate-pulse px-2 py-0.5"
												>
													v{localVersion} (Update)
												</Badge>
											</PopoverTrigger>
											<PopoverContent
												side="right"
												className="flex flex-col gap-2 p-3 text-xs w-60 bg-obsidian border border-white/10 text-white shadow-2xl"
											>
												<div className="flex flex-col gap-0.5">
													<span className="font-semibold text-white">
														{t("common:version", "Version")}: {localVersion}
													</span>
													{masterVersion && (
														<span className="text-amber-400 font-medium">
															{t("common:systemUpdate.updateAvailable", {
																defaultValue: `Update available: v${masterVersion}`,
																version: masterVersion,
															})}
														</span>
													)}
												</div>
												<button
													onClick={handleTriggerUpdate}
													disabled={isUpdating}
													className="mt-1 flex items-center justify-center gap-1.5 rounded-lg bg-gradient-to-r from-amber-500 to-amber-600 px-3 py-1.5 text-xs font-semibold text-black hover:brightness-110 disabled:opacity-50 transition-all shadow-md"
												>
													{isUpdating ? (
														<>
															<Loader2 className="h-3 w-3 animate-spin" />
															<span>{t("common:systemUpdate.updatingStatus", "Updating...")}</span>
														</>
													) : (
														<span>{t("common:systemUpdate.updatePlatform", "Update Platform")}</span>
													)}
												</button>
											</PopoverContent>
										</Popover>
									) : (
										<Badge
											variant="outline"
											className="border-emerald-500/20 bg-emerald-500/10 font-mono text-[9px] text-emerald-400 px-2 py-0.5"
										>
											v{localVersion}
										</Badge>
									)}
									{isExpanded && (
										<span className="text-[10px] text-white/30 font-mono">Quant OS</span>
									)}
								</div>
							)}

							{/* User Plan Badge */}
							{user && (
								<div className={cn("flex items-center", isExpanded ? "justify-between px-1" : "justify-center")}>
									<Link to="/account">
										<Badge
											variant="outline"
											className={cn(
												"capitalize font-medium text-[10px] transition-all cursor-pointer px-2 py-0.5",
												user.plan === "pro"
													? "border-cyan/30 bg-cyan/10 text-cyan hover:bg-cyan/20"
													: "border-amber-500/30 bg-amber-500/10 text-amber-400 hover:bg-amber-500/20",
											)}
										>
											{user.plan !== "pro" && <Crown className="mr-1 h-3 w-3 text-amber-400" />}
											{user.plan}
										</Badge>
									</Link>
								{isExpanded && daysLeft !== null && daysLeft >= 0 && (
									<span
										className={cn(
											"text-[10px] font-mono font-medium",
											daysLeft <= 3
												? "text-rose-400"
												: daysLeft <= 7
													? "text-amber-400"
													: "text-emerald-400",
										)}
									>
										{daysLeft}d left
									</span>
								)}
								</div>
							)}

							{/* Switchers & Collapse Toggle */}
							<div
								className={cn(
									"flex items-center pt-1 border-t border-white/5",
									isExpanded
										? "justify-between px-1 gap-1"
										: "flex-col gap-1.5 justify-center items-center py-1 w-full",
								)}
							>
								<div
									className={cn(
										"flex items-center",
										isExpanded ? "gap-1" : "flex-col gap-1.5 items-center w-full",
									)}
								>
									<ThemeSwitcher />
									<LanguageSwitcher />
								</div>
								<button
									onClick={toggleSidebar}
									className="flex h-8 w-8 items-center justify-center rounded-lg text-white/40 hover:bg-white/5 hover:text-white transition-colors"
									title={isExpanded ? "Collapse sidebar (⌘B)" : "Expand sidebar (⌘B)"}
								>
									{isExpanded ? <ChevronsLeft size={16} /> : <ChevronsRight size={16} />}
								</button>
							</div>
						</div>
					</SidebarFooter>
				</div>
			</TooltipProvider>
		</Sidebar>
	);
}
