// src/components/ui/badge.tsx

import type { VariantProps } from "class-variance-authority";
import * as React from "react";

import { cn } from "@/lib/utils";
import { badgeVariants } from "./badge-variants";

export interface BadgeProps
	extends React.HTMLAttributes<HTMLDivElement>,
		VariantProps<typeof badgeVariants> {}

const Badge = React.forwardRef<HTMLDivElement, BadgeProps>(
	({ className, variant, ...props }, ref) => {
		return (
			<div
				className={cn(badgeVariants({ variant }), className)}
				ref={ref}
				{...props}
			/>
		);
	},
);
Badge.displayName = "Badge"; // Adding displayName for debugging

export { Badge };
