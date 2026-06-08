// src/components/strategies/StrategyLiveLogsTab.tsx

import { useQuery } from "@tanstack/react-query";
import { format } from "date-fns";
import { enUS, ru } from "date-fns/locale"; // Import specific locales
import type React from "react";
import { useEffect, useMemo, useRef } from "react";
import { useTranslation } from "react-i18next"; // Import useTranslation
import { Badge } from "@/components/ui/badge";
import { ScrollArea } from "@/components/ui/scroll-area"; // For better scrolling
import { Skeleton } from "@/components/ui/skeleton";
import { authScopedQueryKey } from "@/lib/queryKeys";
import type { LogEntry } from "@/types/api";

interface StrategyLiveLogsTabProps {
	strategyId: string;
	// strategyName: string; // Could also pass name if component name includes it
}

// Helper to get badge variant based on log level (similar to EventLog.tsx)
const getLevelBadge = (level: LogEntry["level"]) => {
	const styles = {
		INFO: "bg-blue-500/20 text-blue-700 border-blue-500/30 dark:text-blue-400",
		SUCCESS:
			"bg-green-500/20 text-green-700 border-green-500/30 dark:text-green-400",
		WARNING:
			"bg-yellow-500/20 text-yellow-700 border-yellow-500/30 dark:text-yellow-400",
		ERROR: "bg-red-500/20 text-red-700 border-red-500/30 dark:text-red-400",
		DEBUG: "bg-gray-500/20 text-gray-700 border-gray-500/30 dark:text-gray-400",
	};
	return (
		<Badge
			variant="outline"
			className={`whitespace-nowrap text-xs ${styles[level]}`}
		>
			{level}
		</Badge>
	);
};

export const StrategyLiveLogsTab: React.FC<StrategyLiveLogsTabProps> = ({
	strategyId,
}) => {
	const { t, i18n } = useTranslation("pages/strategies"); // Use the correct namespace
	const currentLocale = i18n.language; // For date formatting, or use common:locale
	const dateFnsLocale = currentLocale.startsWith("ru") ? ru : enUS; // Use imported locale objects

	// Use queryClient to get data that WebSocketProvider is updating
	// The queryFn is not strictly necessary here if data is only coming from WebSocket updates
	// to ['eventLog'], but react-query expects one.
	const { data: allLogs = [] } = useQuery<LogEntry[]>({
		queryKey: authScopedQueryKey("eventLog"),
		queryFn: async () => {
			// This function might not be called if initialData is provided or cache already exists.
			// If it is called, it means we don't have initial logs for this specific view from cache.
			return []; // Or fetch historical logs for this strategy if an endpoint existed.
		},
		staleTime: Infinity, // Data comes from WebSocket updates
		refetchOnWindowFocus: false,
		refetchOnMount: false, // Don't refetch on mount, rely on existing cache populated by WebSocket
		// Consider initialData if you want to avoid queryFn running on first mount
		// initialData: () => queryClient.getQueryData(['eventLog']) || [],
	});

	const strategyLogs = useMemo(() => {
		return allLogs
			.filter(
				(log) =>
					log.strategy_id === strategyId || log.component?.includes(strategyId),
				// Add more sophisticated filtering if strategyName is part of component, e.g.
				// (log.component && (log.component.includes(strategyId) || log.component.includes(strategyName)))
			)
			.sort(
				(a, b) =>
					new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime(),
			); // Show newest first
	}, [allLogs, strategyId]);

	const scrollAreaRef = useRef<HTMLDivElement>(null);
	const viewportRef = useRef<HTMLDivElement>(null);

	// Auto-scroll to bottom (or top if reversed)
	useEffect(() => {
		if (viewportRef.current) {
			// If showing newest first, scroll to top
			viewportRef.current.scrollTo({ top: 0, behavior: "smooth" });
			// If showing oldest first and appending, scroll to bottom:
			// viewportRef.current.scrollTo({ top: viewportRef.current.scrollHeight, behavior: 'smooth' });
		}
	}, []);

	if (allLogs.length === 0) {
		// Check allLogs before filtering to show loading for initial population
		// This loading state is for when the global eventLog cache is empty.
		// If it has data, but no logs for *this* strategy, it will show "No logs..." below.
		return (
			<div className="space-y-2 mt-4">
				<p className="text-sm text-muted-foreground">
					{t("liveLogsTab.waitingForFirstLogEvents")}
				</p>
				{[...Array(3)].map((_, i) => (
					<Skeleton key={i} className="h-8 w-full" />
				))}
			</div>
		);
	}

	return (
		<div className="mt-4">
			{strategyLogs.length === 0 ? (
				<p className="text-muted-foreground text-center py-4">
					{t("liveLogsTab.noLogsForStrategy")}
				</p>
			) : (
				<ScrollArea
					className="h-[400px] rounded-md border p-1 font-mono text-xs"
					ref={scrollAreaRef}
				>
					<div ref={viewportRef} className="p-2">
						{strategyLogs.map((log) => (
							<div
								key={log.id}
								className="flex items-start space-x-3 p-1.5 border-b border-dashed border-border/50 last:border-b-0"
							>
								<span className="text-muted-foreground whitespace-nowrap">
									{format(new Date(log.timestamp), "HH:mm:ss.SSS", {
										locale: dateFnsLocale,
									})}
								</span>
								<span>{getLevelBadge(log.level)}</span>
								<span className="text-foreground/80 whitespace-pre-wrap break-all">
									{log.message}
								</span>
							</div>
						))}
					</div>
				</ScrollArea>
			)}
		</div>
	);
};
