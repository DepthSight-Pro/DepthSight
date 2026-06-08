// src/components/ui/Spinner.tsx

import { Loader } from "lucide-react";
import type React from "react";
import { cn } from "@/lib/utils";

interface SpinnerProps {
	size?: "sm" | "md" | "lg";
	className?: string;
}

export const Spinner: React.FC<SpinnerProps> = ({ size = "md", className }) => {
	const sizeClasses = {
		sm: "h-4 w-4",
		md: "h-8 w-8",
		lg: "h-12 w-12",
	};

	return (
		<Loader
			className={cn("animate-spin text-primary", sizeClasses[size], className)}
		/>
	);
};
