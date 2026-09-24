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
	"bg-emerald-500": { bg: "rgba(16, 224, 160, 0.12)", text: "#10e0a0" },
	"bg-rose-500": { bg: "rgba(255, 59, 92, 0.12)", text: "#ff3b5c" },
	"bg-amber-500": { bg: "rgba(245, 158, 11, 0.12)", text: "#f59e0b" },
	"bg-indigo-500": { bg: "rgba(99, 102, 241, 0.12)", text: "#6366f1" },
	"bg-purple-500": { bg: "rgba(168, 85, 247, 0.12)", text: "#a855f7" },
	"bg-sky-500": { bg: "rgba(14, 165, 233, 0.12)", text: "#0ea5e9" },
	"bg-violet-500": { bg: "rgba(139, 92, 246, 0.12)", text: "#8b5cf6" },
	"bg-blue-500": { bg: "rgba(0, 212, 255, 0.12)", text: "#00d4ff" },
	"bg-zinc-500": { bg: "rgba(156, 163, 175, 0.1)", text: "#9ca3af" },
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
			<div className="glass relative rounded-2xl p-4 overflow-hidden border border-white/5 animate-pulse">
				<div className="flex items-center justify-between mb-3">
					<div className="h-3.5 w-16 bg-white/10 rounded" />
					<div className="h-8 w-8 bg-white/10 rounded-xl" />
				</div>
				<div className="h-6 w-20 bg-white/10 rounded mt-2" />
			</div>
		);
	}

	return (
		<div className="glass relative rounded-2xl p-4 overflow-hidden border border-white/10 hover:border-white/20 transition-all group animate-fade-up">
			{/* Ambient background glow */}
			<div
				className="pointer-events-none absolute -right-6 -top-6 h-24 w-24 rounded-full blur-2xl opacity-15 group-hover:opacity-30 transition-opacity"
				style={{ background: colors.text }}
			/>

			<div className="flex items-center justify-between mb-2">
				<span className="text-[11px] font-semibold uppercase tracking-wider text-white/40 font-mono truncate mr-2">
					{label}
				</span>
				<div
					className="flex h-8 w-8 shrink-0 items-center justify-center rounded-xl border transition-all"
					style={{
						borderColor: `${colors.text}33`,
						backgroundColor: colors.bg,
					}}
				>
					{Icon && <Icon className="w-4 h-4" style={{ color: colors.text }} />}
				</div>
			</div>

			<div className="flex flex-col">
				<span
					className="text-xl font-bold font-mono tracking-tight tabular-nums truncate"
					style={{ color: colors.text }}
				>
					{value}
				</span>
				{subValue && (
					<span className="text-[11px] font-mono text-white/40 mt-1 truncate">
						{subValue}
					</span>
				)}
			</div>
		</div>
	);
};
