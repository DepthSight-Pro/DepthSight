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
import { Card, CardContent } from "@/components/ui/card";
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
import type { LogEntry } from "@/types/api";

const getLevelBadge = (level: LogEntry["level"]) => {
	const styles = {
		INFO: "bg-primary/20 text-primary border-primary/30",
		SUCCESS: "bg-profit/20 text-profit border-profit/30",
		WARNING: "bg-warning/20 text-warning border-warning/30",
		ERROR: "bg-loss/20 text-loss border-loss/30",
		DEBUG: "bg-gray-500/20 text-gray-500 border-gray-500/30",
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
			>
				{isPaused ? (
					<Play className="w-4 h-4 mr-2" />
				) : (
					<Pause className="w-4 h-4 mr-2" />
				)}
				{isPaused ? t("resumeButton") : t("pauseButton")}
			</Button>
			<Button
				variant="outline"
				size="sm"
				onClick={handleExport}
				disabled={filteredLogs.length === 0}
			>
				<Download className="w-4 h-4 mr-2" />
				{t("exportButton")}
			</Button>
			<Button variant="destructive" size="sm" onClick={handleClearLogs}>
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
			<Card className="mb-6">
				<CardContent className="p-4 flex flex-wrap items-center gap-4">
					<div className="relative flex-grow min-w-[300px]">
						<Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
						<Input
							placeholder={t("searchPlaceholder")}
							className="pl-10"
							value={searchTerm}
							onChange={(e) => setSearchTerm(e.target.value)}
						/>
					</div>
					<div className="flex items-center gap-2">
						<Filter className="h-4 w-4 text-muted-foreground" />
						<Select
							value={levelFilter}
							onValueChange={(value) =>
								setLevelFilter(value as LogEntry["level"] | "all")
							}
						>
							<SelectTrigger className="w-[150px]">
								<SelectValue placeholder={t("allLevels")} />
							</SelectTrigger>
							<SelectContent>
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
							<SelectTrigger className="w-[180px]">
								<SelectValue placeholder={t("allSources")} />
							</SelectTrigger>
							<SelectContent>
								<SelectItem value="all">{t("allSources")}</SelectItem>
								{sources.map((s) => (
									<SelectItem key={s} value={s}>
										{s}
									</SelectItem>
								))}
							</SelectContent>
						</Select>
					</div>
				</CardContent>
			</Card>

			<div
				ref={logContainerRef}
				className="h-[calc(100vh-250px)] overflow-y-auto rounded-lg bg-card p-2 border font-mono text-xs"
			>
				{isLoadingHistory ? (
					<div className="flex items-center justify-center h-full text-muted-foreground">
						<Loader2 className="w-8 h-8 animate-spin mr-4" />
						{t("loadingHistory")}
					</div>
				) : filteredLogs.length === 0 ? (
					<div className="flex items-center justify-center h-full text-muted-foreground">
						{t("noLogs")}
					</div>
				) : (
					<div className="space-y-1">
						{filteredLogs.map((log) => (
							<div
								key={log.id}
								className="flex items-start space-x-4 p-2 rounded-md hover:bg-accent"
							>
								<span className="text-muted-foreground">
									{new Date(log.timestamp).toLocaleTimeString()}
								</span>
								<span>{getLevelBadge(log.level)}</span>
								<span className="text-primary font-medium w-36 truncate">
									[{log.component}]
								</span>
								<span className="text-foreground flex-1 whitespace-pre-wrap">
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
