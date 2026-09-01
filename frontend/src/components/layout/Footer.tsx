// src/components/layout/Footer.tsx

import type React from "react";
import { useTranslation } from "react-i18next";

interface FooterProps {
	className?: string;
}

export const Footer: React.FC<FooterProps> = ({ className = "" }) => {
	const { t } = useTranslation(["common"]);

	return (
		<footer
			className={`py-4 text-center text-sm text-muted-foreground border-t ${className}`}
		>
			<div className="container mx-auto flex flex-wrap items-center justify-center gap-x-2 gap-y-1">
				<span>© 2026 DepthSight</span>
				<span>|</span>
				<a
					href={`${import.meta.env.VITE_APP_URL || "https://depthsight.pro"}/privacy-policy`}
					target="_blank"
					rel="noopener noreferrer"
					className="hover:underline hover:text-foreground transition-colors"
				>
					{t("privacyPolicy")}
				</a>
				<span>|</span>
				<a
					href={`${import.meta.env.VITE_APP_URL || "https://depthsight.pro"}/terms-of-service`}
					target="_blank"
					rel="noopener noreferrer"
					className="hover:underline hover:text-foreground transition-colors"
				>
					{t("termsOfService")}
				</a>
				<span>|</span>
				<a
					href="https://app.depthsight.pro/pwa/"
					target="_blank"
					rel="noopener noreferrer"
					className="hover:underline hover:text-foreground transition-colors"
				>
					{t("switchToMobile")}
				</a>
			</div>
		</footer>
	);
};
