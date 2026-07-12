import type React from "react";
import { useState } from "react";
import { MemoryBank } from "./MemoryBank";
import { AutopilotTerminal } from "./AutopilotTerminal";

interface AgentWorkspaceProps {
	onStrategyGenerated: (strategyJson: Record<string, any>) => void;
}

export const AgentWorkspace: React.FC<AgentWorkspaceProps> = ({ onStrategyGenerated }) => {
	const [isAutopilotRunning, setIsAutopilotRunning] = useState(false);
	const [activeIteration, setActiveIteration] = useState(0);

	return (
		<div className="flex flex-col lg:flex-row gap-4 h-full min-h-[450px] p-1">
			{/* Terminal Panel */}
			<div className="flex-1 flex flex-col min-w-0">
				<AutopilotTerminal
					onStrategyGenerated={onStrategyGenerated}
					setIsAutopilotRunning={setIsAutopilotRunning}
					setActiveIteration={setActiveIteration}
				/>
			</div>

			{/* Memory Bank Sidebar */}
			<div className="w-full lg:w-80 shrink-0 flex flex-col h-[350px] lg:h-auto">
				<MemoryBank
					isAutopilotRunning={isAutopilotRunning}
					activeIteration={activeIteration}
				/>
			</div>
		</div>
	);
};
