// src/pages/Index.tsx

import { Home } from "lucide-react";
import { useTranslation } from "react-i18next";
import { ActivePositionsTable } from "@/components/dashboard/ActivePositionsTable";
import { LiveEventFeed } from "@/components/dashboard/LiveEventFeed";
import { PortfolioOverviewWidget } from "@/components/dashboard/PortfolioOverviewWidget";
import { SystemStatus } from "@/components/dashboard/SystemStatus";
import { TopStrategiesTable } from "@/components/dashboard/TopStrategiesTable";
import { TotalPnl } from "@/components/dashboard/TotalPnl";
import { PageLayout } from "@/components/layout/PageLayout";

const Index = () => {
	const { t } = useTranslation("index");

	return (
		<PageLayout title={t("pageTitle")} icon={Home}>
			<div className="space-y-6">
				<PortfolioOverviewWidget />
				<div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
					<div className="lg:col-span-2">
						<TotalPnl />
					</div>
					<SystemStatus />
				</div>
				<ActivePositionsTable />
				<div className="grid grid-cols-1 md:grid-cols-2 gap-6">
					<TopStrategiesTable />
					<LiveEventFeed />
				</div>
			</div>
		</PageLayout>
	);
};
export default Index;
