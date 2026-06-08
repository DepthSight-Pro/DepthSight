// frontend/src/components/analytics/AdvancedStatCard.tsx

import * as LucideIcons from "lucide-react";
import type React from "react";

interface AdvancedStatCardProps {
	label: string;
	value: string | number;
	icon: keyof typeof LucideIcons;
	colorClass: string; // e.g. 'bg-emerald-500', 'bg-rose-500', 'bg-amber-500'
	subValue?: string;
	isLoading?: boolean;
}

// Map bg-color classes to actual colors
const colorMap: Record<string, { bg: string; text: string }> = {
	"bg-emerald-500": { bg: "rgba(16, 185, 129, 0.1)", text: "#10b981" },
	"bg-rose-500": { bg: "rgba(244, 63, 94, 0.1)", text: "#f43f5e" },
	"bg-amber-500": { bg: "rgba(245, 158, 11, 0.1)", text: "#f59e0b" },
	"bg-indigo-500": { bg: "rgba(99, 102, 241, 0.1)", text: "#6366f1" },
	"bg-purple-500": { bg: "rgba(168, 85, 247, 0.1)", text: "#a855f7" },
	"bg-sky-500": { bg: "rgba(14, 165, 233, 0.1)", text: "#0ea5e9" },
	"bg-violet-500": { bg: "rgba(139, 92, 246, 0.1)", text: "#8b5cf6" },
};

export const AdvancedStatCard: React.FC<AdvancedStatCardProps> = ({
	label,
	value,
	icon,
	colorClass,
	subValue,
	isLoading = false,
}) => {
	const Icon = LucideIcons[icon] as LucideIcons.LucideIcon;
	const colors = colorMap[colorClass] || {
		bg: "rgba(156, 163, 175, 0.1)",
		text: "#9ca3af",
	};

	if (isLoading) {
		return (
			<div className="bg-card border border-border p-5 rounded-2xl animate-pulse">
				<div className="flex items-center justify-between mb-3">
					<div className="h-4 w-20 bg-muted rounded" />
					<div className="h-9 w-9 bg-muted rounded-lg" />
				</div>
				<div className="h-7 w-24 bg-muted rounded" />
			</div>
		);
	}

	return (
		<div className="bg-card border border-border p-5 rounded-2xl transition-all duration-200 hover:shadow-md">
			<div className="flex items-center justify-between mb-3">
				<span className="text-muted-foreground text-sm font-medium">
					{label}
				</span>
				<div className="p-2 rounded-lg" style={{ backgroundColor: colors.bg }}>
					<Icon className="w-5 h-5" style={{ color: colors.text }} />
				</div>
			</div>
			<div className="flex flex-col">
				<span className="text-2xl font-bold" style={{ color: colors.text }}>
					{value}
				</span>
				{subValue && (
					<span className="text-muted-foreground text-xs mt-1">{subValue}</span>
				)}
			</div>
		</div>
	);
};
