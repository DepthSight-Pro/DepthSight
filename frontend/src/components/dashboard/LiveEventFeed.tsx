// src/components/dashboard/LiveEventFeed.tsx

import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useAuth } from "@/context/AuthContext";
import { useWebSocket } from "@/context/WebSocketProvider";
import type { LogEntry } from "@/types/api";

const getLevelStyle = (level: LogEntry["level"]) => {
	switch (level) {
		case "SUCCESS":
			return "text-profit";
		case "WARNING":
			return "text-warning";
		case "ERROR":
			return "text-loss";
		default:
			return "text-muted-foreground";
	}
};

export function LiveEventFeed() {
	const { t } = useTranslation(["index", "common"]);
	const { user } = useAuth();
	const { subscribe, unsubscribe } = useWebSocket();
	const [events, setEvents] = useState<LogEntry[]>([]);

	const handleNewImportantLog = useCallback((payload: unknown) => {
		const newEvent = payload as LogEntry;
		setEvents((prev) => [newEvent, ...prev].slice(0, 10));
	}, []);

	useEffect(() => {
		if (user) {
			const channel = `important_logs:${user.id}`;
			subscribe(channel, handleNewImportantLog);

			return () => {
				unsubscribe(channel, handleNewImportantLog);
			};
		}
	}, [user, subscribe, unsubscribe, handleNewImportantLog]);

	return (
		<Card className="h-full flex flex-col">
			<CardHeader className="pb-3">
				<CardTitle className="text-base font-medium text-foreground">
					{t("index:liveEventFeed.title")}
				</CardTitle>
			</CardHeader>
			{/* CardContent now stretches and contains conditional logic */}
			<CardContent className="flex-grow">
				{events.length > 0 ? (
					// If there are events, show a div with scrolling
					<div className="space-y-2 terminal-scroll max-h-48 overflow-y-auto">
						{events.map((event) => (
							<div key={event.id} className="text-sm font-mono flex space-x-2">
								<span className="text-terminal-dim">
									[{new Date(event.timestamp).toLocaleTimeString()}]
								</span>
								<span className={`font-medium ${getLevelStyle(event.level)}`}>
									[{event.level}]
								</span>
								<span className="text-foreground flex-1">{event.message}</span>
							</div>
						))}
					</div>
				) : (
					// If there are no events, show a div with centering
					<div className="h-full flex items-center justify-center text-sm text-muted-foreground">
						{t("index:liveEventFeed.waitingForEvents")}
					</div>
				)}
			</CardContent>
		</Card>
	);
}
