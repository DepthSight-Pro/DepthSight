// src/components/genome/StrategyDNA.tsx

import type React from "react";
import { useEffect, useRef } from "react";
import { Card } from "@/components/ui/card";

interface DNASegment {
	type: string;
	label: string;
	color: string;
}

interface StrategyDNAProps {
	config?: Record<string, unknown>;
	className?: string;
}

const extractDNAFromConfig = (
	config: Record<string, unknown> | undefined,
): DNASegment[] => {
	if (!config) return [];

	const segments: DNASegment[] = [];
	const filters = config.filters as
		| { conditions?: { type?: string }[] }
		| undefined;
	const entryConditions = config.entryConditions as
		| { conditions?: { type?: string }[] }
		| undefined;

	// Extract filters
	if (filters?.conditions) {
		filters.conditions.slice(0, 2).forEach((filter) => {
			segments.push({
				type: "filter",
				label: filter.type?.split("_")[0] || "Filter",
				color: "#3b82f6",
			});
		});
	}

	// Extract entry conditions
	if (entryConditions?.conditions) {
		entryConditions.conditions.slice(0, 3).forEach((condition) => {
			segments.push({
				type: "indicator",
				label: condition.type?.split("_")[0] || "Signal",
				color: "#8b5cf6",
			});
		});
	}

	// Extract management blocks
	if (config.positionManagement) {
		(config.positionManagement as { type?: string }[])
			.slice(0, 3)
			.forEach((block) => {
				segments.push({
					type: "management",
					label: block.type?.split("_")[0] || "Exit",
					color: "#f59e0b",
				});
			});
	}

	// Ensure we have at least 6 segments for a nice helix
	while (segments.length < 6) {
		segments.push({
			type: "base",
			label: "Base",
			color: "#6b7280",
		});
	}

	return segments.slice(0, 8); // Max 8 segments
};

export const StrategyDNA: React.FC<StrategyDNAProps> = ({
	config,
	className = "",
}) => {
	const canvasRef = useRef<HTMLDivElement>(null);
	const segments = extractDNAFromConfig(config);

	useEffect(() => {
		if (!canvasRef.current) return;

		const container = canvasRef.current;
		const segmentElements = container.querySelectorAll(".dna-segment");

		let rotation = 0;
		const animate = () => {
			rotation += 0.3;
			segmentElements.forEach((el, index) => {
				const element = el as HTMLElement;
				const angle =
					(index / segments.length) * Math.PI * 2 + (rotation * Math.PI) / 180;
				const x = Math.cos(angle) * 80;
				const y = (index / segments.length) * 280;
				const scale = 0.7 + Math.abs(Math.sin(angle)) * 0.3;
				const zIndex = Math.floor(scale * 100);

				element.style.transform = `translate(${x}px, ${y}px) scale(${scale})`;
				element.style.zIndex = zIndex.toString();
				element.style.opacity = (0.4 + scale * 0.6).toString();
			});

			requestAnimationFrame(animate);
		};

		const animationId = requestAnimationFrame(animate);
		return () => cancelAnimationFrame(animationId);
	}, [segments]);

	return (
		<Card className={`relative overflow-hidden ${className}`}>
			<div className="relative w-full h-[320px] flex items-center justify-center">
				<div
					ref={canvasRef}
					className="relative"
					style={{ width: "200px", height: "300px" }}
				>
					{segments.map((segment, index) => (
						<div
							key={index}
							className="dna-segment absolute left-1/2 -translate-x-1/2 transition-all duration-100"
							style={{
								width: "80px",
								height: "12px",
								borderRadius: "6px",
								backgroundColor: segment.color,
								boxShadow: `0 0 20px ${segment.color}`,
								display: "flex",
								alignItems: "center",
								justifyContent: "center",
							}}
						>
							<span className="text-[10px] font-bold text-white">
								{segment.label}
							</span>
						</div>
					))}
				</div>
			</div>
		</Card>
	);
};

// Mini version for smaller displays
export const StrategyDNAMini: React.FC<{
	segments?: number;
	className?: string;
}> = ({ segments = 6, className = "" }) => {
	const colors = ["#3b82f6", "#8b5cf6", "#10b981", "#f59e0b", "#ef4444"];

	return (
		<div className={`flex items-center gap-1 ${className}`}>
			{Array.from({ length: segments }).map((_, i) => (
				<div
					key={i}
					className="w-2 h-2 rounded-full animate-pulse"
					style={{
						backgroundColor: colors[i % colors.length],
						animationDelay: `${i * 0.1}s`,
					}}
				/>
			))}
		</div>
	);
};
