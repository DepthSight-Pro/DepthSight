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
	Table,
	TableBody,
	TableCell,
	TableHead,
	TableHeader,
	TableRow,
} from "@/components/ui/table";
import { Segmented } from "@/components/ui/quant-ui";
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
		return (
			<PageLayout title={t("pageTitle")} description={t("description")}>
				<div className="flex-1 flex flex-col items-center justify-center min-h-[calc(100vh-250px)] h-full w-full">
					<AppLoader size="xl" fullLogo text={t("loading")} />
				</div>
			</PageLayout>
		);
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
					<Segmented<"weekly" | "monthly" | "all_time">
						size="md"
						value={period}
						onChange={(v) => setPeriod(v)}
						options={[
							{ value: "weekly", label: t("filters.period.weekly") },
							{ value: "monthly", label: t("filters.period.monthly") },
							{ value: "all_time", label: t("filters.period.all_time") },
						]}
					/>

					<Segmented<"sharpe_ratio" | "net_pnl_percent">
						size="md"
						value={category}
						onChange={(v) => setCategory(v)}
						options={[
							{
								value: "sharpe_ratio",
								label: t("filters.category.sharpe_ratio"),
								icon: <BarChart3 className="h-3.5 w-3.5" />,
							},
							{
								value: "net_pnl_percent",
								label: t("filters.category.net_pnl_percent"),
								icon: <TrendingUp className="h-3.5 w-3.5" />,
							},
						]}
					/>
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
								<div className="relative overflow-hidden rounded-2xl border border-cyan/30 glass shadow-xl transition-all hover:border-cyan/50">
									{/* Ambient glow */}
									<div className="pointer-events-none absolute -top-10 -right-10 w-44 h-44 bg-cyan/10 rounded-full blur-3xl" />

									<div className="absolute top-0 right-0 p-4 flex gap-2 z-10">
										{isAdmin && (
											<Button
												variant="ghost"
												size="icon"
												className="h-8 w-8 text-destructive hover:bg-destructive/10 rounded-xl"
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
										<Medal className="h-10 w-10 text-cyan opacity-20" />
									</div>
									<div className="text-center pb-2 pt-6 px-6 relative z-10">
										<div className="flex justify-center mb-2">
											<div className="relative">
												<Avatar className="h-16 w-16 border-2 border-cyan/40 shadow-[0_0_15px_-4px_rgba(0,212,255,0.4)]">
													<AvatarFallback className="bg-cyan/10 text-cyan font-bold">
														{topThree[1].user.username
															.substring(0, 2)
															.toUpperCase()}
													</AvatarFallback>
												</Avatar>
												<div className="absolute -bottom-1 -right-1 bg-gradient-to-r from-cyan to-azure text-black rounded-full h-6 w-6 flex items-center justify-center text-xs font-bold border-2 border-[#07090e] shadow-sm">
													2
												</div>
											</div>
										</div>
										<h3 className="text-lg font-bold text-white truncate">
											{topThree[1].user.username}
										</h3>
										<p className="text-2xl font-black font-mono text-cyan mt-0.5">
											{formatScore(topThree[1].score, category)}
										</p>
									</div>
									<div className="flex flex-col gap-2 justify-center pb-6 px-6 pt-2 relative z-10">
										<Button
											variant="outline"
											size="sm"
											className="w-full rounded-xl bg-white/[0.04] border-white/10 text-white hover:bg-white/[0.08] hover:border-white/20 transition-all font-mono text-xs"
											asChild
										>
											<a
												href={`/s/${topThree[1].sharedBacktestSlug}#equity`}
												target="_blank"
												rel="noopener noreferrer"
											>
												<ExternalLink className="mr-2 h-3.5 w-3.5 text-cyan" />
												{t("table.viewReport")}
											</a>
										</Button>
										<TooltipProvider>
											<Tooltip>
												<TooltipTrigger asChild>
													<Button
														variant="ghost"
														size="sm"
														className="w-full text-xs gap-2 rounded-xl text-white/60 hover:text-white hover:bg-white/5"
														disabled={!topThree[1].isConfigPublic}
														asChild={topThree[1].isConfigPublic}
													>
														{topThree[1].isConfigPublic ? (
															<a
																href={`/s/${topThree[1].sharedBacktestSlug}#config`}
																target="_blank"
																rel="noopener noreferrer"
															>
																<Copy className="h-3.5 w-3.5 text-cyan" />
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
													<TooltipContent className="bg-[#0c0d12] border-white/10 text-white text-xs">Private strategy</TooltipContent>
												)}
											</Tooltip>
										</TooltipProvider>
									</div>
								</div>
							</motion.div>
						)}

						{/* Rank 1 */}
						{topThree[0] && (
							<motion.div
								initial={{ opacity: 0, scale: 0.9 }}
								animate={{ opacity: 1, scale: 1 }}
								transition={{ type: "spring", damping: 12 }}
							>
								<div className="relative overflow-hidden rounded-2xl border border-amber-500/40 glass shadow-[0_0_40px_-10px_rgba(245,158,11,0.25)] transition-all md:-translate-y-4 hover:border-amber-400">
									{/* Ambient gold glow */}
									<div className="pointer-events-none absolute -top-12 -right-12 w-52 h-52 bg-amber-500/15 rounded-full blur-3xl" />

									<div className="absolute top-0 right-0 p-4 flex gap-2 z-10">
										{isAdmin && (
											<Button
												variant="ghost"
												size="icon"
												className="h-8 w-8 text-destructive hover:bg-destructive/10 rounded-xl"
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
										<Trophy className="h-12 w-12 text-amber-500 opacity-25" />
									</div>
									<div className="absolute top-0 left-0 bg-gradient-to-r from-amber-500 to-amber-600 text-black text-[10px] font-mono font-bold px-3 py-1 rounded-br-xl uppercase tracking-wider shadow-sm z-10">
										Champion
									</div>
									<div className="text-center pb-2 pt-8 px-6 relative z-10">
										<div className="flex justify-center mb-3">
											<div className="relative">
												<Avatar className="h-24 w-24 border-4 border-amber-400/60 shadow-[0_0_24px_-4px_rgba(245,158,11,0.6)]">
													<AvatarFallback className="bg-amber-500/10 text-amber-400 text-2xl font-bold">
														{topThree[0].user.username
															.substring(0, 2)
															.toUpperCase()}
													</AvatarFallback>
												</Avatar>
												<div className="absolute -bottom-2 -right-2 bg-gradient-to-r from-amber-400 to-amber-500 text-black rounded-full h-8 w-8 flex items-center justify-center text-sm font-bold border-2 border-[#0c0d14] shadow-md">
													1
												</div>
											</div>
										</div>
										<h3 className="text-xl font-bold text-white truncate">
											{topThree[0].user.username}
										</h3>
										<p className="text-3xl font-black font-mono text-amber-400 mt-1">
											{formatScore(topThree[0].score, category)}
										</p>
									</div>
									<div className="flex flex-col gap-2 pb-8 px-6 pt-2 relative z-10">
										<div className="grid grid-cols-2 gap-2 text-[10px] text-white/50 uppercase mb-2">
											<div className="bg-white/[0.03] border border-white/5 rounded-xl p-2.5 text-center">
												<div className="text-white font-mono font-bold text-sm">
													{topThree[0].meta_data?.win_rate?.toFixed(1)}%
												</div>
												Win Rate
											</div>
											<div className="bg-white/[0.03] border border-white/5 rounded-xl p-2.5 text-center">
												<div className="text-white font-mono font-bold text-sm">
													{topThree[0].meta_data?.trades}
												</div>
												Trades
											</div>
										</div>
										<Button
											variant="default"
											className="w-full bg-gradient-to-r from-amber-500 to-amber-600 hover:from-amber-400 hover:to-amber-500 text-black font-semibold shadow-lg shadow-amber-500/25 rounded-xl text-xs"
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
											className="w-full text-xs gap-2 rounded-xl text-white/60 hover:text-white hover:bg-white/5"
											disabled={!topThree[0].isConfigPublic}
											asChild={topThree[0].isConfigPublic}
										>
											{topThree[0].isConfigPublic ? (
												<a
													href={`/s/${topThree[0].sharedBacktestSlug}#config`}
													target="_blank"
													rel="noopener noreferrer"
												>
													<Copy className="h-3.5 w-3.5 text-amber-400" />
													{t("table.copyStrategy")}
												</a>
											) : (
												<>
													<Lock className="h-3.5 w-3.5 opacity-50" />
													{t("table.copyStrategy")}
												</>
											)}
										</Button>
									</div>
								</div>
							</motion.div>
						)}

						{/* Rank 3 */}
						{topThree[2] && (
							<motion.div
								initial={{ opacity: 0, y: 20 }}
								animate={{ opacity: 1, y: 0 }}
								transition={{ delay: 0.2 }}
							>
								<div className="relative overflow-hidden rounded-2xl border border-violet-500/30 glass shadow-xl transition-all hover:border-violet-500/50">
									{/* Ambient glow */}
									<div className="pointer-events-none absolute -top-10 -right-10 w-44 h-44 bg-violet-500/10 rounded-full blur-3xl" />

									<div className="absolute top-0 right-0 p-4 flex gap-2 z-10">
										{isAdmin && (
											<Button
												variant="ghost"
												size="icon"
												className="h-8 w-8 text-destructive hover:bg-destructive/10 rounded-xl"
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
										<Medal className="h-10 w-10 text-violet-400 opacity-20" />
									</div>
									<div className="text-center pb-2 pt-6 px-6 relative z-10">
										<div className="flex justify-center mb-2">
											<div className="relative">
												<Avatar className="h-16 w-16 border-2 border-violet-500/40 shadow-[0_0_15px_-4px_rgba(168,85,247,0.4)]">
													<AvatarFallback className="bg-violet-500/10 text-violet-400 font-bold">
														{topThree[2].user.username
															.substring(0, 2)
															.toUpperCase()}
													</AvatarFallback>
												</Avatar>
												<div className="absolute -bottom-1 -right-1 bg-gradient-to-r from-violet-500 to-indigo-500 text-white rounded-full h-6 w-6 flex items-center justify-center text-xs font-bold border-2 border-[#08070e] shadow-sm">
													3
												</div>
											</div>
										</div>
										<h3 className="text-lg font-bold text-white truncate">
											{topThree[2].user.username}
										</h3>
										<p className="text-2xl font-black font-mono text-violet-400 mt-0.5">
											{formatScore(topThree[2].score, category)}
										</p>
									</div>
									<div className="flex flex-col gap-2 justify-center pb-6 px-6 pt-2 relative z-10">
										<Button
											variant="outline"
											size="sm"
											className="w-full rounded-xl bg-white/[0.04] border-white/10 text-white hover:bg-white/[0.08] hover:border-white/20 transition-all font-mono text-xs"
											asChild
										>
											<a
												href={`/s/${topThree[2].sharedBacktestSlug}#equity`}
												target="_blank"
												rel="noopener noreferrer"
											>
												<ExternalLink className="mr-2 h-3.5 w-3.5 text-violet-400" />
												{t("table.viewReport")}
											</a>
										</Button>
										<TooltipProvider>
											<Tooltip>
												<TooltipTrigger asChild>
													<Button
														variant="ghost"
														size="sm"
														className="w-full text-xs gap-2 rounded-xl text-white/60 hover:text-white hover:bg-white/5"
														disabled={!topThree[2].isConfigPublic}
														asChild={topThree[2].isConfigPublic}
													>
														{topThree[2].isConfigPublic ? (
															<a
																href={`/s/${topThree[2].sharedBacktestSlug}#config`}
																target="_blank"
																rel="noopener noreferrer"
															>
																<Copy className="h-3.5 w-3.5 text-violet-400" />
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
													<TooltipContent className="bg-[#0c0d12] border-white/10 text-white text-xs">Private strategy</TooltipContent>
												)}
											</Tooltip>
										</TooltipProvider>
									</div>
								</div>
							</motion.div>
						)}
					</div>
				)}

				{/* Main Table for the rest */}
				<div className="mt-4 rounded-2xl border border-white/10 glass shadow-xl overflow-hidden">
					<div className="overflow-x-auto">
						<Table>
							<TableHeader className="bg-white/[0.02] border-b border-white/10">
								<TableRow className="hover:bg-transparent border-b border-white/10">
									<TableHead className="w-[80px] text-center font-mono text-[11px] uppercase tracking-wider text-white/50">
										{t("table.rank")}
									</TableHead>
									<TableHead className="font-mono text-[11px] uppercase tracking-wider text-white/50">{t("table.user")}</TableHead>
									<TableHead className="text-right font-mono text-[11px] uppercase tracking-wider text-white/50">
										{t("table.score")}
									</TableHead>
									<TableHead className="hidden lg:table-cell text-center font-mono text-[11px] uppercase tracking-wider text-white/50">
										Stats
									</TableHead>
									<TableHead className="hidden sm:table-cell text-center font-mono text-[11px] uppercase tracking-wider text-white/50">
										Symbol
									</TableHead>
									<TableHead className="text-right font-mono text-[11px] uppercase tracking-wider text-white/50">
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
												className="group border-b border-white/5 hover:bg-white/[0.03] transition-colors"
											>
												<TableCell className="text-center font-mono font-medium">
													<div className="flex items-center justify-center h-7 w-7 rounded-lg bg-white/[0.04] border border-white/10 text-white/70 mx-auto text-xs font-mono">
														{entry.rank}
													</div>
												</TableCell>
												<TableCell>
													<div className="flex items-center gap-3">
														<Avatar className="h-8 w-8 border border-white/10 ring-1 ring-white/5">
															<AvatarFallback className="text-[10px] bg-white/5 text-white/80 font-mono">
																{entry.user.username
																	.substring(0, 2)
																	.toUpperCase()}
															</AvatarFallback>
														</Avatar>
														<span className="font-semibold text-sm text-white/90 group-hover:text-white transition-colors">
															{entry.user.username}
														</span>
													</div>
												</TableCell>
												<TableCell className="text-right">
													<span
														className={cn(
															"font-bold font-mono text-sm",
															category === "net_pnl_percent" &&
																(entry.score > 0
																	? "text-emerald-400"
																	: "text-rose-400"),
														)}
													>
														{formatScore(entry.score, category)}
													</span>
												</TableCell>
												<TableCell className="hidden lg:table-cell text-center">
													<div className="flex items-center justify-center gap-4 text-[11px] text-white/50 font-mono">
														<div className="flex items-center gap-1">
															<span className="text-white/80 font-bold">
																{entry.meta_data?.win_rate?.toFixed(0)}%
															</span>{" "}
															WR
														</div>
														<div className="flex items-center gap-1">
															<span className="text-white/80 font-bold">
																{entry.meta_data?.trades}
															</span>{" "}
															T
														</div>
													</div>
												</TableCell>
												<TableCell className="hidden sm:table-cell text-center">
													<Badge
														variant="outline"
														className="bg-cyan/10 border-cyan/20 text-cyan font-mono text-[10px] uppercase tracking-wider"
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
																			className="h-8 w-8 text-rose-400 opacity-0 group-hover:opacity-100 transition-opacity hover:bg-rose-500/10 hover:text-rose-300 rounded-lg"
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
																	<TooltipContent className="bg-[#0c0d12] border-white/10 text-white text-xs">
																		Remove from leaderboard
																	</TooltipContent>
																</Tooltip>
															)}

															<Tooltip>
																<TooltipTrigger asChild>
																	<Button
																		variant="ghost"
																		size="icon"
																		className="h-8 w-8 text-white/60 hover:text-white opacity-0 group-hover:opacity-100 transition-opacity hover:bg-white/10 rounded-lg"
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
																<TooltipContent className="bg-[#0c0d12] border-white/10 text-white text-xs">
																	{t("table.viewReport")}
																</TooltipContent>
															</Tooltip>

															<Tooltip>
																<TooltipTrigger asChild>
																	<Button
																		variant="ghost"
																		size="sm"
																		className="h-8 px-2.5 text-[11px] font-semibold gap-1.5 hidden md:flex border border-white/10 bg-white/[0.04] text-white/80 hover:bg-cyan/10 hover:border-cyan/30 hover:text-cyan transition-all rounded-lg"
																		disabled={!entry.isConfigPublic}
																		asChild={entry.isConfigPublic}
																	>
																		{entry.isConfigPublic ? (
																			<a
																				href={`/s/${entry.sharedBacktestSlug}#config`}
																				target="_blank"
																				rel="noopener noreferrer"
																			>
																				<Copy className="h-3.5 w-3.5 text-cyan" />
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
																	<TooltipContent className="bg-[#0c0d12] border-white/10 text-white text-xs">
																		Private strategy
																	</TooltipContent>
																)}
															</Tooltip>

															<Button
																variant="ghost"
																size="icon"
																className="h-8 w-8 text-white/40 hover:text-white md:hidden"
															>
																<ChevronRight className="h-4 w-4" />
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
												className="h-[200px] text-center text-white/40"
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
				</div>

				{/* Footer info */}
				<div className="flex flex-col sm:flex-row justify-between items-center gap-4 text-xs text-white/40 mt-4 px-1 font-mono">
					<div className="flex items-center gap-4">
						<div className="flex items-center gap-1.5">
							<Clock className="h-3.5 w-3.5 text-white/50" />
							Updated 5m ago
						</div>
						<div className="flex items-center gap-1.5">
							<Users className="h-3.5 w-3.5 text-white/50" />
							{leaderboard?.length || 0} Traders Competing
						</div>
					</div>
					<p className="text-white/30">Publish your backtest to join the leaderboard!</p>
				</div>
			</div>
		</PageLayout>
	);
};

export default LeaderboardPage;
