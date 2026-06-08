// src/components/genome/GeneDiscoveryNotification.tsx

import { useQueryClient } from "@tanstack/react-query";
import { Sparkles } from "lucide-react";
import { useEffect } from "react";
import { useTranslation } from "react-i18next";
import { useToast } from "@/components/ui/use-toast";
import { useAuth } from "@/context/AuthContext";
import { useWebSocket } from "@/context/WebSocketProvider";

export const GeneDiscoveryNotification = () => {
	const { t } = useTranslation(["common"]);
	const { subscribe, unsubscribe } = useWebSocket();
	const { toast } = useToast();
	const queryClient = useQueryClient();
	const { user } = useAuth();

	useEffect(() => {
		if (!user?.id) return;

		const channel = `user:${user.id}:notifications`;

		const handleNotification = (payload: unknown) => {
			const notification = payload as {
				type?: string;
				gene?: { rarity: number; name: string; components: string[] };
			};
			if (!notification.gene) return;
			if (notification.type === "gene_discovered") {
				const gene = notification.gene;

				// Determine rarity tier for styling
				let rarityTier = "COMMON";
				let rarityColor = "text-gray-500";

				if (gene.rarity < 1.0) {
					rarityTier = "LEGENDARY";
					rarityColor = "text-yellow-500";
				} else if (gene.rarity < 5.0) {
					rarityTier = "EPIC";
					rarityColor = "text-purple-500";
				} else if (gene.rarity < 20.0) {
					rarityTier = "RARE";
					rarityColor = "text-blue-500";
				}

				// Show toast notification with animation
				toast({
					title: (
						<div className="flex items-center gap-2">
							<Sparkles className="w-5 h-5 text-yellow-500 animate-pulse" />
							<span>{t("common:newGeneDiscoveredTitle")}</span>
						</div>
					) as unknown as string,
					description: (
						<div className="space-y-2">
							<p className={`font-bold italic ${rarityColor}`}>{gene.name}</p>
							<div className="flex flex-wrap gap-1">
								{gene.components.map((comp: string) => (
									<span
										key={comp}
										className="text-xs bg-secondary px-2 py-1 rounded"
									>
										{comp}
									</span>
								))}
							</div>
							<p className="text-xs text-muted-foreground">
								{t("common:newGeneDiscoveredRarity")}:{" "}
								<span className={rarityColor}>{rarityTier}</span> (
								{gene.rarity.toFixed(2)}%)
							</p>
						</div>
					) as unknown as string,
					duration: 8000,
				});

				// Invalidate queries to refresh gene data
				queryClient.invalidateQueries({ queryKey: ["genes"] });
			}
		};

		subscribe(channel, handleNotification);

		return () => {
			unsubscribe(channel, handleNotification);
		};
	}, [user?.id, subscribe, unsubscribe, toast, queryClient, t]);

	return null; // This component doesn't render anything
};
