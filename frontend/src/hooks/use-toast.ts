"use client";

// Inspired by react-hot-toast library
import * as React from "react";

import type { ToastActionElement, ToastProps } from "@/components/ui/toast";

const TOAST_LIMIT = 3;
const TOAST_REMOVE_DELAY = 1000000;

type ToasterToast = Omit<ToastProps, "title"> & {
	id: string;
	title?: React.ReactNode;
	description?: React.ReactNode;
	action?: ToastActionElement;
};

let count = 0;

function genId() {
	count = (count + 1) % Number.MAX_SAFE_INTEGER;
	return count.toString();
}

type Action =
	| {
			type: "ADD_TOAST";
			toast: ToasterToast;
	  }
	| {
			type: "UPDATE_TOAST";
			toast: Partial<ToasterToast>;
	  }
	| {
			type: "DISMISS_TOAST";
			toastId?: ToasterToast["id"];
	  }
	| {
			type: "REMOVE_TOAST";
			toastId?: ToasterToast["id"];
	  };

interface State {
	toasts: ToasterToast[];
}

const toastTimeouts = new Map<string, ReturnType<typeof setTimeout>>();

const addToRemoveQueue = (toastId: string) => {
	if (toastTimeouts.has(toastId)) {
		return;
	}

	const timeout = setTimeout(() => {
		toastTimeouts.delete(toastId);
		dispatch({
			type: "REMOVE_TOAST",
			toastId: toastId,
		});
	}, TOAST_REMOVE_DELAY);

	toastTimeouts.set(toastId, timeout);
};

export const reducer = (state: State, action: Action): State => {
	switch (action.type) {
		case "ADD_TOAST":
			return {
				...state,
				toasts: [action.toast, ...state.toasts].slice(0, TOAST_LIMIT),
			};

		case "UPDATE_TOAST":
			return {
				...state,
				toasts: state.toasts.map((t) =>
					t.id === action.toast.id ? { ...t, ...action.toast } : t,
				),
			};

		case "DISMISS_TOAST": {
			const { toastId } = action;

			// ! Side effects ! - This could be extracted into a dismissToast() action,
			// but I'll keep it here for simplicity
			if (toastId) {
				addToRemoveQueue(toastId);
			} else {
				state.toasts.forEach((toast) => {
					addToRemoveQueue(toast.id);
				});
			}

			return {
				...state,
				toasts: state.toasts.map((t) =>
					t.id === toastId || toastId === undefined
						? {
								...t,
								open: false,
							}
						: t,
				),
			};
		}
		case "REMOVE_TOAST":
			if (action.toastId === undefined) {
				return {
					...state,
					toasts: [],
				};
			}
			return {
				...state,
				toasts: state.toasts.filter((t) => t.id !== action.toastId),
			};
	}
};

const listeners: Array<(state: State) => void> = [];

let memoryState: State = { toasts: [] };

function dispatch(action: Action) {
	memoryState = reducer(memoryState, action);
	listeners.forEach((listener) => {
		listener(memoryState);
	});
}

type Toast = Omit<ToasterToast, "id">;

function toast(
	propsOrTitle: Toast | React.ReactNode,
	options?: ToastOptions & { variant?: Toast["variant"] },
) {
	let props: Toast;
	if (
		typeof propsOrTitle === "string" ||
		React.isValidElement(propsOrTitle) ||
		(propsOrTitle != null && typeof propsOrTitle !== "object") ||
		(typeof propsOrTitle === "object" &&
			!("title" in (propsOrTitle as object)) &&
			!("description" in (propsOrTitle as object)) &&
			!("variant" in (propsOrTitle as object)))
	) {
		props = {
			title: propsOrTitle as React.ReactNode,
			description: options?.description,
			action: options?.action,
			variant: options?.variant,
			duration: options?.duration,
		};
	} else {
		props = propsOrTitle as Toast;
	}

	const id = genId();

	const update = (props: ToasterToast) =>
		dispatch({
			type: "UPDATE_TOAST",
			toast: { ...props, id },
		});
	const dismiss = () => dispatch({ type: "DISMISS_TOAST", toastId: id });

	dispatch({
		type: "ADD_TOAST",
		toast: {
			...props,
			id,
			open: true,
			onOpenChange: (open) => {
				if (!open) dismiss();
			},
		},
	});

	return {
		id: id,
		dismiss,
		update,
	};
}

export interface ToastOptions {
	description?: React.ReactNode;
	action?: ToastActionElement;
	duration?: number;
}

toast.success = (title: React.ReactNode, options?: ToastOptions) =>
	toast({
		title,
		description: options?.description,
		action: options?.action,
		variant: "success",
		duration: options?.duration ?? 4000,
	});

toast.error = (title: React.ReactNode, options?: ToastOptions) =>
	toast({
		title,
		description: options?.description,
		action: options?.action,
		variant: "destructive",
		duration: options?.duration ?? 6000,
	});

toast.warning = (title: React.ReactNode, options?: ToastOptions) =>
	toast({
		title,
		description: options?.description,
		action: options?.action,
		variant: "warning",
		duration: options?.duration ?? 5000,
	});

toast.info = (title: React.ReactNode, options?: ToastOptions) =>
	toast({
		title,
		description: options?.description,
		action: options?.action,
		variant: "info",
		duration: options?.duration ?? 4000,
	});

toast.message = (title: React.ReactNode, options?: ToastOptions) =>
	toast(title, options);

toast.custom = (jsx: React.ReactNode, options?: ToastOptions) =>
	toast(jsx, options);

toast.dismiss = (toastId?: string) => dispatch({ type: "DISMISS_TOAST", toastId });

toast.promise = async <T>(
	promise: Promise<T>,
	messages: {
		loading: React.ReactNode;
		success: React.ReactNode | ((data: T) => React.ReactNode);
		error: React.ReactNode | ((err: unknown) => React.ReactNode);
	},
) => {
	const id = toast({
		title: messages.loading,
		variant: "info",
	}).id;

	try {
		const result = await promise;
		const successMsg =
			typeof messages.success === "function"
				? messages.success(result)
				: messages.success;
		dispatch({
			type: "UPDATE_TOAST",
			toast: {
				id,
				title: successMsg,
				variant: "success",
				open: true,
			},
		});
		return result;
	} catch (err) {
		const errorMsg =
			typeof messages.error === "function"
				? messages.error(err)
				: messages.error;
		dispatch({
			type: "UPDATE_TOAST",
			toast: {
				id,
				title: errorMsg,
				variant: "destructive",
				open: true,
			},
		});
		throw err;
	}
};

function useToast() {
	const [state, setState] = React.useState<State>(memoryState);

	React.useEffect(() => {
		listeners.push(setState);
		return () => {
			const index = listeners.indexOf(setState);
			if (index > -1) {
				listeners.splice(index, 1);
			}
		};
	}, []);

	return {
		...state,
		toast,
		dismiss: (toastId?: string) => dispatch({ type: "DISMISS_TOAST", toastId }),
	};
}

export { toast, useToast };
