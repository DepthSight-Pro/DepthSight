// src/hooks/useAppToast.ts

import { toast as sonnerToast } from "sonner";

// Define standard duration for different types of notifications
const TOAST_DURATION = {
	SUCCESS: 3000, // 3 seconds
	ERROR: 5000, // 5 seconds
	INFO: 4000, // 4 seconds
};

/**
 * Custom hook for standardized display of notifications in the application.
 * Uses 'sonner' under the hood.
 */
export const useAppToast = () => {
	const success = (title: string, description?: string) => {
		sonnerToast.success(title, {
			description,
			duration: TOAST_DURATION.SUCCESS,
		});
	};

	const error = (title: string, description?: string) => {
		sonnerToast.error(title, {
			description,
			duration: TOAST_DURATION.ERROR,
			// You can add a "Dismiss" button for important errors if needed
		});
	};

	const info = (title: string, description?: string) => {
		sonnerToast.info(title, {
			description,
			duration: TOAST_DURATION.INFO,
		});
	};

	const promise = <T>(
		promise: Promise<T>,
		messages: { loading: string; success: string; error: string },
	) => {
		sonnerToast.promise(promise, {
			loading: messages.loading,
			success: () => messages.success,
			error: (err) =>
				`${messages.error}: ${err instanceof Error ? err.message : "Unknown error"}`,
		});
	};

	// Return an object with our methods
	return {
		success,
		error,
		info,
		promise,
	};
};
