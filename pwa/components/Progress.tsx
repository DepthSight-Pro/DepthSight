// pwa/components/Progress.tsx

import type React from "react";

interface ProgressProps {
	value: number;
}

const Progress: React.FC<ProgressProps> = ({ value }) => (
	<div className="h-2.5 w-full rounded-full bg-[hsl(var(--muted))]">
		<div
			className="h-full rounded-full bg-[hsl(var(--primary))] transition-all"
			style={{ width: `${Math.max(0, Math.min(100, value))}%` }}
		/>
	</div>
);

export default Progress;
