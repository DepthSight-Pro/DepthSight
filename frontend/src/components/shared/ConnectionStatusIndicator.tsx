// src/components/shared/ConnectionStatusIndicator.tsx

import { Loader2, Wifi, WifiOff } from "lucide-react";
import React from "react";
import { useTranslation } from "react-i18next";
import { ReadyState } from "react-use-websocket";
import { Badge } from "@/components/ui/badge";
import {
	Tooltip,
	TooltipContent,
	TooltipTrigger,
} from "@/components/ui/tooltip";
import { useWebSocketStatus } from "@/context/WebSocketProvider";
import { cn } from "@/lib/utils";

export const ConnectionStatusIndicator: React.FC = () => {
	const { readyState } = useWebSocketStatus();
	const { t } = useTranslation(["index", "common"]); // Load 'index' and 'common' namespaces

	const statusConfig = React.useMemo(
		() => ({
			[ReadyState.CONNECTING]: {
				text: t("index:connectionStatus.connecting"),
				icon: <Loader2 className="h-3 w-3 animate-spin" />,
				color: "bg-warning/20 text-warning border-warning/30",
				tooltip: t("index:connectionStatus.tooltipConnecting"),
			},
			[ReadyState.OPEN]: {
				text: t("index:connectionStatus.live"), // 'live' is used in index.json for OPEN state
				icon: <Wifi className="h-3 w-3" />,
				color: "bg-profit/20 text-profit border-profit/30",
				tooltip: t("index:connectionStatus.tooltipLive"),
			},
			[ReadyState.CLOSING]: {
				text: t("index:connectionStatus.closing"),
				icon: <Loader2 className="h-3 w-3 animate-spin" />,
				color: "bg-warning/20 text-warning border-warning/30",
				tooltip: t("index:connectionStatus.tooltipClosing"),
			},
			[ReadyState.CLOSED]: {
				text: t("index:connectionStatus.disconnected"), // 'disconnected' is used for CLOSED state
				icon: <WifiOff className="h-3 w-3" />,
				color: "bg-loss/20 text-loss border-loss/30",
				tooltip: t("index:connectionStatus.tooltipDisconnected"),
			},
			[ReadyState.UNINSTANTIATED]: {
				text: t("index:connectionStatus.initializing"), // 'initializing' for UNINSTANTIATED
				icon: <Loader2 className="h-3 w-3 animate-spin" />,
				color: "bg-gray-500/20 text-gray-500 border-gray-500/30",
				tooltip: t("index:connectionStatus.tooltipInitializing"),
			},
		}),
		[t],
	);

	const currentStatus =
		statusConfig[readyState] || statusConfig[ReadyState.UNINSTANTIATED]; // Fallback

	return (
		<Tooltip>
			<TooltipTrigger asChild>
				<Badge
					variant="outline"
					className={cn("transition-all duration-300", currentStatus.color)}
				>
					{currentStatus.icon}
					<span className="ml-1.5">{currentStatus.text}</span>
				</Badge>
			</TooltipTrigger>
			<TooltipContent>
				<p>{currentStatus.tooltip}</p>
			</TooltipContent>
		</Tooltip>
	);
};
