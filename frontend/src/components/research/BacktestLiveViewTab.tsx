// src/components/research/BacktestLiveViewTab.tsx

import type React from "react";
import type { BacktestRunDetailsData } from "@/types/api";
import { BacktestEventFeed } from "./BacktestEventFeed";
import { BacktestProgressKpiPanel } from "./BacktestProgressKpiPanel";
import { BacktestTradeHistoryTable } from "./BacktestTradeHistoryTable";
import { EquityCurveChart } from "./EquityCurveChart";

interface BacktestLiveViewTabProps {
	run: BacktestRunDetailsData;
}

export const BacktestLiveViewTab: React.FC<BacktestLiveViewTabProps> = ({
	run,
}) => {
	return (
		<div className="grid grid-cols-1 lg:grid-cols-5 gap-6">
			<div className="lg:col-span-3 space-y-6">
				<EquityCurveChart run={run} />
				<BacktestTradeHistoryTable
					runId={run.id}
					status={
						run.status.toLowerCase() as
							| "pending"
							| "running"
							| "completed"
							| "failed"
					}
					onViewTradeOnChart={() => {}} // No chart view in live tab for now
				/>
			</div>
			<div className="lg:col-span-2 space-y-6">
				<BacktestProgressKpiPanel run={run} />
				<BacktestEventFeed
					events={run.progress_info?.events || []}
					status={
						run.status.toLowerCase() as
							| "pending"
							| "running"
							| "completed"
							| "failed"
					}
				/>
			</div>
		</div>
	);
};
