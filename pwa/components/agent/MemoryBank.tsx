import type React from "react";
import { useEffect, useState } from "react";
import { api } from "../../services/api";
import type { AgentMemory } from "../../types";
import { Brain, RefreshCw, Eye, EyeOff, Trash2, Sparkles } from "lucide-react";
import ReactMarkdown from "react-markdown";

interface MemoryBankProps {
	isAutopilotRunning?: boolean;
	activeIteration?: number;
}

export const MemoryBank: React.FC<MemoryBankProps> = ({ isAutopilotRunning, activeIteration }) => {
	const [memories, setMemories] = useState<AgentMemory[]>([]);
	const [isLoading, setIsLoading] = useState(false);
	const [isClearing, setIsClearing] = useState(false);
	const [isDeduplicating, setIsDeduplicating] = useState(false);
	const [showMemories, setShowMemories] = useState(true);

	const fetchMemories = async () => {
		setIsLoading(true);
		try {
			const data = await api.getAgentMemories();
			setMemories(data || []);
		} catch (e) {
			console.error("Failed to load agent memories", e);
		} finally {
			setIsLoading(false);
		}
	};

	const handleClearMemories = async () => {
		if (!confirm("Are you sure you want to clear the agent's memory bank?")) return;
		setIsClearing(true);
		try {
			await api.deleteAgentMemories();
			setMemories([]);
		} catch (e) {
			console.error("Failed to clear agent memories", e);
		} finally {
			setIsClearing(false);
		}
	};

	const handleDeduplicateMemories = async () => {
		if (!confirm("Are you sure you want to reorganize and deduplicate the memory bank? This will merge highly similar insights.")) return;
		setIsDeduplicating(true);
		try {
			const res = await api.deduplicateAgentMemories();
			alert(`Successfully reorganized memories! Merged ${res.deleted_count} duplicate insights.`);
			void fetchMemories();
		} catch (e) {
			console.error("Failed to deduplicate agent memories", e);
		} finally {
			setIsDeduplicating(false);
		}
	};

	const handleDeleteMemory = async (memoryId: string) => {
		if (!confirm("Are you sure you want to delete this memory?")) return;
		try {
			await api.deleteAgentMemory(memoryId);
			setMemories((prev) => prev.filter((m) => m.id !== memoryId));
		} catch (e) {
			console.error("Failed to delete agent memory", e);
		}
	};

	useEffect(() => {
		let active = true;
		const load = async () => {
			await Promise.resolve();
			if (!active) return;
			void fetchMemories();
		};
		void load();
		return () => {
			active = false;
		};
	}, []);

	// Refetch memories when autopilot finishes an iteration (since new insights are generated)
	useEffect(() => {
		let active = true;
		if (isAutopilotRunning && activeIteration && activeIteration > 1) {
			const load = async () => {
				await Promise.resolve();
				if (!active) return;
				void fetchMemories();
			};
			void load();
		}
		return () => {
			active = false;
		};
	}, [isAutopilotRunning, activeIteration]);

	const [selectedTag, setSelectedTag] = useState<string | null>(null);

	// Extract unique tags
	const allTags = Array.from(
		new Set(
			(memories || []).flatMap((m) => {
				const tags = m.tags || [];
				const list = [...tags];
				if (m.symbol) list.push(m.symbol);
				if (m.strategy_type) list.push(m.strategy_type);
				return list;
			}).filter(Boolean)
		)
	);

	const filteredMemories = selectedTag
		? (memories || []).filter((m) => {
				const mTags = m.tags || [];
				return (
					mTags.includes(selectedTag) ||
					m.symbol === selectedTag ||
					m.strategy_type === selectedTag
				);
		  })
		: memories;

	return (
		<div className="flex flex-col h-full bg-slate-900/50 backdrop-blur-md border border-slate-800 rounded-2xl overflow-hidden p-4 shadow-xl">
			<div className="flex items-center justify-between border-b border-slate-800 pb-3 mb-3">
				<div className="flex items-center gap-2">
					<Brain className={`w-5 h-5 text-indigo-400 ${isAutopilotRunning ? "animate-pulse" : ""}`} />
					<h3 className="font-semibold text-slate-200 text-sm">Agent Memory Bank</h3>
				</div>
				<div className="flex items-center gap-1">
					<button
						onClick={() => setShowMemories(!showMemories)}
						className="p-1 hover:bg-slate-800 rounded text-slate-400 transition"
						title={showMemories ? "Hide Memories" : "Show Memories"}
						type="button"
					>
						{showMemories ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
					</button>
					<button
						onClick={fetchMemories}
						disabled={isLoading}
						className="p-1 hover:bg-slate-800 rounded text-slate-400 transition disabled:opacity-50"
						title="Refresh Memories"
						type="button"
					>
						<RefreshCw className={`w-4 h-4 ${isLoading ? "animate-spin" : ""}`} />
					</button>
					<button
						onClick={handleDeduplicateMemories}
						disabled={isLoading || isDeduplicating}
						className="p-1 hover:bg-slate-800 hover:text-amber-455 rounded text-slate-400 transition disabled:opacity-50"
						title="Reorganize Memory Bank"
						type="button"
					>
						<Sparkles className={`w-4 h-4 ${isDeduplicating ? "animate-pulse" : ""}`} />
					</button>
					<button
						onClick={handleClearMemories}
						disabled={isLoading || isClearing}
						className="p-1 hover:bg-slate-800 hover:text-rose-400 rounded text-slate-400 transition disabled:opacity-50"
						title="Clear Memories"
						type="button"
					>
						<Trash2 className="w-4 h-4" />
					</button>
				</div>
			</div>

			{showMemories && allTags.length > 0 && (
				<div className="flex gap-1.5 overflow-x-auto pb-2.5 mb-2.5 scrollbar-thin scrollbar-thumb-slate-800 scrollbar-track-transparent">
					<button
						onClick={() => setSelectedTag(null)}
						className={`text-[10px] font-medium px-2 py-0.5 rounded-full transition whitespace-nowrap ${
							!selectedTag
								? "bg-indigo-500 text-white shadow-lg shadow-indigo-500/10"
								: "bg-slate-800 text-slate-400 hover:bg-slate-750 hover:text-slate-300"
						}`}
					>
						All
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
						>
							{tag}
						</button>
					))}
				</div>
			)}

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
						{selectedTag ? "No memories match the selected tag filter." : "No memories formed yet. Launch a backtest or optimize a strategy to generate experience insights."}
					</div>
				) : (
					filteredMemories.map((memory) => {
						const isNew = isAutopilotRunning && memory.content.includes("failed") && activeIteration;
						
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
									} else if (parsed.config_data && parsed.config_data.reasoning) {
										extractedReasoning = parsed.config_data.reasoning;
									}
								}
							} catch (e) {
								prettyConfig = configStr;
							}
						}

						// Determine coloring based on memory type
						let cardStyles = "bg-slate-950/40 border-slate-800/80 hover:border-slate-700";
						let badgeStyles = "bg-slate-500/10 text-slate-400 border border-slate-500/20";
						
						if (memory.memory_type === "rule") {
							cardStyles = "bg-rose-950/10 border-rose-900/30 hover:border-rose-800/50 shadow-rose-950/5";
							badgeStyles = "bg-rose-500/15 text-rose-400 border border-rose-500/30 font-semibold";
						} else if (memory.memory_type === "strategy_insight") {
							cardStyles = "bg-amber-950/5 border-amber-900/20 hover:border-amber-800/40";
							badgeStyles = "bg-amber-500/10 text-amber-400 border border-amber-500/20";
						} else if (memory.memory_type === "optimization") {
							cardStyles = "bg-indigo-950/10 border-indigo-900/30 hover:border-indigo-850";
							badgeStyles = "bg-indigo-500/15 text-indigo-400 border border-indigo-500/20";
						} else if (memory.memory_type === "observation") {
							cardStyles = "bg-emerald-950/5 border-emerald-900/20 hover:border-emerald-800/40";
							badgeStyles = "bg-emerald-500/10 text-emerald-400 border border-emerald-500/20";
						}

						return (
							<div
								key={memory.id}
								className={`group relative border ${
									isNew ? "border-indigo-500/40 animate-pulse shadow-indigo-500/5" : ""
								} ${cardStyles} rounded-xl p-3.5 transition-all duration-300 shadow-sm`}
							>
								<div className="flex items-center justify-between mb-2">
									<div className="flex items-center gap-1.5">
										<span className={`text-[9px] uppercase tracking-wider font-semibold px-2 py-0.5 rounded-full ${badgeStyles}`}>
											{memory.memory_type.replace("_", " ")}
										</span>
										{memory.outcome && (
											<span className={`text-[9px] font-semibold uppercase px-1.5 py-0.5 rounded ${
												memory.outcome === "success" ? "bg-emerald-500/10 text-emerald-400 border border-emerald-500/20" : "bg-rose-500/10 text-rose-400 border border-rose-500/20"
											}`}>
												{memory.outcome}
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

								<div className="absolute top-2 right-2 opacity-0 group-hover:opacity-100 transition flex items-center gap-1.5 bg-slate-900/90 px-2 py-0.5 rounded border border-slate-850 shadow-md">
									<span className="text-[9px] text-slate-400 font-mono">
										Rel: {(memory.relevance_score * 100).toFixed(0)}%
									</span>
									<button
										onClick={(e) => {
											e.stopPropagation();
											void handleDeleteMemory(memory.id);
										}}
										className="text-slate-500 hover:text-rose-400 p-0.5 rounded hover:bg-slate-800 transition"
										title="Delete memory"
										type="button"
									>
										<Trash2 className="w-3.5 h-3.5" />
									</button>
								</div>
							</div>
						);
					})
				)}
			</div>
		</div>
	);
};
