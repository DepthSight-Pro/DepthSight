// src/components/layout/ProtectedLayout.tsx

import type React from "react";
import { useEffect } from "react";
import { useTranslation } from "react-i18next";
import { Outlet } from "react-router-dom";
import { AppHeader } from "@/components/AppHeader";
import { AppSidebar } from "@/components/AppSidebar";
import { ImpersonationBanner } from "@/components/admin/ImpersonationBanner";
import { AiCopilotWidget } from "@/components/common/AiCopilotWidget";
import { useToast } from "@/components/ui/use-toast";
import { useWebSocket } from "@/context/WebSocketProvider";
import type { Achievement } from "@/types/api";

export const ProtectedLayout: React.FC = () => {
	const { subscribe, unsubscribe } = useWebSocket();
	const { toast } = useToast();
	const { t } = useTranslation(["common"]);

	useEffect(() => {
		const handleAchievementUnlocked = (payload: unknown) => {
			const achievement = payload as Achievement;
			toast({
				title: t("common:achievementUnlockedTitle"),
				description: t("common:achievementUnlockedDescription", {
					name: achievement.name,
					xp_reward: achievement.xp_reward,
				}),
			});
		};

		subscribe("achievement_unlocked", handleAchievementUnlocked);

		return () => {
			unsubscribe("achievement_unlocked", handleAchievementUnlocked);
		};
	}, [subscribe, unsubscribe, toast, t]);

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
		</>
	);
};
