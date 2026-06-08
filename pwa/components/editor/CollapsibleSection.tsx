// pwa/components/editor/CollapsibleSection.tsx

import type React from "react";
import { useState } from "react";
import { ICONS } from "../../constants";

interface CollapsibleSectionProps {
	title: string;
	icon?: React.ElementType;
	children: React.ReactNode;
	defaultCollapsed?: boolean;
	className?: string;
}

const CollapsibleSection: React.FC<CollapsibleSectionProps> = ({
	title,
	icon: Icon,
	children,
	defaultCollapsed = false,
	className = "",
}) => {
	const [isCollapsed, setIsCollapsed] = useState(defaultCollapsed);
	const ChevronIcon = isCollapsed ? ICONS.ChevronDown : ICONS.ChevronUp;

	return (
		<div className={`strategy-section ${className}`}>
			<div
				className="section-header cursor-pointer flex items-center justify-between"
				onClick={() => setIsCollapsed(!isCollapsed)}
			>
				<div className="section-title flex items-center">
					{Icon && (
						<div className="section-icon bg-opacity-10 text-opacity-100">
							<Icon className="w-5 h-5" />
						</div>
					)}
					<span>{title}</span>
				</div>
				<ChevronIcon className="w-5 h-5 text-[hsl(var(--muted-foreground))]" />
			</div>
			{!isCollapsed && <div className="section-content">{children}</div>}
		</div>
	);
};

export default CollapsibleSection;
