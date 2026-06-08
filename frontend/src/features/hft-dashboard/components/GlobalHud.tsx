// src/features/hft-dashboard/components/GlobalHud.tsx

import { Play, Server, ShieldAlert, Square } from "lucide-react";
import React from "react";
import { Badge } from "@/components/ui/badge";
import {
	Select,
	SelectContent,
	SelectItem,
	SelectTrigger,
	SelectValue,
} from "@/components/ui/select";
import { useConfig } from "@/lib/api";
import { useAuth } from "../../../context/AuthContext";
import { useHftStore } from "../hooks/useHftStore";

const StatusItem = ({
	label,
	value,
	colorClass,
}: {
	label: string;
	value: string | number;
	colorClass: string;
}) => (
	<div className="flex flex-col gap-0.5 px-4 border-r border-border/40 last:border-r-0">
		<span className="text-xs uppercase font-semibold text-muted-foreground/60 tracking-wider leading-none">
			{label}
		</span>
		<span className={`text-sm font-mono font-bold ${colorClass}`}>{value}</span>
	</div>
);

const apiBase = import.meta.env.VITE_PUBLIC_API_URL || "";

export const GlobalHud: React.FC = () => {
	const { data: appConfig } = useConfig();
	const { status, oracleSymbols, isConnected, selectedApiKeyId, setApiKeyId } =
		useHftStore();
	const { token: authToken } = useAuth();

	const binanceKeys = React.useMemo(() => {
		if (!appConfig?.apiKeys) return [];
		return appConfig.apiKeys.filter(
			(k) =>
				k.isActive &&
				(k.exchange?.toLowerCase() === "binance" ||
					k.exchange?.toLowerCase() === "binance_futures"),
		);
	}, [appConfig]);

	// Auto-select first key if none selected
	React.useEffect(() => {
		if (binanceKeys.length > 0 && !selectedApiKeyId) {
			setApiKeyId(binanceKeys[0].id);
		}
	}, [binanceKeys, selectedApiKeyId, setApiKeyId]);

	const latency = status?.latency_ms ?? 0;
	const cpuUsage = status?.server_load_cpu ?? 0;
	const activeBots = status?.active_bots ?? 0;

	// Engine is considered running if there are active bots OR we received a heartbeat recently
	const isEngineActive = activeBots > 0 || (status?.engine_active ?? false);
	// Connection is synced if WS is open AND we have some data coming in
	const isSynced = isConnected && (oracleSymbols.length > 0 || activeBots > 0);

	const sendCommand = async (command: "start" | "stop" | "emergency") => {
		const token = authToken;
		if (!token) return;

		try {
			const queryParams = new URLSearchParams();
			if (command === "start" && selectedApiKeyId) {
				queryParams.append("api_key_id", String(selectedApiKeyId));
			}

			const url = `${apiBase}/api/v1/hft/${command}${queryParams.toString() ? `?${queryParams.toString()}` : ""}`;
			await fetch(url, {
				method: "POST",
				headers: {
					Authorization: `Bearer ${token}`,
					"Content-Type": "application/json",
				},
			});
		} catch (error) {
			console.error(`Failed to send ${command} command:`, error);
		}
	};

	return (
		<div className="h-12 border-b border-border/40 bg-card/50 backdrop-blur-sm flex items-center justify-between px-4 shrink-0 z-50">
			<div className="flex items-center gap-4">
				<div className="flex items-center gap-3 mr-2">
					<div
						className={`p-1.5 rounded-lg transition-all duration-700 ${isEngineActive ? "bg-cyan-500/10 text-cyan-500 shadow-[0_0_15px_rgba(6,182,212,0.15)]" : "bg-muted text-muted-foreground"}`}
					>
						<Server
							size={18}
							className={isEngineActive ? "animate-pulse" : ""}
						/>
					</div>
				</div>

				<div className="flex items-center h-8">
					<StatusItem
						label="Latency"
						value={`${latency}ms`}
						colorClass={latency < 50 ? "text-emerald-500" : "text-amber-500"}
					/>
					<StatusItem
						label="System Load"
						value={`${cpuUsage}%`}
						colorClass={cpuUsage < 80 ? "text-cyan-500" : "text-rose-500"}
					/>
					<StatusItem
						label="Active Bots"
						value={activeBots}
						colorClass="text-primary"
					/>

					<div className="flex flex-col gap-0.5 px-4">
						<span className="text-[11px] uppercase font-semibold text-muted-foreground/60 tracking-wider leading-none">
							Redis
						</span>
						<Badge
							variant={isSynced ? "default" : "destructive"}
							className="h-4 text-[10px] px-1.5 w-fit font-bold"
						>
							{isSynced ? "SYNCED" : "OFFLINE"}
						</Badge>
					</div>
				</div>
			</div>

			<div className="flex items-center gap-3">
				{binanceKeys.length > 1 && !isEngineActive && (
					<div className="flex items-center gap-2 mr-2">
						<span className="text-xs uppercase font-bold text-muted-foreground whitespace-nowrap">
							Account:
						</span>
						<Select
							value={selectedApiKeyId?.toString()}
							onValueChange={(v) => setApiKeyId(parseInt(v, 10))}
						>
							<SelectTrigger className="h-9 w-[160px] text-xs bg-zinc-950/50 border-white/5 font-mono">
								<SelectValue placeholder="Select Key" />
							</SelectTrigger>
							<SelectContent className="bg-zinc-950 border-white/10 text-white">
								{binanceKeys.map((k) => (
									<SelectItem
										key={k.id}
										value={k.id.toString()}
										className="text-xs font-mono hover:bg-white/10"
									>
										{k.name} ({k.keyPrefix}...)
									</SelectItem>
								))}
							</SelectContent>
						</Select>
					</div>
				)}

				<button
					onClick={() => sendCommand(isEngineActive ? "stop" : "start")}
					disabled={!isConnected}
					className={`flex items-center gap-2 px-5 h-9 rounded-md text-xs font-bold transition-all border ${
						!isConnected ? "opacity-50 cursor-not-allowed grayscale" : ""
					} ${
						isEngineActive
							? "bg-zinc-800 text-zinc-400 border-white/10 hover:bg-zinc-700"
							: "bg-cyan-500/10 text-cyan-400 border-cyan-500/30 hover:bg-cyan-500/20 active:scale-95 shadow-lg shadow-cyan-500/5"
					}`}
				>
					{isEngineActive ? (
						<Square size={14} fill="currentColor" />
					) : (
						<Play size={14} fill="currentColor" />
					)}
					{isEngineActive ? "SHUTDOWN ENGINE" : "START ENGINE"}
				</button>

				<button
					onClick={() => sendCommand("emergency")}
					disabled={!isConnected}
					className={`px-5 h-9 rounded-md text-xs font-black tracking-wider border transition-all ${
						!isConnected
							? "opacity-50 cursor-not-allowed grayscale"
							: "bg-rose-500/10 border-rose-500/20 text-rose-500 hover:bg-rose-500 hover:text-white active:scale-95"
					} flex items-center gap-2`}
				>
					<ShieldAlert size={16} />
					PANIC
				</button>
			</div>
		</div>
	);
};
