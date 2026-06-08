// src/components/layout/PageLayout.tsx

import type React from "react";
import { useEffect } from "react";
import { useTranslation } from "react-i18next";
import { SidebarTrigger, useSidebar } from "@/components/ui/sidebar";

interface PageLayoutProps {
	title: string;
	description?: React.ReactNode;
	icon?: React.ElementType;
	children: React.ReactNode;
	headerActions?: React.ReactNode;
}

export const PageLayout: React.FC<PageLayoutProps> = ({
	title,
	description,
	icon: Icon,
	children,
	headerActions,
}) => {
	const { t } = useTranslation(["common"]);
	useEffect(() => {
		document.title = `DepthSight - ${title}`;
	}, [title]);

	const { isMobile } = useSidebar();

	return (
		<div className="p-4 sm:p-6 lg:p-8 h-full flex flex-col">
			<header className="mb-6 flex items-start justify-between flex-shrink-0">
				<div className="flex items-center gap-3">
					{isMobile && <SidebarTrigger />}
					{Icon && <Icon className="w-7 h-7 text-primary" />}
					<div>
						<h1 className="text-2xl font-bold tracking-tight">{title}</h1>
						{description && (
							<div className="text-sm text-muted-foreground mt-1">
								{description}
							</div>
						)}
					</div>
				</div>
				<div className="flex items-center space-x-4">{headerActions}</div>
			</header>
			<div className="flex-grow min-h-0">{children}</div>
			<footer className="mt-8 py-4 text-center text-sm text-muted-foreground border-t">
				© 2026 DepthSight |{" "}
				<a
					href={`${import.meta.env.VITE_APP_URL || "https://depthsight.pro"}/privacy-policy`}
					className="hover:underline"
				>
					{t("privacyPolicy")}
				</a>{" "}
				|{" "}
				<a
					href={`${import.meta.env.VITE_APP_URL || "https://depthsight.pro"}/terms-of-service`}
					className="hover:underline"
				>
					{t("termsOfService")}
				</a>{" "}
				| <a href="/?view_mode=mobile">{t("switchToMobile")}</a>
			</footer>
		</div>
	);
};
