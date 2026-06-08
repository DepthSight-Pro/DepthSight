// pwa/components/SettingsSection.tsx

import type React from "react";

interface SettingsSectionProps {
	title: string;
	description: string;
	children: React.ReactNode;
	footerActions?: React.ReactNode;
}

const SettingsSection: React.FC<SettingsSectionProps> = ({
	title,
	description,
	children,
	footerActions,
}) => (
	<div className="bg-[hsl(var(--card))] p-4 rounded-lg shadow-sm">
		<h2 className="text-lg font-semibold text-[hsl(var(--card-foreground))]">
			{title}
		</h2>
		<p className="text-sm text-[hsl(var(--muted-foreground))]">{description}</p>
		<div className="mt-4">{children}</div>
		{footerActions && (
			<div className="mt-4 flex justify-end">{footerActions}</div>
		)}
	</div>
);

export default SettingsSection;
