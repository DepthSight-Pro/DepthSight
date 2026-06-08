// src/components/layout/PublicLayout.tsx

import type React from "react";
import { useTranslation } from "react-i18next";
import { Outlet } from "react-router-dom";

export const PublicLayout: React.FC = () => {
	const { t } = useTranslation("common");

	return (
		<div className="flex min-h-screen w-full flex-col bg-background">
			<main className="flex-grow">
				<Outlet />
			</main>
			<footer className="py-6 px-4 text-center text-sm text-muted-foreground border-t">
				<div className="container mx-auto">
					© {new Date().getFullYear()} DepthSight |{" "}
					<a
						href={`${import.meta.env.VITE_APP_URL || "https://depthsight.pro"}/privacy-policy`}
						target="_blank"
						rel="noopener noreferrer"
						className="underline hover:text-primary"
					>
						{t("privacyPolicy")}
					</a>{" "}
					|{" "}
					<a
						href={`${import.meta.env.VITE_APP_URL || "https://depthsight.pro"}/terms-of-service`}
						target="_blank"
						rel="noopener noreferrer"
						className="underline hover:text-primary"
					>
						{t("termsOfService")}
					</a>
				</div>
			</footer>
		</div>
	);
};
