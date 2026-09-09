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
		<div className="flex flex-col xl:flex-row gap-4 h-full p-1 overflow-y-auto xl:overflow-hidden pb-14 xl:pb-1">
			
			{/* Terminal Panel */}
			<div className="w-full shrink-0 xl:flex-1 xl:shrink xl:min-w-0 xl:min-h-0 xl:h-full flex flex-col">
				<AutopilotTerminal
					onStrategyGenerated={onStrategyGenerated}
					setIsAutopilotRunning={setIsAutopilotRunning}
					setActiveIteration={setActiveIteration}
				/>
			</div>

			{/* Memory Bank Sidebar */}
			<div className="w-full shrink-0 xl:w-80 xl:h-full flex flex-col h-[380px] xl:h-auto">
				<MemoryBank
					isAutopilotRunning={isAutopilotRunning}
					activeIteration={activeIteration}
				/>
			</div>
			
		</div>
	);
};