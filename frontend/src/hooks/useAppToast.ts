// src/hooks/useAppToast.ts

import { toast } from "@/hooks/use-toast";

const TOAST_DURATION = {
	SUCCESS: 3500,
	ERROR: 5500,
	INFO: 4000,
};

/**
 * Custom hook for standardized display of notifications in the application.
 * Uses the unified DepthSight glassmorphic toast system.
 */
export const useAppToast = () => {
	const success = (title: string, description?: string) => {
		toast.success(title, {
			description,
			duration: TOAST_DURATION.SUCCESS,
		});
	};

	const error = (title: string, description?: string) => {
		toast.error(title, {
			description,
			duration: TOAST_DURATION.ERROR,
		});
	};

	const info = (title: string, description?: string) => {
		toast.info(title, {
			description,
			duration: TOAST_DURATION.INFO,
		});
	};

	const promise = <T>(
		prom: Promise<T>,
		messages: { loading: string; success: string; error: string },
	) => {
		return toast.promise(prom, {
			loading: messages.loading,
			success: messages.success,
			error: (err) =>
				`${messages.error}: ${err instanceof Error ? err.message : "Unknown error"}`,
		});
	};

	return {
		success,
		error,
		info,
		promise,
	};
};
