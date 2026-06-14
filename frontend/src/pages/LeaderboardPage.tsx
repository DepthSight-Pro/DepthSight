// frontend/src/pages/LeaderboardPage.tsx

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AnimatePresence, motion } from "framer-motion";
import {
	AlertCircle,
	BarChart3,
	ChevronRight,
	Clock,
	Copy,
	ExternalLink,
	Lock,
	Medal,
	Trash2,
	TrendingUp,
	Trophy,
	Users,
} from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { PageLayout } from "@/components/layout/PageLayout";
import { AppLoader } from "@/components/shared/AppLoader";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
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
	Table,
	TableBody,
	TableCell,
	TableHead,
	TableHeader,
	TableRow,
} from "@/components/ui/table";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
	Tooltip,
	TooltipContent,
	TooltipProvider,
	TooltipTrigger,
} from "@/components/ui/tooltip";
import { useToast } from "@/components/ui/use-toast";
import { useAuth } from "@/context/AuthContext";
import { apiClient } from "@/lib/apiClient";
import { cn } from "@/lib/utils";
import type { LeaderboardEntry } from "@/types/api";

const LeaderboardPage = () => {
	const { t } = useTranslation(["leaderboard", "common", "research"]);
	const { user } = useAuth();
	const { toast } = useToast();
	const queryClient = useQueryClient();
	const isAdmin = user?.role === "admin";

	const [period, setPeriod] = useState<"all_time" | "monthly" | "weekly">(
		"all_time",
	);
	const [category, setCategory] = useState<"sharpe_ratio" | "net_pnl_percent">(
		"sharpe_ratio",
	);

	const {
		data: leaderboard,
		isLoading,
		isError,
		error,
	} = useQuery<LeaderboardEntry[], Error>({
		queryKey: ["leaderboard", period, category],
		queryFn: () =>
			apiClient<LeaderboardEntry[]>(
				`/leaderboard?period=${period}&category=${category}`,
			),
	});

	const deleteMutation = useMutation({
		mutationFn: (entryId: string | number) =>
			apiClient(`/leaderboard/${entryId}`, { method: "DELETE" }),
		onSuccess: () => {
			queryClient.invalidateQueries({ queryKey: ["leaderboard"] });
			toast({
				title: t("common:success"),
				description: "Entry deleted from the leaderboard",
			});
		},
		onError: (err) => {
			const error = err as Error;
			toast({
				title: t("common:errorTitle"),
				description: error.message || "Failed to delete entry",
				variant: "destructive",
			});
		},
	});

	const handleDelete = (entryId: string | number, username: string) => {
		if (
			window.confirm(
				`Are you sure you want to delete the result of user ${username} from the leaderboard?`,
			)
		) {
			deleteMutation.mutate(entryId);
		}
	};

	if (isLoading) {
		return <AppLoader fullLogo text={t("loading")} />;
	}

	if (isError) {
		return (
			<PageLayout title={t("pageTitle")}>
				<Alert variant="destructive">
					<AlertCircle className="h-4 w-4" />
					<AlertTitle>{t("common:errorTitle")}</AlertTitle>
					<AlertDescription>{error.message}</AlertDescription>
				</Alert>
			</PageLayout>
		);
	}

	const topThree = leaderboard?.slice(0, 3) || [];
	const rest = leaderboard?.slice(3) || [];

	const formatScore = (score: number, cat: string) => {
		if (cat === "sharpe_ratio") return score.toFixed(2);
		if (cat === "net_pnl_percent")
			return `${score > 0 ? "+" : ""}${score.toFixed(2)}%`;
		return score.toString();
	};

	return (
		<PageLayout title={t("pageTitle")} description={t("description")}>
			<div className="flex flex-col gap-8">
				{/* Filters */}
				<div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4">
					<Tabs
						value={period}
						onValueChange={(v) =>
							setPeriod(v as "all_time" | "monthly" | "weekly")
						}
						className="w-full sm:w-auto"
					>
						<TabsList className="grid grid-cols-3 w-full sm:w-[360px]">
							<TabsTrigger value="weekly" className="text-xs">
								{t("filters.period.weekly")}
							</TabsTrigger>
							<TabsTrigger value="monthly" className="text-xs">
								{t("filters.period.monthly")}
							</TabsTrigger>
							<TabsTrigger value="all_time" className="text-xs">
								{t("filters.period.all_time")}
							</TabsTrigger>
						</TabsList>
					</Tabs>

					<Tabs
						value={category}
						onValueChange={(v) =>
							setCategory(v as "sharpe_ratio" | "net_pnl_percent")
						}
						className="w-full sm:w-auto"
					>
						<TabsList className="grid grid-cols-2 w-full sm:w-[320px]">
							<TabsTrigger
								value="sharpe_ratio"
								className="flex items-center gap-2 text-xs"
							>
								<BarChart3 className="h-3.5 w-3.5" />
								{t("filters.category.sharpe_ratio")}
							</TabsTrigger>
							<TabsTrigger
								value="net_pnl_percent"
								className="flex items-center gap-2 text-xs"
							>
								<TrendingUp className="h-3.5 w-3.5" />
								{t("filters.category.net_pnl_percent")}
							</TabsTrigger>
						</TabsList>
					</Tabs>
				</div>

				{/* Podium for Top 3 */}
				{topThree.length > 0 && (
					<div className="grid grid-cols-1 md:grid-cols-3 gap-6 items-end mt-4">
						{/* Rank 2 */}
						{topThree[1] && (
							<motion.div
								initial={{ opacity: 0, y: 20 }}
								animate={{ opacity: 1, y: 0 }}
								transition={{ delay: 0.1 }}
							>
								<Card className="relative overflow-hidden border-slate-300/20 bg-slate-400/5 hover:bg-slate-400/10 transition-colors">
									<div className="absolute top-0 right-0 p-4 flex gap-2">
										{isAdmin && (
											<Button
												variant="ghost"
												size="icon"
												className="h-8 w-8 text-destructive hover:bg-destructive/10"
												onClick={() =>
													handleDelete(
														topThree[1].id,
														topThree[1].user.username,
													)
												}
											>
												<Trash2 className="h-4 w-4" />
											</Button>
										)}
										<Medal className="h-10 w-10 text-slate-300 opacity-20" />
									</div>
									<CardHeader className="text-center pb-2">
										<div className="flex justify-center mb-2">
											<div className="relative">
												<Avatar className="h-16 w-16 border-2 border-slate-300/30">
													<AvatarFallback className="bg-slate-300/10 text-slate-300">
														{topThree[1].user.username
															.substring(0, 2)
															.toUpperCase()}
													</AvatarFallback>
												</Avatar>
												<div className="absolute -bottom-1 -right-1 bg-slate-300 text-slate-900 rounded-full h-6 w-6 flex items-center justify-center text-xs font-bold border-2 border-background">
													2
												</div>
											</div>
										</div>
										<CardTitle className="text-lg truncate">
											{topThree[1].user.username}
										</CardTitle>
										<CardDescription className="text-2xl font-bold text-foreground">
											{formatScore(topThree[1].score, category)}
										</CardDescription>
									</CardHeader>
									<CardContent className="flex flex-col gap-2 justify-center pb-6">
										<Button
											variant="outline"
											size="sm"
											className="w-full"
											asChild
										>
											<a
												href={`/s/${topThree[1].sharedBacktestSlug}#equity`}
												target="_blank"
												rel="noopener noreferrer"
											>
												<ExternalLink className="mr-2 h-4 w-4" />
												{t("table.viewReport")}
											</a>
										</Button>
										<TooltipProvider>
											<Tooltip>
												<TooltipTrigger asChild>
													<Button
														variant="ghost"
														size="sm"
														className="w-full text-xs gap-2"
														disabled={!topThree[1].isConfigPublic}
														asChild={topThree[1].isConfigPublic}
													>
														{topThree[1].isConfigPublic ? (
															<a
																href={`/s/${topThree[1].sharedBacktestSlug}#config`}
																target="_blank"
																rel="noopener noreferrer"
															>
																<Copy className="h-3.5 w-3.5" />
																{t("table.copyStrategy")}
															</a>
														) : (
															<>
																<Lock className="h-3.5 w-3.5 opacity-50" />
																{t("table.copyStrategy")}
															</>
														)}
													</Button>
												</TooltipTrigger>
												{!topThree[1].isConfigPublic && (
													<TooltipContent>Private strategy</TooltipContent>
												)}
											</Tooltip>
										</TooltipProvider>
									</CardContent>
								</Card>
							</motion.div>
						)}

						{/* Rank 1 */}
						{topThree[0] && (
							<motion.div
								initial={{ opacity: 0, scale: 0.9 }}
								animate={{ opacity: 1, scale: 1 }}
								transition={{ type: "spring", damping: 12 }}
							>
								<Card className="relative overflow-hidden border-yellow-500/30 bg-yellow-500/5 hover:bg-yellow-500/10 transition-all shadow-lg shadow-yellow-500/5 md:-translate-y-4">
									<div className="absolute top-0 right-0 p-4 flex gap-2">
										{isAdmin && (
											<Button
												variant="ghost"
												size="icon"
												className="h-8 w-8 text-destructive hover:bg-destructive/10"
												onClick={() =>
													handleDelete(
														topThree[0].id,
														topThree[0].user.username,
													)
												}
											>
												<Trash2 className="h-4 w-4" />
											</Button>
										)}
										<Trophy className="h-12 w-12 text-yellow-500 opacity-20" />
									</div>
									<div className="absolute top-0 left-0 bg-yellow-500 text-yellow-950 text-[10px] font-bold px-3 py-1 rounded-br-lg uppercase tracking-wider">
										Champion
									</div>
									<CardHeader className="text-center pb-2 pt-8">
										<div className="flex justify-center mb-3">
											<div className="relative">
												<Avatar className="h-24 w-24 border-4 border-yellow-500/40">
													<AvatarFallback className="bg-yellow-500/10 text-yellow-500 text-xl">
														{topThree[0].user.username
															.substring(0, 2)
															.toUpperCase()}
													</AvatarFallback>
												</Avatar>
												<div className="absolute -bottom-2 -right-2 bg-yellow-500 text-yellow-950 rounded-full h-8 w-8 flex items-center justify-center text-sm font-bold border-2 border-background">
													1
												</div>
											</div>
										</div>
										<CardTitle className="text-xl truncate">
											{topThree[0].user.username}
										</CardTitle>
										<CardDescription className="text-3xl font-black text-yellow-500">
											{formatScore(topThree[0].score, category)}
										</CardDescription>
									</CardHeader>
									<CardContent className="flex flex-col gap-2 pb-8 px-6">
										<div className="grid grid-cols-2 gap-2 text-[10px] text-muted-foreground uppercase mb-2">
											<div className="bg-background/50 rounded p-2 text-center">
												<div className="text-foreground font-bold">
													{topThree[0].meta_data?.win_rate?.toFixed(1)}%
												</div>
												Win Rate
											</div>
											<div className="bg-background/50 rounded p-2 text-center">
												<div className="text-foreground font-bold">
													{topThree[0].meta_data?.trades}
												</div>
												Trades
											</div>
										</div>
										<Button
											variant="default"
											className="w-full bg-yellow-600 hover:bg-yellow-500 text-white shadow-lg shadow-yellow-900/20"
											asChild
										>
											<a
												href={`/s/${topThree[0].sharedBacktestSlug}#equity`}
												target="_blank"
												rel="noopener noreferrer"
											>
												<ExternalLink className="mr-2 h-4 w-4" />
												{t("table.viewReport")}
											</a>
										</Button>
										<Button
											variant="ghost"
											size="sm"
											className="w-full text-xs gap-2 hover:bg-yellow-500/10"
											disabled={!topThree[0].isConfigPublic}
											asChild={topThree[0].isConfigPublic}
										>
											{topThree[0].isConfigPublic ? (
												<a
													href={`/s/${topThree[0].sharedBacktestSlug}#config`}
													target="_blank"
													rel="noopener noreferrer"
												>
													<Copy className="h-3.5 w-3.5" />
													{t("table.copyStrategy")}
												</a>
											) : (
												<>
													<Lock className="h-3.5 w-3.5 opacity-50" />
													{t("table.copyStrategy")}
												</>
											)}
										</Button>
									</CardContent>
								</Card>
							</motion.div>
						)}

						{/* Rank 3 */}
						{topThree[2] && (
							<motion.div
								initial={{ opacity: 0, y: 20 }}
								animate={{ opacity: 1, y: 0 }}
								transition={{ delay: 0.2 }}
							>
								<Card className="relative overflow-hidden border-amber-600/20 bg-amber-600/5 hover:bg-amber-600/10 transition-colors">
									<div className="absolute top-0 right-0 p-4 flex gap-2">
										{isAdmin && (
											<Button
												variant="ghost"
												size="icon"
												className="h-8 w-8 text-destructive hover:bg-destructive/10"
												onClick={() =>
													handleDelete(
														topThree[2].id,
														topThree[2].user.username,
													)
												}
											>
												<Trash2 className="h-4 w-4" />
											</Button>
										)}
										<Medal className="h-10 w-10 text-amber-600 opacity-20" />
									</div>
									<CardHeader className="text-center pb-2">
										<div className="flex justify-center mb-2">
											<div className="relative">
												<Avatar className="h-16 w-16 border-2 border-amber-600/30">
													<AvatarFallback className="bg-amber-600/10 text-amber-600">
														{topThree[2].user.username
															.substring(0, 2)
															.toUpperCase()}
													</AvatarFallback>
												</Avatar>
												<div className="absolute -bottom-1 -right-1 bg-amber-600 text-amber-950 rounded-full h-6 w-6 flex items-center justify-center text-xs font-bold border-2 border-background">
													3
												</div>
											</div>
										</div>
										<CardTitle className="text-lg truncate">
											{topThree[2].user.username}
										</CardTitle>
										<CardDescription className="text-2xl font-bold text-foreground">
											{formatScore(topThree[2].score, category)}
										</CardDescription>
									</CardHeader>
									<CardContent className="flex flex-col gap-2 justify-center pb-6">
										<Button
											variant="outline"
											size="sm"
											className="w-full"
											asChild
										>
											<a
												href={`/s/${topThree[2].sharedBacktestSlug}#equity`}
												target="_blank"
												rel="noopener noreferrer"
											>
												<ExternalLink className="mr-2 h-4 w-4" />
												{t("table.viewReport")}
											</a>
										</Button>
										<TooltipProvider>
											<Tooltip>
												<TooltipTrigger asChild>
													<Button
														variant="ghost"
														size="sm"
														className="w-full text-xs gap-2"
														disabled={!topThree[2].isConfigPublic}
														asChild={topThree[2].isConfigPublic}
													>
														{topThree[2].isConfigPublic ? (
															<a
																href={`/s/${topThree[2].sharedBacktestSlug}#config`}
																target="_blank"
																rel="noopener noreferrer"
															>
																<Copy className="h-3.5 w-3.5" />
																{t("table.copyStrategy")}
															</a>
														) : (
															<>
																<Lock className="h-3.5 w-3.5 opacity-50" />
																{t("table.copyStrategy")}
															</>
														)}
													</Button>
												</TooltipTrigger>
												{!topThree[2].isConfigPublic && (
													<TooltipContent>Private strategy</TooltipContent>
												)}
											</Tooltip>
										</TooltipProvider>
									</CardContent>
								</Card>
							</motion.div>
						)}
					</div>
				)}

				{/* Main Table for the rest */}
				<Card className="mt-4 border-muted/30 shadow-sm overflow-hidden">
					<div className="rounded-md border-0">
						<Table>
							<TableHeader className="bg-muted/30">
								<TableRow className="hover:bg-transparent border-b">
									<TableHead className="w-[80px] text-center">
										{t("table.rank")}
									</TableHead>
									<TableHead>{t("table.user")}</TableHead>
									<TableHead className="text-right">
										{t("table.score")}
									</TableHead>
									<TableHead className="hidden lg:table-cell text-center">
										Stats
									</TableHead>
									<TableHead className="hidden sm:table-cell text-center">
										Symbol
									</TableHead>
									<TableHead className="text-right">
										{t("table.actions")}
									</TableHead>
								</TableRow>
							</TableHeader>
							<TableBody>
								<AnimatePresence mode="popLayout">
									{rest.length > 0 ? (
										rest.map((entry) => (
											<motion.tr
												key={entry.id}
												initial={{ opacity: 0 }}
												animate={{ opacity: 1 }}
												exit={{ opacity: 0 }}
												className="group border-b hover:bg-muted/30 transition-colors"
											>
												<TableCell className="text-center font-mono font-medium">
													<div className="flex items-center justify-center h-8 w-8 rounded-full bg-muted/50 mx-auto">
														{entry.rank}
													</div>
												</TableCell>
												<TableCell>
													<div className="flex items-center gap-3">
														<Avatar className="h-8 w-8 border border-muted/50">
															<AvatarFallback className="text-[10px]">
																{entry.user.username
																	.substring(0, 2)
																	.toUpperCase()}
															</AvatarFallback>
														</Avatar>
														<span className="font-semibold text-sm">
															{entry.user.username}
														</span>
													</div>
												</TableCell>
												<TableCell className="text-right">
													<span
														className={cn(
															"font-bold font-mono",
															category === "net_pnl_percent" &&
																(entry.score > 0
																	? "text-green-500"
																	: "text-red-500"),
														)}
													>
														{formatScore(entry.score, category)}
													</span>
												</TableCell>
												<TableCell className="hidden lg:table-cell text-center">
													<div className="flex items-center justify-center gap-4 text-[11px] text-muted-foreground font-medium">
														<div className="flex items-center gap-1">
															<span className="text-foreground">
																{entry.meta_data?.win_rate?.toFixed(0)}%
															</span>{" "}
															WR
														</div>
														<div className="flex items-center gap-1">
															<span className="text-foreground">
																{entry.meta_data?.trades}
															</span>{" "}
															T
														</div>
													</div>
												</TableCell>
												<TableCell className="hidden sm:table-cell text-center">
													<Badge
														variant="outline"
														className="bg-background/50 font-mono text-[10px] uppercase"
													>
														{entry.meta_data?.symbol || "N/A"}
													</Badge>
												</TableCell>
												<TableCell className="text-right">
													<TooltipProvider>
														<div className="flex items-center justify-end gap-2">
															{isAdmin && (
																<Tooltip>
																	<TooltipTrigger asChild>
																		<Button
																			variant="ghost"
																			size="icon"
																			className="h-8 w-8 text-destructive opacity-0 group-hover:opacity-100 transition-opacity hover:bg-destructive/10"
																			onClick={() =>
																				handleDelete(
																					entry.id,
																					entry.user.username,
																				)
																			}
																		>
																			<Trash2 className="h-4 w-4" />
																		</Button>
																	</TooltipTrigger>
																	<TooltipContent>
																		Remove from leaderboard
																	</TooltipContent>
																</Tooltip>
															)}

															<Tooltip>
																<TooltipTrigger asChild>
																	<Button
																		variant="ghost"
																		size="icon"
																		className="h-8 w-8 opacity-0 group-hover:opacity-100 transition-opacity"
																		asChild
																	>
																		<a
																			href={`/s/${entry.sharedBacktestSlug}#equity`}
																			target="_blank"
																			rel="noopener noreferrer"
																		>
																			<ExternalLink className="h-4 w-4" />
																		</a>
																	</Button>
																</TooltipTrigger>
																<TooltipContent>
																	{t("table.viewReport")}
																</TooltipContent>
															</Tooltip>

															<Tooltip>
																<TooltipTrigger asChild>
																	<Button
																		variant="ghost"
																		size="sm"
																		className="h-8 px-2 text-[11px] font-semibold gap-1.5 hidden md:flex hover:bg-primary/10 hover:text-primary"
																		disabled={!entry.isConfigPublic}
																		asChild={entry.isConfigPublic}
																	>
																		{entry.isConfigPublic ? (
																			<a
																				href={`/s/${entry.sharedBacktestSlug}#config`}
																				target="_blank"
																				rel="noopener noreferrer"
																			>
																				<Copy className="h-3.5 w-3.5" />
																				{t("table.copyStrategy")}
																			</a>
																		) : (
																			<>
																				<Lock className="h-3.5 w-3.5 opacity-50" />
																				{t("table.copyStrategy")}
																			</>
																		)}
																	</Button>
																</TooltipTrigger>
																{!entry.isConfigPublic && (
																	<TooltipContent>
																		Private strategy
																	</TooltipContent>
																)}
															</Tooltip>

															<Button
																variant="ghost"
																size="icon"
																className="h-8 w-8 md:hidden"
															>
																<ChevronRight className="h-4 w-4 text-muted-foreground" />
															</Button>
														</div>
													</TooltipProvider>
												</TableCell>
											</motion.tr>
										))
									) : leaderboard?.length === 0 ? (
										<TableRow>
											<TableCell
												colSpan={6}
												className="h-[200px] text-center text-muted-foreground"
											>
												<div className="flex flex-col items-center gap-2">
													<Users className="h-10 w-10 opacity-20 mb-2" />
													<p className="font-medium">{t("noData")}</p>
												</div>
											</TableCell>
										</TableRow>
									) : null}
								</AnimatePresence>
							</TableBody>
						</Table>
					</div>
				</Card>

				{/* Footer info */}
				<div className="flex flex-col sm:flex-row justify-between items-center gap-4 text-xs text-muted-foreground mt-4 px-1">
					<div className="flex items-center gap-4">
						<div className="flex items-center gap-1.5">
							<Clock className="h-3.5 w-3.5" />
							Updated 5m ago
						</div>
						<div className="flex items-center gap-1.5">
							<Users className="h-3.5 w-3.5" />
							{leaderboard?.length || 0} Traders Competing
						</div>
					</div>
					<p>Publish your backtest to join the leaderboard!</p>
				</div>
			</div>
		</PageLayout>
	);
};

export default LeaderboardPage;
