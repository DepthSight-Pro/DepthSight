// src/components/genome/GeneDetailsModal.tsx

import { Calendar, Dna, TrendingUp, User } from "lucide-react";
import type React from "react";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
	Dialog,
	DialogContent,
	DialogDescription,
	DialogHeader,
	DialogTitle,
} from "@/components/ui/dialog";
import type { Gene } from "@/types/api";
import { StrategyDNA } from "./StrategyDNA";

interface GeneDetailsModalProps {
	gene: Gene | null;
	isOpen: boolean;
	onClose: () => void;
	unlockedAt?: string;
	sourceType?: string;
}

const getRarityTier = (rarity: number): string => {
	if (rarity < 1.0) return "LEGENDARY";
	if (rarity < 5.0) return "EPIC";
	if (rarity < 20.0) return "RARE";
	return "COMMON";
};

const getRarityColor = (tier: string) => {
	switch (tier) {
		case "LEGENDARY":
			return "text-yellow-500 border-yellow-500";
		case "EPIC":
			return "text-purple-500 border-purple-500";
		case "RARE":
			return "text-blue-500 border-blue-500";
		default:
			return "text-gray-500 border-gray-500";
	}
};

export const GeneDetailsModal: React.FC<GeneDetailsModalProps> = ({
	gene,
	isOpen,
	onClose,
	unlockedAt,
	sourceType,
}) => {
	if (!gene) return null;

	const rarityTier = getRarityTier(gene.rarity);
	const rarityColor = getRarityColor(rarityTier);

	return (
		<Dialog open={isOpen} onOpenChange={onClose}>
			<DialogContent className="max-w-3xl max-h-[90vh] overflow-y-auto">
				<DialogHeader>
					<DialogTitle className="flex items-center gap-2 text-2xl">
						<Dna className="w-6 h-6 text-green-500" />
						{gene.name}
					</DialogTitle>
					<DialogDescription>{gene.description}</DialogDescription>
				</DialogHeader>

				<div className="space-y-6 mt-4">
					{/* Rarity and Stats */}
					<div className="grid grid-cols-2 md:grid-cols-4 gap-4">
						<Card>
							<CardHeader className="pb-2">
								<CardTitle className="text-xs text-muted-foreground">
									Rarity
								</CardTitle>
							</CardHeader>
							<CardContent>
								<Badge className={`${rarityColor} text-lg`} variant="outline">
									{rarityTier}
								</Badge>
								<div className="text-xs text-muted-foreground mt-1">
									{gene.rarity.toFixed(2)}%
								</div>
							</CardContent>
						</Card>

						<Card>
							<CardHeader className="pb-2">
								<CardTitle className="text-xs text-muted-foreground">
									Components
								</CardTitle>
							</CardHeader>
							<CardContent>
								<div className="text-2xl font-bold text-green-500">
									{gene.components.length}
								</div>
							</CardContent>
						</Card>

						{unlockedAt && (
							<Card>
								<CardHeader className="pb-2">
									<CardTitle className="text-xs text-muted-foreground">
										Discovered
									</CardTitle>
								</CardHeader>
								<CardContent>
									<div className="text-sm">
										{new Date(unlockedAt).toLocaleDateString()}
									</div>
								</CardContent>
							</Card>
						)}

						{sourceType && (
							<Card>
								<CardHeader className="pb-2">
									<CardTitle className="text-xs text-muted-foreground">
										Source
									</CardTitle>
								</CardHeader>
								<CardContent>
									<Badge variant="outline">{sourceType}</Badge>
								</CardContent>
							</Card>
						)}
					</div>

					{/* DNA Visualization */}
					<div>
						<h3 className="text-sm font-semibold mb-3 flex items-center gap-2">
							<Dna className="w-4 h-4" />
							DNA Structure
						</h3>
						<StrategyDNA />
					</div>

					{/* Components List */}
					<div>
						<h3 className="text-sm font-semibold mb-3">Component Breakdown</h3>
						<div className="flex flex-wrap gap-2">
							{gene.components.map((component, index) => (
								<Badge key={index} variant="secondary" className="text-sm">
									{component}
								</Badge>
							))}
						</div>
					</div>

					{/* Metadata (if available) */}
					{gene.metadata && (
						<Card className="bg-secondary/50">
							<CardHeader className="pb-3">
								<CardTitle className="text-sm flex items-center gap-2">
									<TrendingUp className="w-4 h-4" />
									Performance Context
								</CardTitle>
							</CardHeader>
							<CardContent className="grid grid-cols-2 gap-4 text-sm">
								{gene.metadata.market_regime && (
									<div>
										<span className="text-muted-foreground">
											Market Regime:
										</span>
										<div className="font-medium capitalize">
											{gene.metadata.market_regime.replace("_", " ")}
										</div>
									</div>
								)}
								{gene.metadata.win_rate !== undefined && (
									<div>
										<span className="text-muted-foreground">Win Rate:</span>
										<div className="font-medium text-green-500">
											{gene.metadata.win_rate.toFixed(1)}%
										</div>
									</div>
								)}
								{gene.metadata.avg_pnl !== undefined && (
									<div>
										<span className="text-muted-foreground">Avg PnL:</span>
										<div
											className={`font-medium ${gene.metadata.avg_pnl > 0 ? "text-green-500" : "text-red-500"}`}
										>
											${gene.metadata.avg_pnl.toFixed(2)}
										</div>
									</div>
								)}
								{gene.metadata.avg_volatility !== undefined && (
									<div>
										<span className="text-muted-foreground">
											Avg Volatility:
										</span>
										<div className="font-medium">
											{gene.metadata.avg_volatility.toFixed(2)}%
										</div>
									</div>
								)}
							</CardContent>
						</Card>
					)}

					{/* First Discovery Info */}
					{gene.discoveredAt && (
						<div className="text-xs text-muted-foreground flex items-center gap-2">
							<Calendar className="w-3 h-3" />
							First discovered on{" "}
							{new Date(gene.discoveredAt).toLocaleDateString()}
							{gene.firstDiscoveredBy && (
								<>
									<User className="w-3 h-3 ml-2" />
									by User #{gene.firstDiscoveredBy}
								</>
							)}
						</div>
					)}
				</div>
			</DialogContent>
		</Dialog>
	);
};
