// src/components/shared/AppLoader.tsx

import type React from "react";
import { Logo } from "@/components/ui/logo";
import { cn } from "@/lib/utils";

interface AppLoaderProps {
	size?: "sm" | "md" | "lg" | "xl";
	text?: string;
	className?: string;
	fullLogo?: boolean;
}

export const AppLoader: React.FC<AppLoaderProps> = ({
	size = "md",
	text,
	className,
	fullLogo = false,
}) => {
	const sizeClasses = {
		sm: "h-6",
		md: "h-10",
		lg: "h-16",
		xl: "h-24",
	};

	return (
		<div
			className={cn(
				"flex flex-col items-center justify-center gap-4",
				className,
			)}
		>
			{fullLogo ? (
				<Logo className={cn("animate-pulse-slow", sizeClasses[size])} />
			) : (
				<Logo iconOnly className={cn("animate-spin w-10", sizeClasses[size])} />
			)}
			{text && <span className="text-muted-foreground">{text}</span>}
		</div>
	);
};
