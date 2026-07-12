// pwa/components/agent/AgentWorkspace.tsx

import type React from "react";
import { useState } from "react";
import { MemoryBank } from "./MemoryBank";
import { AutopilotTerminal } from "./AutopilotTerminal";
import type { StrategyConfig } from "../../types";

interface AgentWorkspaceProps {
	onStrategyGenerated: (strategyJson: Partial<StrategyConfig>) => void;
}

export const AgentWorkspace: React.FC<AgentWorkspaceProps> = ({ onStrategyGenerated }) => {
	const [isAutopilotRunning, setIsAutopilotRunning] = useState(false);
	const [activeIteration, setActiveIteration] = useState(0);

	return (
		<div className="flex flex-col xl:flex-row gap-4 h-full p-1 overflow-y-auto xl:overflow-hidden">
			
			{/* Terminal Panel */}
			<div className="flex-1 flex flex-col min-w-0 min-h-[500px] xl:min-h-0">
				<AutopilotTerminal
					onStrategyGenerated={onStrategyGenerated}
					setIsAutopilotRunning={setIsAutopilotRunning}
					setActiveIteration={setActiveIteration}
				/>
			</div>
			<div className="w-full xl:w-80 shrink-0 flex flex-col h-[400px] xl:h-auto">
				<MemoryBank
					isAutopilotRunning={isAutopilotRunning}
					activeIteration={activeIteration}
				/>
			</div>
			
		</div>
	);
};