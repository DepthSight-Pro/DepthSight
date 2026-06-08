// src/pages/LaboratoryPage.tsx

import { Dna, Filter, Search, Shuffle, Sparkles } from "lucide-react";
import type React from "react";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { BreedingLab } from "@/components/genome/BreedingLab";
import { EvolutionTree } from "@/components/genome/EvolutionTree";
import { GeneDetailsModal } from "@/components/genome/GeneDetailsModal";
import { PageLayout } from "@/components/layout/PageLayout";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import {
	Card,
	CardContent,
	CardDescription,
	CardHeader,
	CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import {
	Select,
	SelectContent,
	SelectItem,
	SelectTrigger,
	SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useGeneStats, useMyGenes } from "@/lib/api";
import type { Gene, RarityTier } from "@/types/api";

const getRarityTier = (rarity: number): RarityTier => {
	if (rarity < 1.0) return "LEGENDARY";
	if (rarity < 5.0) return "EPIC";
	if (rarity < 20.0) return "RARE";
	return "COMMON";
};

const getRarityColor = (tier: RarityTier) => {
	switch (tier) {
		case "LEGENDARY":
			return "bg-gradient-to-r from-yellow-500 to-orange-500";
		case "EPIC":
			return "bg-gradient-to-r from-purple-500 to-pink-500";
		case "RARE":
			return "bg-gradient-to-r from-blue-500 to-cyan-500";
		default:
			return "bg-gray-500";
	}
};

const LaboratoryPage: React.FC = () => {
	const { t } = useTranslation("laboratory");
	const [now] = useState(() => Date.now());
	const { data: genesData, isLoading: genesLoading } = useMyGenes();
	const { data: stats, isLoading: statsLoading } = useGeneStats();

	// Filters and search
	const [searchQuery, setSearchQuery] = useState("");
	const [rarityFilter, setRarityFilter] = useState<RarityTier | "ALL">("ALL");
	const [sortBy, setSortBy] = useState<"rarity" | "recent" | "name">("recent");
	const [selectedGene, setSelectedGene] = useState<{
		gene: Gene;
		unlockedAt: string;
		sourceType?: string;
	} | null>(null);

	// Filter and sort genes
	const filteredGenes = useMemo(() => {
		if (!genesData?.genes) return [];

		let filtered = [...genesData.genes];

		// Apply search
		if (searchQuery) {
			const query = searchQuery.toLowerCase();
			filtered = filtered.filter(
				(ug) =>
					ug.gene.name.toLowerCase().includes(query) ||
					ug.gene.description?.toLowerCase().includes(query) ||
					ug.gene.components.some((c) => c.toLowerCase().includes(query)),
			);
		}

		// Apply rarity filter
		if (rarityFilter !== "ALL") {
			filtered = filtered.filter(
				(ug) => getRarityTier(ug.gene.rarity) === rarityFilter,
			);
		}

		// Apply sorting
		filtered.sort((a, b) => {
			switch (sortBy) {
				case "rarity":
					return a.gene.rarity - b.gene.rarity; // Lower rarity % = more rare
				case "name":
					return a.gene.name.localeCompare(b.gene.name);
				default:
					return (
						new Date(b.unlockedAt).getTime() - new Date(a.unlockedAt).getTime()
					);
			}
		});

		return filtered;
	}, [genesData, searchQuery, rarityFilter, sortBy]);

	return (
		<PageLayout title={t("title")} icon={Dna} description={t("description")}>
			<Tabs defaultValue="library" className="space-y-6">
				<TabsList className="grid w-full grid-cols-3">
					<TabsTrigger value="library" className="flex items-center gap-2">
						<Dna className="w-4 h-4" />
						{t("gene_library_tab")}
					</TabsTrigger>
					<TabsTrigger value="breeding" className="flex items-center gap-2">
						<Shuffle className="w-4 h-4" />
						{t("breeding_lab_tab")}
					</TabsTrigger>
				</TabsList>

				{/* Gene Library Tab */}
				<TabsContent value="library" className="space-y-6">
					{/* Stats Overview */}
					<div className="grid grid-cols-1 md:grid-cols-5 gap-4">
						<Card>
							<CardHeader className="pb-2">
								<CardTitle className="text-sm font-medium text-muted-foreground">
									{t("genes_discovered_stat")}
								</CardTitle>
							</CardHeader>
							<CardContent>
								{statsLoading ? (
									<Skeleton className="h-8 w-20" />
								) : (
									<div className="text-3xl font-bold text-green-500">
										{stats?.totalGenesDiscovered || 0}
									</div>
								)}
								<p className="text-xs text-muted-foreground mt-1">
									{t("of_stat")} {stats?.totalGenesInSystem || 0}{" "}
									{t("total_stat")}
								</p>
							</CardContent>
						</Card>

						{["LEGENDARY", "EPIC", "RARE", "COMMON"].map((tier) => (
							<Card key={tier}>
								<CardHeader className="pb-2">
									<CardTitle className="text-sm font-medium text-muted-foreground">
										{t(`${tier.toLowerCase()}_rarity`)}
									</CardTitle>
								</CardHeader>
								<CardContent>
									{statsLoading ? (
										<Skeleton className="h-8 w-12" />
									) : (
										<div
											className={`text-3xl font-bold ${
												tier === "LEGENDARY"
													? "text-yellow-500"
													: tier === "EPIC"
														? "text-purple-500"
														: tier === "RARE"
															? "text-blue-500"
															: "text-gray-500"
											}`}
										>
											{stats?.rarityBreakdown?.[tier as RarityTier] || 0}
										</div>
									)}
								</CardContent>
							</Card>
						))}
					</div>

					<EvolutionTree />

					{/* Filters and Search */}
					<Card>
						<CardHeader>
							<div className="flex flex-col md:flex-row md:items-center md:justify-between gap-4">
								<div className="flex-1">
									<div className="relative">
										<Search className="absolute left-3 top-3 h-4 w-4 text-muted-foreground" />
										<Input
											placeholder={t("search_placeholder")}
											value={searchQuery}
											onChange={(e) => setSearchQuery(e.target.value)}
											className="pl-10"
										/>
									</div>
								</div>
								<div className="flex gap-2">
									<Select
										value={rarityFilter}
										onValueChange={(v) =>
											setRarityFilter(v as RarityTier | "ALL")
										}
									>
										<SelectTrigger className="w-[140px]">
											<Filter className="w-4 h-4 mr-2" />
											<SelectValue />
										</SelectTrigger>
										<SelectContent>
											<SelectItem value="ALL">
												{t("all_rarity_filter")}
											</SelectItem>
											<SelectItem value="LEGENDARY">
												{t("legendary_filter")}
											</SelectItem>
											<SelectItem value="EPIC">{t("epic_filter")}</SelectItem>
											<SelectItem value="RARE">{t("rare_filter")}</SelectItem>
											<SelectItem value="COMMON">
												{t("common_filter")}
											</SelectItem>
										</SelectContent>
									</Select>
									<Select
										value={sortBy}
										onValueChange={(v) =>
											setSortBy(v as "rarity" | "recent" | "name")
										}
									>
										<SelectTrigger className="w-[140px]">
											<SelectValue />
										</SelectTrigger>
										<SelectContent>
											<SelectItem value="recent">
												{t("sort_by_recent")}
											</SelectItem>
											<SelectItem value="rarity">
												{t("sort_by_rarity")}
											</SelectItem>
											<SelectItem value="name">{t("sort_by_name")}</SelectItem>
										</SelectContent>
									</Select>
								</div>
							</div>
						</CardHeader>
					</Card>

					{/* Genes Grid */}
					<Card>
						<CardHeader>
							<CardTitle className="flex items-center gap-2">
								<Dna className="w-5 h-5" />
								{t("discovered_genes_title")} ({filteredGenes.length})
							</CardTitle>
							<CardDescription>
								{t("discovered_genes_description")}
							</CardDescription>
						</CardHeader>
						<CardContent>
							{genesLoading ? (
								<div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
									{[...Array(6)].map((_, i) => (
										<Skeleton key={i} className="h-40" />
									))}
								</div>
							) : filteredGenes.length === 0 ? (
								<Alert>
									<Sparkles className="h-4 w-4" />
									<AlertDescription>
										{searchQuery || rarityFilter !== "ALL"
											? t("no_genes_filtered_message")
											: t("no_genes_discovered_message")}
									</AlertDescription>
								</Alert>
							) : (
								<div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
									{filteredGenes.map((userGene) => {
										const gene = userGene.gene;
										const rarityTier = getRarityTier(gene.rarity);
										const rarityColor = getRarityColor(rarityTier);

										// Check if gene was discovered recently (within 5 minutes)
										const isNewlyDiscovered =
											userGene.unlockedAt &&
											now - new Date(userGene.unlockedAt).getTime() <
												5 * 60 * 1000;

										return (
											<Card
												key={userGene.id}
												className={`hover:shadow-lg transition-all cursor-pointer border-2 hover:border-primary ${
													isNewlyDiscovered
														? "animate-in fade-in zoom-in duration-500"
														: ""
												}`}
												onClick={() =>
													setSelectedGene({
														gene,
														unlockedAt: userGene.unlockedAt,
														sourceType: userGene.sourceType || undefined,
													})
												}
											>
												<div
													className={`h-1 ${rarityColor} ${isNewlyDiscovered ? "animate-pulse" : ""}`}
												/>
												<CardHeader className="pb-3">
													<div className="flex items-start justify-between">
														<CardTitle className="text-base font-bold italic text-green-400 flex items-center gap-2">
															{gene.name}
															{isNewlyDiscovered && (
																<Sparkles className="w-4 h-4 text-yellow-500 animate-pulse" />
															)}
														</CardTitle>
														<Badge variant="outline" className="text-xs">
															{t(`${rarityTier.toLowerCase()}_rarity`)}
														</Badge>
													</div>
													{gene.description && (
														<CardDescription className="text-xs">
															{gene.description}
														</CardDescription>
													)}
												</CardHeader>
												<CardContent className="space-y-3">
													<div className="flex flex-wrap gap-1">
														{gene.components.map((component) => (
															<Badge
																key={component}
																variant="secondary"
																className="text-xs"
															>
																{component}
															</Badge>
														))}
													</div>
													<div className="flex justify-between text-xs text-muted-foreground pt-2 border-t">
														<span>
															{t("rarity_label")}: {gene.rarity.toFixed(2)}%
														</span>
														<span>
															{userGene.sourceType && (
																<Badge variant="outline" className="text-xs">
																	{userGene.sourceType}
																</Badge>
															)}
														</span>
													</div>
												</CardContent>
											</Card>
										);
									})}
								</div>
							)}
						</CardContent>
					</Card>
				</TabsContent>

				{/* Breeding Lab Tab */}
				<TabsContent value="breeding">
					<BreedingLab />
				</TabsContent>
			</Tabs>

			{/* Gene Details Modal */}
			<GeneDetailsModal
				gene={selectedGene?.gene || null}
				isOpen={!!selectedGene}
				onClose={() => setSelectedGene(null)}
				unlockedAt={selectedGene?.unlockedAt}
				sourceType={selectedGene?.sourceType}
			/>
		</PageLayout>
	);
};

export default LaboratoryPage;
