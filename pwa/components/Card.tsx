// pwa/components/Card.tsx

import type React from "react";

interface CardProps {
	children: React.ReactNode;
	className?: string;
}

export const Card: React.FC<CardProps> = ({ children, className }) => (
	<div
		className={`bg-[hsl(var(--card))] p-4 rounded-lg shadow-sm ${className}`}
	>
		{children}
	</div>
);

export const CardHeader: React.FC<CardProps> = ({ children, className }) => (
	<div
		className={`border-b pb-2 mb-2 border-[hsl(var(--border))] ${className}`}
	>
		{children}
	</div>
);

export const CardTitle: React.FC<CardProps> = ({ children, className }) => (
	<h2
		className={`text-lg font-semibold text-[hsl(var(--card-foreground))] ${className}`}
	>
		{children}
	</h2>
);

export const CardDescription: React.FC<CardProps> = ({
	children,
	className,
}) => (
	<p className={`text-sm text-[hsl(var(--muted-foreground))] ${className}`}>
		{children}
	</p>
);

export const CardContent: React.FC<CardProps> = ({ children, className }) => (
	<div className={`mt-4 text-[hsl(var(--card-foreground))] ${className}`}>
		{children}
	</div>
);
