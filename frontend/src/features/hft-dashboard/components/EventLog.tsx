// src/features/hft-dashboard/components/EventLog.tsx

import { format } from "date-fns";
import { Pause, Play, Terminal, Trash2 } from "lucide-react";
import type React from "react";
import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useHftStore } from "../hooks/useHftStore";
import type { HftLogEvent } from "../types/hft.types";

export const EventLog: React.FC = () => {
	const { logs } = useHftStore();
	const [isPaused, setIsPaused] = useState(false);
	const [frozenLogs, setFrozenLogs] = useState<HftLogEvent[]>([]);
	const scrollContainerRef = useRef<HTMLDivElement>(null);

	const handlePauseToggle = () => {
		if (!isPaused) {
			setFrozenLogs(logs);
		}
		setIsPaused(!isPaused);
	};

	// Auto-scroll to bottom on new logs (only if not paused)
	useEffect(() => {
		if (scrollContainerRef.current && !isPaused) {
			scrollContainerRef.current.scrollTop =
				scrollContainerRef.current.scrollHeight;
		}
	}, [isPaused]);

	const formatLogMessage = (rawMessage: string) => {
		if (!rawMessage) return null;

		// 1. Garbage cleanup [HEARTBEAT ...]
		const message = rawMessage.replace(/\[HEARTBEAT .*?\]\s*/g, "").trim();

		// 2. Extracting message parts
		const parts = message.split(
			/(\[.*?\]|Probs:|Mid:|Tape:|Features:|Ctx:|Pos:|\d+\.\d+)/g,
		);

		return (
			<span className="leading-5">
				{parts.map((part, i) => {
					if (!part) return null;

					// Probabilities or features in square brackets
					if (part.startsWith("[") && part.includes(":")) {
						return (
							<span
								key={i}
								className="text-cyan-400/80 font-mono tracking-tighter"
							>
								{part}
							</span>
						);
					}
					// Main labels (make them less bright)
					if (
						["Probs:", "Mid:", "Tape:", "Features:", "Ctx:", "Pos:"].includes(
							part,
						)
					) {
						return (
							<span key={i} className="text-muted-foreground/70 font-bold mr-1">
								{part}
							</span>
						);
					}
					// Numbers
					if (/^\d+\.\d+$/.test(part)) {
						return (
							<span key={i} className="text-foreground/90 tabular-nums">
								{part}
							</span>
						);
					}
					// Position state
					if (part.includes("NONE")) {
						return (
							<span key={i} className="text-muted-foreground/40">
								{part}
							</span>
						);
					}
					if (part.includes("USD") && !part.includes("0.0 USD")) {
						return (
							<span
								key={i}
								className="text-emerald-400/90 font-bold underline decoration-emerald-500/30 underline-offset-4"
							>
								{part}
							</span>
						);
					}

					return (
						<span key={i} className="text-foreground/70">
							{part}
						</span>
					);
				})}
			</span>
		);
	};

	const displayedLogs = isPaused ? frozenLogs : logs;

	return (
		<Card className="h-full flex flex-col border-border/20 shadow-none bg-[#0a0a0c]">
			<CardHeader className="py-2 px-4 border-b border-border/10 flex flex-row items-center justify-between space-y-0 shrink-0 bg-muted/5">
				<CardTitle className="text-[10px] font-black uppercase tracking-[0.2em] text-muted-foreground/60 flex items-center gap-2">
					<Terminal
						size={14}
						className={isPaused ? "text-amber-500/50" : "text-cyan-500/50"}
					/>
					Engine Activity{" "}
					{isPaused && (
						<span className="text-amber-500/80 ml-2 font-bold">[ PAUSED ]</span>
					)}
				</CardTitle>
				<div className="flex items-center gap-1">
					<Button
						variant="ghost"
						size="icon"
						className="h-7 w-7 text-muted-foreground/40 hover:text-foreground"
						onClick={handlePauseToggle}
					>
						{isPaused ? <Play size={14} /> : <Pause size={14} />}
					</Button>
					<Button
						variant="ghost"
						size="icon"
						className="h-7 w-7 text-muted-foreground/40 hover:text-rose-400"
					>
						<Trash2 size={14} />
					</Button>
				</div>
			</CardHeader>
			<CardContent className="flex-1 p-0 overflow-hidden relative">
				<div
					ref={scrollContainerRef}
					className="h-full overflow-y-auto custom-scrollbar bg-[radial-gradient(circle_at_top_right,_var(--tw-gradient-stops))] from-muted/5 via-transparent to-transparent"
				>
					<div className="p-4 font-mono text-[11px] space-y-1">
						{displayedLogs.map((log, idx) => (
							<div
								key={log.id || idx}
								className="flex gap-4 items-start py-0.5 border-b border-border/[0.03] group transition-colors hover:bg-white/[0.02]"
							>
								<span className="text-muted-foreground/30 shrink-0 select-none w-14 tabular-nums text-[10px]">
									{log.timestamp
										? format(new Date(log.timestamp * 1000), "HH:mm:ss")
										: "--:--:--"}
								</span>
								<div
									className={`flex-1 min-w-0 transition-opacity ${isPaused ? "opacity-70" : "opacity-100"}`}
								>
									{log.type === "TRADE" && (
										<span className="px-1 py-0 rounded bg-emerald-500/10 text-emerald-400 font-black mr-2 text-[9px] uppercase">
											TRADE
										</span>
									)}
									{log.type === "ERROR" && (
										<span className="px-1 py-0 rounded bg-rose-500/10 text-rose-400 font-black mr-2 text-[9px] uppercase">
											ERROR
										</span>
									)}

									{log.symbol && (
										<span className="font-bold mr-2 text-cyan-500/60 tabular-nums">
											{log.symbol}
										</span>
									)}
									{formatLogMessage(log.message)}
								</div>
							</div>
						))}
						{displayedLogs.length === 0 && (
							<div className="h-64 flex flex-col items-center justify-center text-muted-foreground/10 space-y-4">
								<Terminal size={40} strokeWidth={1} />
								<span className="text-[10px] tracking-widest font-bold">
									SYSTEM_STANDBY
								</span>
							</div>
						)}
						<div className="h-4" />
					</div>
				</div>
				{!isPaused && logs.length > 0 && (
					<div className="absolute bottom-2 right-4 flex items-center gap-2 px-2 py-0.5 rounded-full bg-cyan-500/5 border border-cyan-500/10 transition-all animate-in fade-in slide-in-from-bottom-1">
						<div className="w-1 h-1 rounded-full bg-cyan-500 animate-pulse" />
						<span className="text-[8px] text-cyan-500/80 font-bold tracking-tighter uppercase">
							Feeding
						</span>
					</div>
				)}
			</CardContent>
		</Card>
	);
};
