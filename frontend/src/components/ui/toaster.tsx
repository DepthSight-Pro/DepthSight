import {
	AlertCircle,
	AlertTriangle,
	CheckCircle2,
	Info,
} from "lucide-react";
import {
	Toast,
	ToastClose,
	ToastDescription,
	ToastProvider,
	ToastTitle,
	ToastViewport,
} from "@/components/ui/toast";
import { useToast } from "@/hooks/use-toast";

export function Toaster() {
	const { toasts } = useToast();

	return (
		<ToastProvider>
			{toasts.map(({ id, title, description, action, variant, ...props }) => (
				<Toast key={id} variant={variant} {...props}>
					<div className="flex items-start gap-3 w-full">
						{variant === "success" && (
							<CheckCircle2 className="h-5 w-5 text-emerald-400 shrink-0 mt-0.5" />
						)}
						{variant === "destructive" && (
							<AlertCircle className="h-5 w-5 text-red-400 shrink-0 mt-0.5" />
						)}
						{variant === "warning" && (
							<AlertTriangle className="h-5 w-5 text-amber-400 shrink-0 mt-0.5" />
						)}
						{variant === "info" && (
							<Info className="h-5 w-5 text-cyan-400 shrink-0 mt-0.5" />
						)}
						<div className="grid gap-1 flex-1 min-w-0">
							{title && <ToastTitle>{title}</ToastTitle>}
							{description && <ToastDescription>{description}</ToastDescription>}
						</div>
					</div>
					{action}
					<ToastClose />
				</Toast>
			))}
			<ToastViewport />
		</ToastProvider>
	);
}
