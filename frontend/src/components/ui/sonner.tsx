"use client";

import { useTheme } from "next-themes";
import { Toaster as Sonner } from "sonner";

type ToasterProps = React.ComponentProps<typeof Sonner>;

const Toaster = ({ ...props }: ToasterProps) => {
	const { theme = "system" } = useTheme();

	return (
		<Sonner
			theme={theme as ToasterProps["theme"]}
			className="toaster group"
			position="bottom-right"
			/* Same width / offset in narrow and wide windows */
			toastOptions={{
				classNames: {
					toast:
						"group toast group-[.toaster]:rounded-xl group-[.toaster]:border group-[.toaster]:border-white/10 group-[.toaster]:bg-background/80 group-[.toaster]:text-foreground group-[.toaster]:shadow-2xl group-[.toaster]:backdrop-blur-xl group-[.toaster]:bg-gradient-to-b group-[.toaster]:from-white/[0.05] group-[.toaster]:to-white/[0.015] group-[.toaster]:overflow-hidden",
					title: "group-[.toast]:text-foreground group-[.toast]:font-semibold",
					description: "group-[.toast]:text-muted-foreground group-[.toast]:text-sm",
					actionButton:
						"group-[.toast]:bg-primary group-[.toast]:text-primary-foreground group-[.toast]:rounded-lg",
					cancelButton:
						"group-[.toast]:bg-muted/60 group-[.toast]:text-muted-foreground group-[.toast]:rounded-lg",
					/* Success / error / warning / info accents */
					success:
						"group-[.toaster]:border-emerald-500/30 [&_[data-icon]]:text-emerald-400",
					error:
						"group-[.toaster]:border-red-500/30 [&_[data-icon]]:text-red-400",
					warning:
						"group-[.toaster]:border-amber-500/30 [&_[data-icon]]:text-amber-400",
					info: "group-[.toaster]:border-primary/30 [&_[data-icon]]:text-primary",
				},
			}}
			{...props}
		/>
	);
};

export { Toaster };
