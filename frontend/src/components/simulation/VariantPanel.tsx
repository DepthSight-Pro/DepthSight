// frontend/src/components/simulation/VariantPanel.tsx
// Panel for managing and selecting strategy variants

import {
	ChevronDown,
	ChevronUp,
	Copy,
	Plus,
	Settings,
	Trash2,
} from "lucide-react";
import type React from "react";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import {
	Tooltip,
	TooltipContent,
	TooltipProvider,
	TooltipTrigger,
} from "@/components/ui/tooltip";
import { useSimulationStore } from "./simulationStore";
import {
	BUILT_IN_VARIANTS,
	type CustomVariant,
	generateVariantDescription,
	MAX_VARIANTS,
} from "./types";
import { VariantBuilder } from "./VariantBuilder";

interface VariantPanelProps {
	compact?: boolean;
}

export const VariantPanel: React.FC<VariantPanelProps> = ({
	compact = false,
}) => {
	const { t } = useTranslation("simulation");
	const {
		selectedVariants,
		toggleVariant,
		customVariants,
		addCustomVariant,
		updateCustomVariant,
		removeCustomVariant,
		duplicateVariant,
		canAddVariant,
	} = useSimulationStore();

	const [isBuilderOpen, setIsBuilderOpen] = useState(false);
	const [editingVariant, setEditingVariant] = useState<CustomVariant | null>(
		null,
	);
	const [expanded, setExpanded] = useState(true);

	const allVariants = [...BUILT_IN_VARIANTS, ...customVariants];

	const handleEditVariant = (variant: CustomVariant) => {
		setEditingVariant(variant);
		setIsBuilderOpen(true);
	};

	const handleCreateNew = () => {
		setEditingVariant(null);
		setIsBuilderOpen(true);
	};

	const handleSaveVariant = (variant: CustomVariant) => {
		if (editingVariant) {
			updateCustomVariant(variant.id, variant);
		} else {
			addCustomVariant(variant);
			// Auto-select new variant
			if (!selectedVariants.includes(variant.id)) {
				toggleVariant(variant.id);
			}
		}
	};

	if (compact) {
		return (
			<div className="space-y-2">
				<div className="flex items-center justify-between">
					<span className="text-xs font-medium text-muted-foreground">
						Variants ({selectedVariants.length}/{MAX_VARIANTS})
					</span>
					<Button
						variant="ghost"
						size="sm"
						className="h-6 px-2"
						onClick={handleCreateNew}
						disabled={!canAddVariant()}
					>
						<Plus size={12} className="mr-1" /> New
					</Button>
				</div>
				<div className="flex flex-wrap gap-1">
					{allVariants.map((variant) => (
						<button
							key={variant.id}
							onClick={() => toggleVariant(variant.id)}
							className={`px-2 py-1 text-[10px] rounded-full border transition-all ${
								selectedVariants.includes(variant.id)
									? "bg-primary/20 border-primary text-primary"
									: "bg-muted/30 border-border text-muted-foreground hover:border-primary/50"
							}`}
							style={{
								borderColor: selectedVariants.includes(variant.id)
									? variant.color
									: undefined,
								color: selectedVariants.includes(variant.id)
									? variant.color
									: undefined,
							}}
						>
							{variant.name}
						</button>
					))}
				</div>

				<VariantBuilder
					isOpen={isBuilderOpen}
					onClose={() => setIsBuilderOpen(false)}
					variant={editingVariant}
					onSave={handleSaveVariant}
					existingIds={allVariants.map((v) => v.id)}
				/>
			</div>
		);
	}

	return (
		<div className="border rounded-lg bg-card">
			{/* Header */}
			<button
				onClick={() => setExpanded(!expanded)}
				className="w-full flex items-center justify-between p-3 hover:bg-muted/30 transition-colors"
			>
				<div className="flex items-center gap-2">
					<span className="text-sm font-bold">Strategy Variants</span>
					<span className="text-xs px-2 py-0.5 bg-primary/20 text-primary rounded-full">
						{selectedVariants.length}/{MAX_VARIANTS}
					</span>
				</div>
				{expanded ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
			</button>

			{expanded && (
				<div className="p-3 pt-0 space-y-3">
					{/* Built-in Variants */}
					<div>
						<span className="text-[10px] font-bold uppercase text-muted-foreground tracking-widest">
							{t("builtInPresets", "Built-in Presets")}
						</span>
						<div className="grid grid-cols-2 gap-1.5 mt-2">
							{BUILT_IN_VARIANTS.map((variant) => (
								<TooltipProvider key={variant.id}>
									<Tooltip>
										<TooltipTrigger asChild>
											<div
												onClick={() => toggleVariant(variant.id)}
												className={`p-2 rounded-lg border cursor-pointer transition-all group relative ${
													selectedVariants.includes(variant.id)
														? "bg-primary/10 border-primary"
														: "bg-muted/20 border-border hover:border-primary/50"
												}`}
												style={{
													borderColor: selectedVariants.includes(variant.id)
														? variant.color
														: undefined,
												}}
											>
												<div className="flex items-center justify-between gap-1">
													<div className="flex items-center gap-1 min-w-0">
														<span
															className="w-2 h-2 rounded-full flex-shrink-0"
															style={{ backgroundColor: variant.color }}
														/>
														<span className="text-xs font-medium truncate">
															{variant.name}
														</span>
													</div>

													{/* Duplicate button - always visible */}
													<button
														onClick={(e) => {
															e.stopPropagation();
															duplicateVariant(variant.id);
														}}
														className="p-0.5 hover:bg-primary/20 rounded transition-colors flex-shrink-0"
														disabled={!canAddVariant()}
														title={t(
															"duplicateToEdit",
															"Duplicate to customize",
														)}
													>
														<Copy
															size={10}
															className="opacity-50 hover:opacity-100"
														/>
													</button>
												</div>
											</div>
										</TooltipTrigger>
										<TooltipContent>
											<p className="text-xs font-medium mb-1">{variant.name}</p>
											<p className="text-[10px] text-muted-foreground">
												{generateVariantDescription(variant)}
											</p>
											<p className="text-[10px] text-primary/80 mt-1">
												💡{" "}
												{t(
													"clickCopyToCustomize",
													"Click copy icon to customize",
												)}
											</p>
										</TooltipContent>
									</Tooltip>
								</TooltipProvider>
							))}
						</div>
					</div>

					{/* Custom Variants */}
					{customVariants.length > 0 && (
						<div>
							<span className="text-[10px] font-bold uppercase text-muted-foreground tracking-widest">
								{t("customVariants", "Custom Variants")}
							</span>
							<div className="grid grid-cols-2 gap-2 mt-2">
								{customVariants.map((variant) => (
									<TooltipProvider key={variant.id}>
										<Tooltip>
											<TooltipTrigger asChild>
												<div
													onClick={() => toggleVariant(variant.id)}
													className={`p-2 rounded-lg border cursor-pointer transition-all group relative ${
														selectedVariants.includes(variant.id)
															? "bg-primary/10 border-primary"
															: "bg-muted/20 border-border hover:border-primary/50"
													}`}
													style={{
														borderColor: selectedVariants.includes(variant.id)
															? variant.color
															: undefined,
													}}
												>
													<div className="flex items-center gap-1">
														<span
															className="w-2 h-2 rounded-full"
															style={{ backgroundColor: variant.color }}
														/>
														<span className="text-xs font-medium truncate">
															{variant.name}
														</span>
													</div>
													{/* Auto-generated description preview */}
													<p className="text-[9px] text-muted-foreground truncate mt-0.5">
														{generateVariantDescription(variant)
															.split(" • ")
															.slice(0, 2)
															.join(" • ")}
													</p>

													{/* Actions */}
													<div className="absolute top-1 right-1 flex gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
														<button
															onClick={(e) => {
																e.stopPropagation();
																handleEditVariant(variant);
															}}
															className="p-1 bg-muted rounded hover:bg-primary/20"
														>
															<Settings size={10} />
														</button>
														<button
															onClick={(e) => {
																e.stopPropagation();
																removeCustomVariant(variant.id);
															}}
															className="p-1 bg-muted rounded hover:bg-rose-500/20"
														>
															<Trash2 size={10} />
														</button>
													</div>
												</div>
											</TooltipTrigger>
											<TooltipContent>
												<p className="text-xs font-medium mb-1">
													{variant.name}
												</p>
												<p className="text-[10px] text-muted-foreground">
													{generateVariantDescription(variant)}
												</p>
											</TooltipContent>
										</Tooltip>
									</TooltipProvider>
								))}
							</div>
						</div>
					)}

					{/* Add New Button */}
					<Button
						variant="outline"
						size="sm"
						className="w-full"
						onClick={handleCreateNew}
						disabled={!canAddVariant()}
					>
						<Plus size={14} className="mr-1" />
						{t("createCustomVariant", "Create Custom Variant")}
						{!canAddVariant() && (
							<span className="ml-1 text-xs text-muted-foreground">
								({t("maxVariantsReached", "max")} {MAX_VARIANTS})
							</span>
						)}
					</Button>
				</div>
			)}

			{/* Variant Builder Modal */}
			<VariantBuilder
				isOpen={isBuilderOpen}
				onClose={() => setIsBuilderOpen(false)}
				variant={editingVariant}
				onSave={handleSaveVariant}
				existingIds={allVariants.map((v) => v.id)}
			/>
		</div>
	);
};

export default VariantPanel;
