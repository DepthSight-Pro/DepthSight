// src/components/research/BacktestEventFeed.tsx

import { Pause, Play } from "lucide-react";
import React, { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
	Card,
	CardContent,
	CardDescription,
	CardHeader,
	CardTitle,
} from "@/components/ui/card";
import { ScrollArea } from "@/components/ui/scroll-area";
import type { ProgressEventData } from "@/types/api";

interface BacktestEventFeedProps {
	events: ProgressEventData[] | null | undefined;
	status: "pending" | "running" | "completed" | "failed";
}

const getEventTypeBadge = (type: string) => {
	const lowerType = type.toLowerCase();
	if (lowerType.includes("open") || lowerType.includes("filled"))
		return "bg-blue-500/20 text-blue-400 border-blue-500/30";
	if (lowerType.includes("close") || lowerType.includes("hit"))
		return "bg-green-500/20 text-green-400 border-green-500/30";
	if (lowerType.includes("signal"))
		return "bg-yellow-500/20 text-yellow-400 border-yellow-500/30";
	return "bg-gray-500/20 text-gray-400 border-gray-500/30";
};

export const BacktestEventFeed: React.FC<BacktestEventFeedProps> = ({
	events,
	status,
}) => {
	const { t } = useTranslation(["research", "common"]);
	const [isPaused, setIsPaused] = useState(false);
	const scrollAreaRef = useRef<HTMLDivElement>(null);
	const currentLocale = t("common:locale", {
		returnObjects: false,
		defaultValue: "en-US",
	});

	const reversedEvents = React.useMemo(
		() => (events ? [...events].reverse() : []),
		[events],
	);

	useEffect(() => {
		if (!isPaused && scrollAreaRef.current) {
			scrollAreaRef.current.scrollTop = scrollAreaRef.current.scrollHeight;
		}
	}, [isPaused]);

	let statusMessage = "";
	if (status !== "running" && (!events || events.length === 0)) {
		if (status === "completed")
			statusMessage = t("liveEventFeed.backtestCompleted");
		else if (status === "failed")
			statusMessage = t("liveEventFeed.backtestFailed");
		else statusMessage = t("liveEventFeed.waitingForEvents");
	}

	return (
		<Card className="h-full flex flex-col">
			<CardHeader className="flex flex-row items-center justify-between">
				<div>
					<CardTitle>{t("liveEventFeed.title")}</CardTitle>
					<CardDescription>{t("liveEventFeed.description")}</CardDescription>
				</div>
				<Button
					variant="outline"
					size="icon"
					className="h-8 w-8"
					onClick={() => setIsPaused((p) => !p)}
					title={
						isPaused
							? t("liveEventFeed.tooltipResume")
							: t("liveEventFeed.tooltipPause")
					}
				>
					{isPaused ? (
						<Play className="h-4 w-4" />
					) : (
						<Pause className="h-4 w-4" />
					)}
				</Button>
			</CardHeader>
			<CardContent className="flex-grow overflow-hidden">
				<ScrollArea className="h-full max-h-[260px] pr-4">
					<div ref={scrollAreaRef} className="flex flex-col gap-2">
						{statusMessage ? (
							<div className="flex items-center justify-center h-full text-sm text-muted-foreground italic">
								{statusMessage}
							</div>
						) : (
							reversedEvents.map((event, index) => (
								<div
									key={index}
									className="text-xs font-mono flex items-start gap-3"
								>
									<span className="text-muted-foreground/80 whitespace-nowrap pt-0.5">
										{new Date(event.timestamp).toLocaleTimeString(
											currentLocale,
										)}
									</span>
									<Badge
										variant="outline"
										className={`text-[10px] py-0 px-1.5 ${getEventTypeBadge(event.type)}`}
									>
										{event.type}
									</Badge>
									<p className="text-foreground/90 whitespace-pre-wrap flex-1 leading-snug">
										{event.message}
									</p>
								</div>
							))
						)}
					</div>
				</ScrollArea>
			</CardContent>
		</Card>
	);
};
