import type React from "react";
import { useTranslation } from "react-i18next";
import { ConnectionStatusIndicator } from "@/components/shared/ConnectionStatusIndicator";
import { cn } from "@/lib/utils";

interface FooterProps {
	className?: string;
}

export const Footer: React.FC<FooterProps> = ({ className = "" }) => {
	const { t } = useTranslation(["common"]);

	return (
		<footer
			className={cn(
				"relative w-full shrink-0 py-3 text-center text-[11.5px] font-mono text-muted-foreground border-t border-border/50 bg-obsidian/40 backdrop-blur-md",
				className,
			)}
		>
			<div className="container mx-auto flex flex-wrap items-center justify-center gap-x-3 gap-y-1">
				<span className="text-foreground/80">© 2026 DepthSight</span>
				<span className="text-muted-foreground/30">|</span>
				<a
					href={`${import.meta.env.VITE_APP_URL || "https://depthsight.pro"}/privacy-policy`}
					target="_blank"
					rel="noopener noreferrer"
					className="hover:text-cyan hover:underline transition-colors"
				>
					{t("privacyPolicy")}
				</a>
				<span className="text-muted-foreground/30">|</span>
				<a
					href={`${import.meta.env.VITE_APP_URL || "https://depthsight.pro"}/terms-of-service`}
					target="_blank"
					rel="noopener noreferrer"
					className="hover:text-cyan hover:underline transition-colors"
				>
					{t("termsOfService")}
				</a>
				<span className="text-muted-foreground/30">|</span>
				<a
					href="https://app.depthsight.pro/pwa/"
					target="_blank"
					rel="noopener noreferrer"
					className="hover:text-cyan hover:underline transition-colors text-muted-foreground hover:text-foreground"
				>
					{t("switchToMobile")}
				</a>
			</div>
			<div className="absolute right-3 top-1/2 -translate-y-1/2">
				<ConnectionStatusIndicator iconOnly />
			</div>
		</footer>
	);
};
