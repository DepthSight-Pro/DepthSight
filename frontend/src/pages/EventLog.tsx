// src/pages/EventLog.tsx

import {
	Download,
	Filter,
	Loader2,
	Pause,
	Play,
	Search,
	Terminal,
	Trash2,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { PageLayout } from "@/components/layout/PageLayout";
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
import { useAuth } from "@/context/AuthContext";
import { useWebSocket } from "@/context/WebSocketProvider";
import { useLogHistory } from "@/lib/api";
import { cn } from "@/lib/utils";
import type { LogEntry } from "@/types/api";

const getLevelBadge = (level: LogEntry["level"]) => {
	const styles = {
		INFO: "bg-cyan/15 text-cyan border-cyan/30",
		SUCCESS: "bg-emerald-500/15 text-emerald-400 border-emerald-500/30",
		WARNING: "bg-amber-500/15 text-amber-300 border-amber-500/30",
		ERROR: "bg-rose-500/15 text-rose-300 border-rose-500/30",
		DEBUG: "bg-white/10 text-white/60 border-white/10",
	};
	return (
		<Badge variant="outline" className={`whitespace-nowrap ${styles[level]}`}>
			{level}
		</Badge>
	);
};

export default function EventLog() {
	const { t } = useTranslation(["eventLog", "common"]);
	const { user } = useAuth();
	const { subscribe, unsubscribe } = useWebSocket();

	const { data: initialLogs, isLoading: isLoadingHistory } = useLogHistory();

	const [prevUserId, setPrevUserId] = useState<number | undefined>(undefined);
	const [logs, setLogs] = useState<LogEntry[]>([]);
	const [prevInitialLogs, setPrevInitialLogs] = useState<
		LogEntry[] | undefined
	>(undefined);

	// Synchronous render-phase state updates to avoid useEffect cascading renders:
	if (user?.id !== prevUserId) {
		setPrevUserId(user?.id);
		setLogs([]);
	}

	if (initialLogs !== prevInitialLogs) {
		setPrevInitialLogs(initialLogs);
		if (initialLogs) {
			setLogs(initialLogs);
		}
	}

	const [searchTerm, setSearchTerm] = useState("");
	const [levelFilter, setLevelFilter] = useState<LogEntry["level"] | "all">(
		"all",
	);
	const [sourceFilter, setSourceFilter] = useState("all");
	const [isPaused, setIsPaused] = useState(false);
	const logContainerRef = useRef<HTMLDivElement>(null);

	const handleNewLog = useCallback((payload: unknown) => {
		const newLog = payload as LogEntry;
		setIsPaused((currentPaused) => {
			if (currentPaused) return currentPaused;

			setLogs((prev) => {
				if (prev.some((log) => log.id === newLog.id)) {
					return prev;
				}
				return [newLog, ...prev].slice(0, 500);
			});
			return currentPaused;
		});
	}, []);

	useEffect(() => {
		if (user?.id) {
			const channel = `user_logs:${user.id}`;
			subscribe(channel, handleNewLog);
			return () => {
				unsubscribe(channel, handleNewLog);
			};
		}
	}, [user, subscribe, unsubscribe, handleNewLog]);

	const sources = useMemo(
		() => [...new Set(logs.map((l) => l.component))],
		[logs],
	);

	const filteredLogs = useMemo(() => {
		return logs.filter((log) => {
			const searchMatch =
				searchTerm === "" ||
				log.message.toLowerCase().includes(searchTerm.toLowerCase()) ||
				log.component.toLowerCase().includes(searchTerm.toLowerCase());
			const levelMatch = levelFilter === "all" || log.level === levelFilter;
			const sourceMatch =
				sourceFilter === "all" || log.component === sourceFilter;
			return searchMatch && levelMatch && sourceMatch;
		});
	}, [logs, searchTerm, levelFilter, sourceFilter]);

	useEffect(() => {
		if (!isPaused && logContainerRef.current) {
			logContainerRef.current.scrollTop = 0;
		}
	}, [isPaused]);

	const handleClearLogs = () => {
		setLogs([]);
	};

	const handleExport = () => {
		if (filteredLogs.length === 0) return;

		const headers = ["Timestamp", "Level", "Source", "Message"];
		const csvContent = [
			headers.join(","),
			...filteredLogs.map((log) =>
				[
					new Date(log.timestamp).toISOString(),
					log.level,
					`"${log.component.replace(/"/g, '""')}"`,
					`"${log.message.replace(/"/g, '""')}"`,
				].join(","),
			),
		].join("\n");

		const blob = new Blob([csvContent], { type: "text/csv;charset=utf-8;" });
		const url = URL.createObjectURL(blob);
		const link = document.createElement("a");
		link.setAttribute("href", url);
		link.setAttribute(
			"download",
			`event_logs_${new Date().toISOString().split("T")[0]}.csv`,
		);
		link.style.visibility = "hidden";
		document.body.appendChild(link);
		link.click();
		document.body.removeChild(link);
	};

	const headerActions = (
		<div className="flex items-center space-x-2">
			<Button
				variant="outline"
				size="sm"
				onClick={() => setIsPaused(!isPaused)}
				className={cn(
					"border-white/10 bg-white/[0.04] text-white hover:bg-white/[0.08] hover:text-white transition-all cursor-pointer",
					isPaused && "border-amber-500/40 bg-amber-500/10 text-amber-300",
				)}
			>
				{isPaused ? (
					<Play className="w-4 h-4 mr-2 text-amber-400" />
				) : (
					<Pause className="w-4 h-4 mr-2 text-cyan" />
				)}
				{isPaused ? t("resumeButton") : t("pauseButton")}
			</Button>
			<Button
				variant="outline"
				size="sm"
				onClick={handleExport}
				disabled={filteredLogs.length === 0}
				className="border-white/10 bg-white/[0.04] text-white hover:bg-white/[0.08] hover:text-white transition-all cursor-pointer disabled:opacity-40"
			>
				<Download className="w-4 h-4 mr-2 text-white/70" />
				{t("exportButton")}
			</Button>
			<Button
				variant="destructive"
				size="sm"
				onClick={handleClearLogs}
				className="border border-rose-500/30 bg-rose-500/10 text-rose-300 hover:bg-rose-500/20 hover:text-rose-200 transition-all cursor-pointer"
			>
				<Trash2 className="w-4 h-4 mr-2" />
				{t("clearButton")}
			</Button>
		</div>
	);

	return (
		<PageLayout
			title={t("pageTitle")}
			icon={Terminal}
			headerActions={headerActions}
		>
			<div className="mb-6 rounded-2xl border border-white/10 glass shadow-xl p-4 flex flex-wrap items-center gap-4">
				<div className="relative flex-grow min-w-[280px]">
					<Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-white/40" />
					<Input
						placeholder={t("searchPlaceholder")}
						className="pl-10 bg-white/[0.03] border-white/10 text-white placeholder:text-white/40 focus-visible:ring-cyan/30 rounded-xl"
						value={searchTerm}
						onChange={(e) => setSearchTerm(e.target.value)}
					/>
				</div>
				<div className="flex items-center gap-2">
					<Filter className="h-4 w-4 text-white/40" />
					<Select
						value={levelFilter}
						onValueChange={(value) =>
							setLevelFilter(value as LogEntry["level"] | "all")
						}
					>
						<SelectTrigger className="w-[150px] bg-white/[0.03] border-white/10 text-white rounded-xl">
							<SelectValue placeholder={t("allLevels")} />
						</SelectTrigger>
						<SelectContent className="bg-[#0c0d12]/95 border-white/10 text-white backdrop-blur-xl">
							<SelectItem value="all">{t("allLevels")}</SelectItem>
							<SelectItem value="ERROR">{t("levelError")}</SelectItem>
							<SelectItem value="WARNING">{t("levelWarning")}</SelectItem>
							<SelectItem value="SUCCESS">{t("levelSuccess")}</SelectItem>
							<SelectItem value="INFO">{t("levelInfo")}</SelectItem>
							<SelectItem value="DEBUG">{t("levelDebug")}</SelectItem>
						</SelectContent>
					</Select>
				</div>
				<div className="flex items-center gap-2">
					<Select value={sourceFilter} onValueChange={setSourceFilter}>
						<SelectTrigger className="w-[180px] bg-white/[0.03] border-white/10 text-white rounded-xl">
							<SelectValue placeholder={t("allSources")} />
						</SelectTrigger>
						<SelectContent className="bg-[#0c0d12]/95 border-white/10 text-white backdrop-blur-xl">
							<SelectItem value="all">{t("allSources")}</SelectItem>
							{sources.map((s) => (
								<SelectItem key={s} value={s}>
									{s}
								</SelectItem>
							))}
						</SelectContent>
					</Select>
				</div>
			</div>

			<div
				ref={logContainerRef}
				className="h-[calc(100vh-250px)] overflow-y-auto rounded-2xl border border-white/10 glass shadow-xl p-4 font-mono text-xs"
			>
				{isLoadingHistory ? (
					<div className="flex flex-col items-center justify-center h-full gap-3 text-white/70">
						<Loader2 className="w-8 h-8 animate-spin text-cyan" />
						<span className="text-sm font-sans tracking-wide">{t("loadingHistory")}</span>
					</div>
				) : filteredLogs.length === 0 ? (
					<div className="flex items-center justify-center h-full text-white/40">
						{t("noLogs")}
					</div>
				) : (
					<div className="space-y-1">
						{filteredLogs.map((log) => (
							<div
								key={log.id}
								className="flex flex-col sm:flex-row items-start gap-1 sm:gap-3 px-2.5 sm:px-3 py-2 rounded-xl hover:bg-white/[0.04] border border-transparent hover:border-white/5 transition-colors min-w-0 w-full"
							>
								<div className="flex items-center gap-2 sm:gap-2.5 shrink-0 flex-wrap">
									<span className="text-white/40 font-mono shrink-0 whitespace-nowrap text-[11px] sm:text-xs">
										{new Date(log.timestamp).toLocaleTimeString()}
									</span>
									<span className="shrink-0">{getLevelBadge(log.level)}</span>
									<span className="text-cyan font-medium shrink-0 font-mono text-[11px] sm:text-xs whitespace-nowrap">
										[{log.component}]
									</span>
								</div>
								<span className="text-white/90 flex-1 whitespace-pre-wrap break-words font-mono min-w-0 w-full sm:w-auto text-xs leading-relaxed">
									{log.message}
								</span>
							</div>
						))}
					</div>
				)}
			</div>
		</PageLayout>
	);
}
