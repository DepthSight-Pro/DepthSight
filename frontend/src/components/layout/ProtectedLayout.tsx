import type React from "react";
import { Outlet } from "react-router-dom";
import { AppHeader } from "@/components/AppHeader";
import { AppSidebar } from "@/components/AppSidebar";
import { SteamAchievementNotification } from "@/components/achievements/SteamAchievementNotification";
import { ImpersonationBanner } from "@/components/admin/ImpersonationBanner";
import { AiCopilotWidget } from "@/components/common/AiCopilotWidget";

export const ProtectedLayout: React.FC = () => {
	return (
		<>
			<AppSidebar />
			<div className="flex flex-1 flex-col overflow-hidden">
				<AppHeader />
				<main className="flex-1 overflow-auto relative">
					<Outlet />
				</main>
				<ImpersonationBanner />
			</div>
			<AiCopilotWidget />
			<SteamAchievementNotification />
		</>
	);
};
