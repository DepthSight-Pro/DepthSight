// src/pages/NotFound.tsx

import { useEffect } from "react";
import { useTranslation } from "react-i18next";
import { useLocation } from "react-router-dom";
import { Footer } from "@/components/layout/Footer";

const NotFound = () => {
	const { t } = useTranslation("common");
	const location = useLocation();

	useEffect(() => {
		console.error(
			"404 Error: User attempted to access non-existent route:",
			location.pathname,
		);
	}, [location.pathname]);

	return (
		<div className="min-h-screen flex flex-col bg-background text-foreground">
			<div className="flex-1 flex items-center justify-center">
				<div className="text-center p-4">
					<h1 className="text-4xl font-bold mb-4">{t("notFound.title")}</h1>
					<p className="text-xl text-muted-foreground mb-4">
						{t("notFound.description")}
					</p>
					<a href="/" className="text-primary hover:underline font-medium">
						{t("notFound.goHomeButton")}
					</a>
				</div>
			</div>
			<Footer className="mt-auto" />
		</div>
	);
};

export default NotFound;

