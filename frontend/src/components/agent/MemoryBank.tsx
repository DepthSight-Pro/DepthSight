import type React from "react";
import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import {
	Brain,
	RefreshCw,
	Eye,
	EyeOff,
	Trash2,
	Sparkles,
	Globe,
	Info,
	ShieldCheck,
	CheckCircle2,
	X,
	Share2,
} from "lucide-react";
import {
	useGetAgentMemories,
	useDeleteAgentMemories,
	useDeleteAgentMemory,
	useDeduplicateAgentMemories,
	useUpdateCommunityMemorySharing,
	useShareAgentMemory,
} from "@/lib/api";
import { toast } from "sonner";
import { useAuth } from "@/context/AuthContext";
import { useTranslation } from "react-i18next";
import ReactMarkdown from "react-markdown";

interface MemoryBankProps {
	isAutopilotRunning?: boolean;
	activeIteration?: number;
}

export const MemoryBank: React.FC<MemoryBankProps> = ({
	isAutopilotRunning,
	activeIteration,
}) => {
	const { t } = useTranslation("common");
	const { user, updateUser } = useAuth();
	const { data: memories = [], isLoading, refetch } = useGetAgentMemories();
	const deleteMemories = useDeleteAgentMemories();
	const deleteMemory = useDeleteAgentMemory();
	const deduplicateMemories = useDeduplicateAgentMemories();
	const updateCommunitySharing = useUpdateCommunityMemorySharing();
	const shareMemory = useShareAgentMemory();

	const [showMemories, setShowMemories] = useState(true);
	const [selectedTag, setSelectedTag] = useState<string | null>(null);
	const [scopeFilter, setScopeFilter] = useState<"all" | "private" | "community">("all");
	const isUserOptedIn = Boolean(
		(user as any)?.shareCommunityMemories ||
		(user as any)?.share_community_memories
	);
	const [isCommunityOptIn, setIsCommunityOptIn] = useState(isUserOptedIn);
	const [showOnboardingModal, setShowOnboardingModal] = useState(false);

	// Sync local opt-in toggle when user profile changes
	useEffect(() => {
		if (user) {
			setIsCommunityOptIn(
				Boolean(
					(user as any)?.shareCommunityMemories ||
					(user as any)?.share_community_memories
				)
			);
		}
	}, [
		(user as any)?.shareCommunityMemories,
		(user as any)?.share_community_memories,
	]);

	// Auto-trigger onboarding popup on first visit if not yet opted in and never seen
	useEffect(() => {
		const seen = localStorage.getItem("depthsight_community_memory_modal_seen");
		if (!seen && !isUserOptedIn) {
			setShowOnboardingModal(true);
		}
	}, [isUserOptedIn]);

	// Refetch memories when autopilot finishes an iteration
	useEffect(() => {
		if (isAutopilotRunning && activeIteration && activeIteration > 1) {
			void refetch();
		}
	}, [isAutopilotRunning, activeIteration, refetch]);

	const handleToggleCommunity = (enabled: boolean) => {
		setIsCommunityOptIn(enabled);
		if (updateUser) {
			updateUser({
				shareCommunityMemories: enabled,
				...({ share_community_memories: enabled } as any),
			});
		}
		updateCommunitySharing.mutate(enabled, {
			onSuccess: (data) => {
				if (enabled && data.promoted_count && data.promoted_count > 0) {
					toast.success(
						t(
							"communityMemory.retroactiveSuccess",
							"Community pool enabled! {{count}} verified strategies shared.",
							{ count: data.promoted_count }
						)
					);
				}
				void refetch();
			},
			onError: (err: any) => {
				toast.error(err?.message || "Failed to update community sharing");
				setIsCommunityOptIn(!enabled);
				if (updateUser) {
					updateUser({
						shareCommunityMemories: !enabled,
						...({ share_community_memories: !enabled } as any),
					});
				}
			},
		});
	};

	const handleModalAccept = () => {
		localStorage.setItem("depthsight_community_memory_modal_seen", "true");
		setShowOnboardingModal(false);
		handleToggleCommunity(true);
	};

	const handleModalDecline = () => {
		localStorage.setItem("depthsight_community_memory_modal_seen", "true");
		setShowOnboardingModal(false);
	};

	// Extract unique tags
	const allTags = Array.from(
		new Set(
			memories.flatMap((m) => {
				const tags = m.tags || [];
				const list = [...tags];
				if (m.symbol) list.push(m.symbol);
				if (m.strategy_type) list.push(m.strategy_type);
				return list;
			}).filter(Boolean)
		)
	);

	const filteredMemories = memories.filter((m) => {
		if (scopeFilter === "private" && m.visibility === "community") return false;
		if (scopeFilter === "community" && m.visibility !== "community") return false;
		if (selectedTag) {
			const mTags = m.tags || [];
			return (
				mTags.includes(selectedTag) ||
				m.symbol === selectedTag ||
				m.strategy_type === selectedTag
			);
		}
		return true;
	});

	const communityCount = memories.filter(
		(m) => m.visibility === "community"
	).length;

	return (
		<div className="flex flex-col h-full bg-slate-900/50 backdrop-blur-md border border-slate-800 rounded-2xl overflow-hidden p-4 shadow-xl relative">
			{/* Top Header */}
			<div className="flex items-center justify-between border-b border-slate-800 pb-3 mb-3">
				<div className="flex items-center gap-2">
					<Brain
						className={`w-5 h-5 text-indigo-400 ${
							isAutopilotRunning ? "animate-pulse" : ""
						}`}
					/>
					<h3 className="font-semibold text-slate-200 text-sm">
						{t("communityMemory.title", "Agent Memory Bank")}
					</h3>
				</div>
				<div className="flex items-center gap-1">
					<button
						onClick={() => setShowMemories(!showMemories)}
						className="p-1 hover:bg-slate-800 rounded text-slate-400 transition"
						title={showMemories ? "Hide Memories" : "Show Memories"}
						type="button"
					>
						{showMemories ? (
							<EyeOff className="w-4 h-4" />
						) : (
							<Eye className="w-4 h-4" />
						)}
					</button>
					<button
						onClick={() => void refetch()}
						disabled={isLoading}
						className="p-1 hover:bg-slate-800 rounded text-slate-400 transition disabled:opacity-50"
						title="Refresh Memories"
						type="button"
					>
						<RefreshCw
							className={`w-4 h-4 ${isLoading ? "animate-spin" : ""}`}
						/>
					</button>
					<button
						onClick={() => {
							if (
								confirm(
									"Are you sure you want to reorganize and deduplicate the memory bank? This will merge highly similar insights."
								)
							) {
								deduplicateMemories.mutate(undefined, {
									onSuccess: (data) => {
										alert(
											`Successfully reorganized memories! Merged ${data.deleted_count} duplicate insights.`
										);
									},
								});
							}
						}}
						disabled={deduplicateMemories.isPending}
						className="p-1 hover:bg-slate-800 hover:text-amber-450 rounded text-slate-400 transition disabled:opacity-50"
						title="Reorganize Memory Bank"
						type="button"
					>
						<Sparkles
							className={`w-4 h-4 ${
								deduplicateMemories.isPending ? "animate-pulse" : ""
							}`}
						/>
					</button>
					<button
						onClick={() => {
							if (
								confirm(
									"Are you sure you want to clear your private agent memories? Community memories are safely preserved."
								)
							) {
								deleteMemories.mutate();
							}
						}}
						disabled={deleteMemories.isPending}
						className="p-1 hover:bg-slate-800 hover:text-rose-400 rounded text-slate-400 transition disabled:opacity-50"
						title="Clear Private Memories"
						type="button"
					>
						<Trash2 className="w-4 h-4" />
					</button>
				</div>
			</div>

			{/* Prominent Opt-In Barter Banner / Switch */}
			<div className="mb-3 p-2.5 rounded-xl border border-indigo-500/25 bg-gradient-to-r from-indigo-950/50 via-slate-900 to-indigo-950/30 flex items-center justify-between gap-3 shadow-inner">
				<div className="flex items-center gap-2 min-w-0">
					<div
						className={`p-1.5 rounded-lg transition-colors ${
							isCommunityOptIn
								? "bg-indigo-500/20 text-indigo-400 shadow-sm shadow-indigo-500/20"
								: "bg-slate-800 text-slate-500"
						}`}
					>
						<Globe className="w-4 h-4" />
					</div>
					<div className="min-w-0">
						<div className="flex items-center gap-1.5">
							<span className="text-xs font-medium text-slate-200 truncate">
								{t("communityMemory.communityPool", "Community Pool")}
							</span>
							<button
								type="button"
								onClick={() => setShowOnboardingModal(true)}
								className="text-slate-400 hover:text-indigo-300 transition"
								title={t(
									"communityMemory.optInTooltip",
									"About Community Memory"
								)}
							>
								<Info className="w-3.5 h-3.5" />
							</button>
						</div>
						<p className="text-[10px] text-slate-400 truncate">
							{isCommunityOptIn
								? `Swarm active (${communityCount} community insights)`
								: "Local-only memory"}
						</p>
					</div>
				</div>

				<label className="relative inline-flex items-center cursor-pointer shrink-0">
					<input
						type="checkbox"
						checked={isCommunityOptIn}
						disabled={updateCommunitySharing.isPending}
						onChange={(e) => handleToggleCommunity(e.target.checked)}
						className="sr-only peer"
					/>
					<div className="w-9 h-5 bg-slate-800 peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-slate-300 after:border after:rounded-full after:h-4 after:w-4 after:transition-all peer-checked:bg-indigo-600"></div>
				</label>
			</div>

			{/* Filter Tabs (All / Private / Community) & Tag Chips */}
			{showMemories && (
				<div className="space-y-2 pb-2.5 mb-2.5 border-b border-slate-800/60">
					{/* Scope Selector */}
					<div className="flex gap-1 bg-slate-950/60 p-1 rounded-lg border border-slate-800 text-[10px]">
						<button
							onClick={() => setScopeFilter("all")}
							type="button"
							className={`flex-1 py-1 rounded transition text-center font-medium ${
								scopeFilter === "all"
									? "bg-indigo-600 text-white shadow-sm"
									: "text-slate-400 hover:text-slate-200"
							}`}
						>
							{t("communityMemory.all", "All")} ({memories.length})
						</button>
						<button
							onClick={() => setScopeFilter("private")}
							type="button"
							className={`flex-1 py-1 rounded transition text-center font-medium ${
								scopeFilter === "private"
									? "bg-indigo-600 text-white shadow-sm"
									: "text-slate-400 hover:text-slate-200"
							}`}
						>
							{t("communityMemory.myMemories", "My Memories")} (
							{memories.length - communityCount})
						</button>
						<button
							onClick={() => setScopeFilter("community")}
							type="button"
							className={`flex-1 py-1 rounded transition text-center font-medium flex items-center justify-center gap-1 ${
								scopeFilter === "community"
									? "bg-indigo-600 text-white shadow-sm"
									: "text-slate-400 hover:text-slate-200"
							}`}
						>
							<Globe className="w-3 h-3" />
							{t("communityMemory.community", "Community")} (
							{communityCount})
						</button>
					</div>

					{/* Tag Chips */}
					{allTags.length > 0 && (
						<div className="flex gap-1.5 overflow-x-auto pb-1 scrollbar-thin scrollbar-thumb-slate-800 scrollbar-track-transparent">
							<button
								onClick={() => setSelectedTag(null)}
								className={`text-[10px] font-medium px-2 py-0.5 rounded-full transition whitespace-nowrap ${
									!selectedTag
										? "bg-indigo-500/30 text-indigo-200 border border-indigo-500/40"
										: "bg-slate-800 text-slate-400 hover:bg-slate-750 hover:text-slate-300"
								}`}
								type="button"
							>
								Tags: All
							</button>
							{allTags.map((tag) => (
								<button
									key={tag}
									onClick={() => setSelectedTag(tag)}
									className={`text-[10px] font-medium px-2.5 py-0.5 rounded-full transition whitespace-nowrap ${
										selectedTag === tag
											? "bg-indigo-600 text-white shadow-md shadow-indigo-500/10 border border-indigo-500/30"
											: "bg-slate-800/80 text-slate-400 hover:bg-slate-750 hover:text-slate-300 border border-slate-700/50"
									}`}
									type="button"
								>
									{tag}
								</button>
							))}
						</div>
					)}
				</div>
			)}

			{/* Memories List */}
			<div className="flex-1 overflow-y-auto pr-1 space-y-2.5">
				{isLoading && memories.length === 0 ? (
					<div className="flex flex-col items-center justify-center h-32 gap-2">
						<Brain className="w-8 h-8 text-indigo-500/50 animate-bounce" />
						<span className="text-xs text-slate-500">Accessing synapses...</span>
					</div>
				) : !showMemories ? (
					<div className="flex flex-col items-center justify-center h-32 gap-2 text-slate-500">
						<span className="text-xs">Memories encrypted</span>
					</div>
				) : filteredMemories.length === 0 ? (
					<div className="text-center py-8 text-xs text-slate-500">
						{selectedTag || scopeFilter !== "all"
							? "No memories match the active filters."
							: "No memories formed yet. Launch a backtest or optimize a strategy to generate experience insights."}
					</div>
				) : (
					filteredMemories.map((memory) => {
						const isNew =
							isAutopilotRunning &&
							memory.content.includes("failed") &&
							activeIteration;
						const isCommunity = memory.visibility === "community";

						// Parse the content
						const content = memory.content;
						const reasoningIndex = content.indexOf(". Reasoning: ");
						const configIndex = content.indexOf(". Config: ");

						let summary = content;
						let reasoning = "";
						let configStr = "";
						let hasConfig = false;

						if (reasoningIndex !== -1 && configIndex !== -1) {
							summary = content.substring(0, reasoningIndex + 1);
							reasoning = content.substring(reasoningIndex + 13, configIndex);
							configStr = content.substring(configIndex + 10);
							hasConfig = true;
						} else if (configIndex !== -1) {
							summary = content.substring(0, configIndex + 1);
							configStr = content.substring(configIndex + 10);
							hasConfig = true;
						} else if (reasoningIndex !== -1) {
							summary = content.substring(0, reasoningIndex + 1);
							reasoning = content.substring(reasoningIndex + 13);
						}

						let prettyConfig = configStr;
						let extractedReasoning = reasoning;
						if (hasConfig) {
							try {
								const jsonStr = configStr
									.replace(/'/g, '"')
									.replace(/True/g, "true")
									.replace(/False/g, "false")
									.replace(/None/g, "null");
								const parsed = JSON.parse(jsonStr);
								prettyConfig = JSON.stringify(parsed, null, 2);

								if (!reasoning && parsed) {
									if (parsed.reasoning) {
										extractedReasoning = parsed.reasoning;
									} else if (
										parsed.config_data &&
										parsed.config_data.reasoning
									) {
										extractedReasoning = parsed.config_data.reasoning;
									}
								}
							} catch (e) {
								prettyConfig = configStr;
							}
						}

						// Determine coloring based on memory type & community status
						let cardStyles =
							"bg-slate-950/40 border-slate-800/80 hover:border-slate-700";
						let badgeStyles =
							"bg-slate-500/10 text-slate-400 border border-slate-500/20";

						if (isCommunity) {
							cardStyles =
								"bg-indigo-950/20 border-indigo-500/30 hover:border-indigo-500/50 shadow-sm shadow-indigo-950/10";
						} else if (memory.memory_type === "rule") {
							cardStyles =
								"bg-rose-950/10 border-rose-900/30 hover:border-rose-800/50 shadow-rose-950/5";
							badgeStyles =
								"bg-rose-500/15 text-rose-400 border border-rose-500/30 font-semibold";
						} else if (memory.memory_type === "strategy_insight") {
							cardStyles =
								"bg-amber-950/5 border-amber-900/20 hover:border-amber-800/40";
							badgeStyles =
								"bg-amber-500/10 text-amber-400 border border-amber-500/20";
						} else if (memory.memory_type === "optimization") {
							cardStyles =
								"bg-indigo-950/10 border-indigo-900/30 hover:border-indigo-850";
							badgeStyles =
								"bg-indigo-500/15 text-indigo-400 border border-indigo-500/20";
						} else if (memory.memory_type === "observation") {
							cardStyles =
								"bg-emerald-950/5 border-emerald-900/20 hover:border-emerald-800/40";
							badgeStyles =
								"bg-emerald-500/10 text-emerald-400 border border-emerald-500/20";
						}

						return (
							<div
								key={memory.id}
								className={`group relative border ${
									isNew
										? "border-indigo-500/40 animate-pulse shadow-indigo-500/5"
										: ""
								} ${cardStyles} rounded-xl p-3.5 transition-all duration-300 shadow-sm`}
							>
								<div className="flex items-center justify-between mb-2">
									<div className="flex items-center gap-1.5 flex-wrap">
										{/* Community Icon & Badge */}
										{isCommunity && (
											<span
												className="text-[9px] font-semibold uppercase px-2 py-0.5 rounded-full bg-indigo-500/20 text-indigo-300 border border-indigo-500/40 flex items-center gap-1 shadow-sm"
												title="Community Insight (Decentralized Pool)"
											>
												<Globe className="w-2.5 h-2.5" />
												<span>Community</span>
											</span>
										)}

										<span
											className={`text-[9px] uppercase tracking-wider font-semibold px-2 py-0.5 rounded-full ${badgeStyles}`}
										>
											{memory.memory_type.replace("_", " ")}
										</span>

										{memory.outcome && (
											<span
												className={`text-[9px] font-semibold uppercase px-1.5 py-0.5 rounded ${
													memory.outcome === "success"
														? "bg-emerald-500/10 text-emerald-400 border border-emerald-500/20"
														: "bg-rose-500/10 text-rose-400 border border-rose-500/20"
												}`}
											>
												{memory.outcome}
											</span>
										)}

										{isCommunity &&
											memory.community_confirmations &&
											memory.community_confirmations > 1 && (
												<span className="text-[9px] text-cyan-400 font-mono bg-cyan-950/40 px-1.5 py-0.5 rounded border border-cyan-500/20">
													{t("communityMemory.confirmedCount", {
														count: memory.community_confirmations,
													})}
												</span>
											)}

										{memory.confidence && memory.confidence < 1.0 && (
											<span className="text-[9px] text-slate-400 font-mono">
												conf: {Math.round(memory.confidence * 100)}%
											</span>
										)}
									</div>
									<span className="text-[10px] text-slate-500 font-medium">
										{new Date(memory.created_at).toLocaleDateString()}
									</span>
								</div>

								<div className="text-xs text-slate-300 leading-relaxed font-light space-y-2">
									<p className="font-semibold text-slate-100">{summary}</p>
									{extractedReasoning && (
										<div className="text-slate-300 border-l-2 border-indigo-500/30 pl-2.5 py-0.5 text-[11px] prose prose-invert prose-xs leading-normal">
											<ReactMarkdown>{extractedReasoning}</ReactMarkdown>
										</div>
									)}
									{hasConfig && (
										<details className="mt-2 text-[10px] text-slate-400 bg-slate-950/80 rounded-lg border border-slate-850 p-2 font-mono cursor-pointer">
											<summary className="hover:text-slate-200 transition select-none font-sans font-medium text-[9px] uppercase tracking-wider text-slate-500">
												View Config JSON
											</summary>
											<pre className="mt-2 overflow-x-auto whitespace-pre-wrap max-h-40 text-indigo-300/90 text-[10px] leading-tight">
												{prettyConfig}
											</pre>
										</details>
									)}
								</div>

								{/* Card Action Controls */}
								<div className="absolute top-2 right-2 opacity-0 group-hover:opacity-100 transition flex items-center gap-1.5 bg-slate-900/90 px-2 py-0.5 rounded border border-slate-850 shadow-md">
									<span className="text-[9px] text-slate-400 font-mono">
										Rel: {(memory.relevance_score * 100).toFixed(0)}%
									</span>
									{isCommunity ? (
										<span
											className="text-indigo-400/80 p-0.5"
											title={t(
												"communityMemory.cannotDeleteCommunity",
												"Community memories are preserved in the shared pool."
											)}
										>
											<Globe className="w-3.5 h-3.5" />
										</span>
									) : (
										<>
											<button
												onClick={(e) => {
													e.stopPropagation();
													shareMemory.mutate(memory.id, {
														onSuccess: () => {
															toast.success(
																t(
																	"communityMemory.shareSuccess",
																	"Memory successfully shared to Community pool!"
																)
															);
															void refetch();
														},
														onError: (err: any) => {
															toast.error(
																err?.message ||
																	t(
																		"communityMemory.shareError",
																		"Could not share memory with community"
																	)
															);
														},
													});
												}}
												disabled={shareMemory.isPending}
												className="text-slate-500 hover:text-indigo-400 p-0.5 rounded hover:bg-slate-800 transition disabled:opacity-50"
												title={t(
													"communityMemory.shareWithCommunity",
													"Share with Community (requires >= 30 trades)"
												)}
												type="button"
											>
												<Share2 className="w-3.5 h-3.5" />
											</button>

											<button
												onClick={(e) => {
													e.stopPropagation();
													if (
														confirm(
															"Are you sure you want to delete this memory?"
														)
													) {
														deleteMemory.mutate(memory.id);
													}
												}}
												disabled={deleteMemory.isPending}
												className="text-slate-500 hover:text-rose-400 p-0.5 rounded hover:bg-slate-800 transition disabled:opacity-50"
												title="Delete memory"
												type="button"
											>
												<Trash2 className="w-3.5 h-3.5" />
											</button>
										</>
									)}
								</div>
							</div>
						);
					})
				)}
			</div>

			{/* First-Time Onboarding Modal */}
			{showOnboardingModal &&
				typeof document !== "undefined" &&
				createPortal(
					<div className="fixed inset-0 z-[9999] flex items-center justify-center p-3 sm:p-4 bg-slate-950/85 backdrop-blur-sm overflow-y-auto animate-in fade-in duration-200">
						<div
							className="fixed inset-0"
							onClick={handleModalDecline}
						/>
						<div className="relative z-10 bg-slate-900 border border-indigo-500/30 rounded-2xl p-4 sm:p-6 max-w-lg w-full shadow-2xl relative max-h-[85dvh] sm:max-h-[85vh] flex flex-col my-auto">
							<button
								onClick={handleModalDecline}
								className="absolute top-4 right-4 text-slate-400 hover:text-slate-200 p-1.5 rounded-lg hover:bg-slate-800 transition z-10"
								type="button"
							>
								<X className="w-5 h-5" />
							</button>

							<div className="flex items-center gap-3.5 pr-8 shrink-0 pb-2">
								<div className="p-3 bg-indigo-500/20 text-indigo-400 rounded-xl shadow-inner border border-indigo-500/30 shrink-0">
									<Globe className="w-7 h-7 animate-pulse" />
								</div>
								<div className="min-w-0">
									<h3 className="text-base font-semibold text-white leading-tight">
										{t(
											"communityMemory.modalTitle",
											"DepthSight Community Memory Pool"
										)}
									</h3>
									<p className="text-xs text-indigo-400 mt-0.5">
										{t(
											"communityMemory.modalSubtitle",
											"Decentralized Swarm Intelligence for Trading Agents"
										)}
									</p>
								</div>
							</div>

							<div className="flex-1 min-h-0 overflow-y-auto space-y-3 pr-1 py-1 text-xs text-slate-300 scrollbar-thin">
								<p className="leading-relaxed text-xs">
									{t(
										"communityMemory.modalDesc",
										"Participate in the shared trading intelligence pool by barter. When you run profitable backtests (≥30 trades, ≥28 days), generalized market insights are anonymously shared with the network. In return, your agent taps into verified setups and universal rules discovered by traders worldwide."
									)}
								</p>

								<div className="bg-slate-950/60 rounded-xl p-3.5 border border-slate-800 space-y-2.5 text-xs text-slate-300">
									<div className="flex items-start gap-2.5">
										<ShieldCheck className="w-4 h-4 text-emerald-400 shrink-0 mt-0.5" />
										<span className="leading-snug">
											{t(
												"communityMemory.modalPrivacy",
												"Privacy Guarantee: Strategy parameters, confidential configurations, and API keys are strictly removed. Only high-level market lessons and performance statistics are contributed."
											)}
										</span>
									</div>
									<div className="flex items-start gap-2.5">
										<CheckCircle2 className="w-4 h-4 text-indigo-400 shrink-0 mt-0.5" />
										<span className="leading-snug">
											{t(
												"communityMemory.modalQuality",
												"Quality Gate: Only verified profitable strategies with ≥30 trades and ≥28 days backtest duration enter the network pool."
											)}
										</span>
									</div>
									<div className="flex items-start gap-2.5">
										<Share2 className="w-4 h-4 text-indigo-400 shrink-0 mt-0.5" />
										<span className="leading-snug">
											{t(
												"communityMemory.modalTransfer",
												"Cross-Asset Transfer: Learn from BTC, ETH, and altcoin patterns even on assets you haven't traded yet."
											)}
										</span>
									</div>
								</div>
							</div>

							<div className="flex flex-col sm:flex-row items-stretch sm:items-center justify-end gap-2.5 pt-3 mt-2 border-t border-slate-800/80 shrink-0">
								<button
									type="button"
									onClick={handleModalDecline}
									className="w-full sm:w-auto px-4 py-2.5 rounded-xl text-xs font-medium text-slate-400 hover:text-slate-200 hover:bg-slate-800 transition text-center"
								>
									{t("communityMemory.modalLater", "Keep Private Only")}
								</button>
								<button
									type="button"
									onClick={handleModalAccept}
									className="w-full sm:w-auto px-5 py-2.5 rounded-xl text-xs font-semibold bg-indigo-600 hover:bg-indigo-500 text-white shadow-lg shadow-indigo-600/25 transition flex items-center justify-center gap-1.5"
								>
									<Globe className="w-4 h-4 shrink-0" />
									<span>
										{t("communityMemory.modalJoin", "Join Community Pool")}
									</span>
								</button>
							</div>
						</div>
					</div>,
					document.body
				)}
		</div>
	);
};
