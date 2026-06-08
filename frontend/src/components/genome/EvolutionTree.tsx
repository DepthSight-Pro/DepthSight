// src/components/genome/EvolutionTree.tsx

import {
	Background,
	BackgroundVariant,
	Controls,
	type Edge,
	MarkerType,
	type Node,
	type NodeProps,
	Position,
	ReactFlow,
	useEdgesState,
	useNodesState,
} from "@xyflow/react";
import React, { useMemo, useState } from "react";
import "@xyflow/react/dist/style.css";
import { AlertCircle, GitBranch, Sparkles } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import {
	Card,
	CardContent,
	CardDescription,
	CardHeader,
	CardTitle,
} from "@/components/ui/card";
import {
	Select,
	SelectContent,
	SelectItem,
	SelectTrigger,
	SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { useStrategyLineage, useStrategyLineages } from "@/lib/api";

interface StrategyNodeData {
	name: string;
	generation: number;
	source_mutation?: string;
	created_at: string;
	is_current: boolean;
	[key: string]: unknown; // For React Flow compatibility
}

// Custom Node Component
const StrategyNode: React.FC<NodeProps<Node<StrategyNodeData>>> = ({
	data,
}) => {
	const { t } = useTranslation("laboratory"); // Hook for translation
	const isCurrent = data.is_current;
	const isRoot = data.generation === 1;

	return (
		<div
			className={`px-4 py-3 rounded-lg border-2 shadow-lg transition-all ${
				isCurrent
					? "border-green-500 bg-green-500/10 shadow-green-500/20"
					: isRoot
						? "border-blue-500 bg-blue-500/10 shadow-blue-500/20"
						: "border-purple-500 bg-purple-500/10 shadow-purple-500/20"
			}`}
			style={{ minWidth: 200 }}
		>
			<div className="flex items-start justify-between gap-2">
				<div className="flex-1 min-w-0">
					<div className="font-semibold text-sm truncate">
						{String(data.name)}
					</div>
					<div className="text-xs text-muted-foreground mt-1">
						{t("evolutionTree.generation_label", { gen: data.generation })}
					</div>
					{data.source_mutation && (
						<Badge variant="outline" className="text-xs mt-1">
							{String(data.source_mutation)}
						</Badge>
					)}
				</div>
				{!!isCurrent && (
					<Badge className="bg-green-500 text-white text-xs">
						{t("evolutionTree.active_badge")}
					</Badge>
				)}
				{!!isRoot && !isCurrent && (
					<Badge variant="outline" className="text-xs">
						{t("evolutionTree.root_badge")}
					</Badge>
				)}
			</div>
		</div>
	);
};

const nodeTypes = {
	strategyNode: StrategyNode,
};

export const EvolutionTree: React.FC = () => {
	const { t } = useTranslation("laboratory");
	const [selectedLineage, setSelectedLineage] = useState<string | null>(null);

	const { data: lineages, isLoading: lineagesLoading } = useStrategyLineages();
	const { data: lineageData, isLoading: lineageLoading } =
		useStrategyLineage(selectedLineage);

	// Convert backend data to react-flow format
	const { nodes, edges } = useMemo(() => {
		if (!lineageData) return { nodes: [], edges: [] };

		// Calculate layout using Dagre-like algorithm (simplified)
		const nodesByGeneration = new Map<number, typeof lineageData.nodes>();

		// Group nodes by generation
		lineageData.nodes.forEach((node) => {
			if (!nodesByGeneration.has(node.generation)) {
				nodesByGeneration.set(node.generation, []);
			}
			nodesByGeneration.get(node.generation)?.push(node);
		});

		// Calculate positions
		const horizontalSpacing = 280;
		const verticalSpacing = 120;

		const reactFlowNodes: Node[] = lineageData.nodes.map((node) => {
			const generationNodes = nodesByGeneration.get(node.generation) || [];
			const indexInGeneration = generationNodes.findIndex(
				(n) => n.id === node.id,
			);
			const totalInGeneration = generationNodes.length;

			// Center nodes in their generation
			const xOffset = ((totalInGeneration - 1) * horizontalSpacing) / 2;

			return {
				id: node.id,
				type: "strategyNode",
				position: {
					x: indexInGeneration * horizontalSpacing - xOffset,
					y: (node.generation - 1) * verticalSpacing,
				},
				data: {
					name: node.name,
					generation: node.generation,
					source_mutation: node.source_mutation,
					created_at: node.created_at,
					is_current: node.is_current,
				},
				sourcePosition: Position.Bottom,
				targetPosition: Position.Top,
			};
		});

		const reactFlowEdges: Edge[] = lineageData.edges.map((edge, edgeIndex) => ({
			id: `edge-${edgeIndex}`,
			source: edge.from,
			target: edge.to,
			type: "smoothstep",
			animated: true,
			style: { stroke: "#8b5cf6", strokeWidth: 2 },
			markerEnd: {
				type: MarkerType.ArrowClosed,
				color: "#8b5cf6",
			},
		}));

		return { nodes: reactFlowNodes, edges: reactFlowEdges };
	}, [lineageData]);

	const [reactFlowNodes, setNodes, onNodesChange] = useNodesState(nodes);
	const [reactFlowEdges, setEdges, onEdgesChange] = useEdgesState(edges);

	// Update nodes when lineage data changes
	React.useEffect(() => {
		setNodes(nodes);
		setEdges(edges);
	}, [nodes, edges, setNodes, setEdges]);

	return (
		<div className="space-y-4">
			{/* Header Card */}
			<Card>
				<CardHeader>
					<CardTitle className="flex items-center gap-2">
						<GitBranch className="w-5 h-5" />
						{t("evolutionTree.title")}
					</CardTitle>
					<CardDescription>{t("evolutionTree.description")}</CardDescription>
				</CardHeader>
				<CardContent>
					<div className="space-y-4">
						<div className="flex items-center gap-4">
							<label className="text-sm font-medium min-w-fit">
								{t("evolutionTree.select_lineage_label")}
							</label>
							<Select
								value={selectedLineage || ""}
								onValueChange={(value) => setSelectedLineage(value || null)}
								disabled={lineagesLoading}
							>
								<SelectTrigger className="flex-1">
									<SelectValue
										placeholder={t("evolutionTree.select_lineage_placeholder")}
									/>
								</SelectTrigger>
								<SelectContent>
									{lineages?.map((lineage) => (
										<SelectItem key={lineage.id} value={lineage.id}>
											{lineage.name}{" "}
											{t("evolutionTree.lineage_item", {
												gen: lineage.generation,
												count: lineage.descendants_count || 0,
											})}
										</SelectItem>
									))}
								</SelectContent>
							</Select>
						</div>

						{selectedLineage && lineageData && (
							<Alert>
								<Sparkles className="h-4 w-4" />
								<AlertDescription>
									{t("evolutionTree.showing_stats", {
										count: lineageData.nodes.length,
										generations: Math.max(
											...lineageData.nodes.map((n) => n.generation),
										),
									})}
								</AlertDescription>
							</Alert>
						)}
					</div>
				</CardContent>
			</Card>

			{/* Tree Visualization */}
			<Card>
				<CardContent className="p-0">
					{!selectedLineage ? (
						<div className="h-[600px] flex items-center justify-center">
							<Alert className="max-w-md">
								<AlertCircle className="h-4 w-4" />
								<AlertDescription>
									{t("evolutionTree.alert_select_lineage")}
								</AlertDescription>
							</Alert>
						</div>
					) : lineageLoading ? (
						<div className="h-[600px] flex items-center justify-center">
							<Skeleton className="w-full h-full" />
						</div>
					) : reactFlowNodes.length === 0 ? (
						<div className="h-[600px] flex items-center justify-center">
							<Alert className="max-w-md">
								<AlertDescription>
									{t("evolutionTree.alert_no_data")}
								</AlertDescription>
							</Alert>
						</div>
					) : (
						<div className="h-[600px] bg-background">
							<ReactFlow
								nodes={reactFlowNodes}
								edges={reactFlowEdges}
								onNodesChange={onNodesChange}
								onEdgesChange={onEdgesChange}
								nodeTypes={nodeTypes}
								fitView
								fitViewOptions={{ padding: 0.2 }}
								minZoom={0.1}
								maxZoom={1.5}
							>
								<Background
									variant={BackgroundVariant.Dots}
									gap={12}
									size={1}
								/>
								<Controls />
							</ReactFlow>
						</div>
					)}
				</CardContent>
			</Card>

			{/* Legend */}
			{selectedLineage && reactFlowNodes.length > 0 && (
				<Card>
					<CardHeader className="pb-3">
						<CardTitle className="text-sm">
							{t("evolutionTree.legend_title")}
						</CardTitle>
					</CardHeader>
					<CardContent>
						<div className="flex flex-wrap gap-4 text-sm">
							<div className="flex items-center gap-2">
								<div className="w-4 h-4 rounded border-2 border-blue-500 bg-blue-500/10" />
								<span>{t("evolutionTree.legend_root")}</span>
							</div>
							<div className="flex items-center gap-2">
								<div className="w-4 h-4 rounded border-2 border-purple-500 bg-purple-500/10" />
								<span>{t("evolutionTree.legend_evolved")}</span>
							</div>
							<div className="flex items-center gap-2">
								<div className="w-4 h-4 rounded border-2 border-green-500 bg-green-500/10" />
								<span>{t("evolutionTree.legend_current")}</span>
							</div>
						</div>
					</CardContent>
				</Card>
			)}
		</div>
	);
};
