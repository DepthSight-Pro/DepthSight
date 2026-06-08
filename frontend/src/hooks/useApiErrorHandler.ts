// src/hooks/useApiErrorHandler.ts

import { useEffect } from "react";
import { useToast } from "@/components/ui/use-toast";
import { useAuth } from "@/context/AuthContext";

// Assuming your API hooks throw an error with a `response` field
interface ApiError extends Error {
	response?: {
		status: number;
		data: {
			detail?: string;
		};
	};
}

export const useApiErrorHandler = (error: unknown, context?: string) => {
	const { toast } = useToast();
	const { logout } = useAuth();

	useEffect(() => {
		if (!error) return;

		const apiError = error as ApiError;
		const status = apiError.response?.status;
		const detail =
			apiError.response?.data?.detail || "An unknown error occurred.";
		const title = `API Error${context ? `: ${context}` : ""}`;

		console.error(title, error);

		if (status === 401) {
			// If the token is invalid, log out of the system
			toast({
				variant: "destructive",
				title: "Authentication Error",
				description: "Your session has expired. Please log in again.",
			});
			logout();
			return;
		}

		if (status === 403) {
			toast({
				variant: "destructive",
				title: "Access Denied",
				description:
					detail ||
					"This feature requires a higher plan. Please upgrade your account.",
			});
			return;
		}

		if (status === 429) {
			toast({
				variant: "destructive",
				title: "Usage Limit Reached",
				description:
					detail ||
					"You have exceeded the usage limit for this feature on your current plan.",
			});
			return;
		}

		toast({
			variant: "destructive",
			title: title,
			description: apiError.message || detail,
		});
	}, [error, context, toast, logout]);
};
