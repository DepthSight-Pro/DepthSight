// src/pages/NotFound.tsx

import { useEffect } from "react";
import { useTranslation } from "react-i18next";
import { useLocation } from "react-router-dom";

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
		<div className="min-h-screen flex items-center justify-center bg-gray-100">
			<div className="text-center">
				<h1 className="text-4xl font-bold mb-4">{t("notFound.title")}</h1>
				<p className="text-xl text-gray-600 mb-4">
					{t("notFound.description")}
				</p>
				{/* Changed 'message' to 'description' to match keys from research.json */}
				<a href="/" className="text-blue-500 hover:text-blue-700 underline">
					{t("notFound.goHomeButton")}
				</a>
			</div>
		</div>
	);
};

export default NotFound;
