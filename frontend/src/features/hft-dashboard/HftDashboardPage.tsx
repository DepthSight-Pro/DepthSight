// src/features/hft-dashboard/HftDashboardPage.tsx

import { Activity, Wifi } from "lucide-react";
import { EquityChart } from "./components/EquityChart";
import { EventLog } from "./components/EventLog";
import { GlobalHud } from "./components/GlobalHud";
import { OracleScanner } from "./components/OracleScanner";
import { StrategyControls } from "./components/StrategyControls";
import { useHftSocket } from "./hooks/useHftSocket";

export default function HftDashboardPage() {
	// Initialize WebSocket connection for real-time HFT data
	useHftSocket();

	return (
		<div className="absolute inset-0 flex flex-col overflow-hidden bg-background text-foreground selection:bg-cyan-500/30 font-sans leading-tight">
			<GlobalHud />

			<div className="flex-1 flex overflow-hidden p-1 gap-1 min-h-0">
				{/* Main Content Area: Chart, Scanner, Logs */}
				<div className="flex flex-1 flex-col min-w-0 gap-1 overflow-hidden h-full">
					{/* Top: Equity Chart - Slightly reduced to 55% total area */}
					<div className="flex-[5.5] min-h-0 border border-border/40 rounded-lg bg-card/5 relative overflow-hidden">
						<EquityChart />
					</div>

					{/* Bottom Split: Scanner & Logs - 40% of available height */}
					{/* Bottom Split: Scanner & Logs - Adjusted for more visibility */}
					<div className="flex-[6] min-h-0 flex gap-1 overflow-hidden">
						<div className="w-1/2 border border-border/40 rounded-lg h-full overflow-hidden relative bg-card/5 p-1">
							<OracleScanner />
						</div>
						<div className="w-1/2 border border-border/40 rounded-lg h-full overflow-hidden relative bg-card/5 p-1">
							<EventLog />
						</div>
					</div>
				</div>

				{/* Right Sidebar: Controls - Constraints to full parent height */}
				<div className="w-[320px] shrink-0 bg-card/80 border border-border/40 rounded-lg flex flex-col h-full overflow-hidden">
					<div className="flex-1 overflow-y-auto">
						<StrategyControls />
					</div>
				</div>
			</div>

			{/* Ultra-compact footer */}
			<div className="h-4 shrink-0 border-t border-border/40 bg-zinc-950/50 text-[8px] text-muted-foreground flex items-center justify-between px-3 select-none">
				<div className="flex items-center gap-3">
					<span className="opacity-40 font-mono tracking-tighter uppercase">
						DepthSight HFT System
					</span>
					<span className="opacity-20">|</span>
					<span className="flex items-center gap-1">
						<Activity size={7} className="text-emerald-500/50" /> ENGINE_ACTIVE
					</span>
				</div>
				<div className="flex items-center gap-3 opacity-60">
					<span className="flex items-center gap-1">
						<Wifi size={8} className="text-cyan-500/70" />
						MAINNET_STABLE
					</span>
				</div>
			</div>
		</div>
	);
}
