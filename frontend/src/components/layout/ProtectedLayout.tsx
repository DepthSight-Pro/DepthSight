import type React from "react";
import { Outlet } from "react-router-dom";
import { AppHeader } from "@/components/AppHeader";
import { AppSidebar } from "@/components/AppSidebar";
import { SteamAchievementNotification } from "@/components/achievements/SteamAchievementNotification";
import { ImpersonationBanner } from "@/components/admin/ImpersonationBanner";
import { AiCopilotWidget } from "@/components/common/AiCopilotWidget";

export const ProtectedLayout: React.FC = () => {

	return (
		<div className="relative flex h-screen w-screen overflow-hidden bg-void text-white">
			{/* Ambient background glows */}
			<div className="pointer-events-none absolute inset-0 grid-bg opacity-40" />
			<div className="pointer-events-none absolute -top-40 left-1/3 h-[520px] w-[720px] rounded-full bg-azure/10 blur-[140px]" />
			<div className="pointer-events-none absolute -bottom-40 right-0 h-[420px] w-[520px] rounded-full bg-cyan/8 blur-[140px]" />

			<AppSidebar />
			<div className="relative flex min-w-0 flex-1 flex-col overflow-hidden">
				<AppHeader />
				<main className="relative flex-1 overflow-y-auto overflow-x-hidden flex flex-col">
					<Outlet />
				</main>
				<ImpersonationBanner />
			</div>
			<AiCopilotWidget />
			<SteamAchievementNotification />
		</div>
	);
};
