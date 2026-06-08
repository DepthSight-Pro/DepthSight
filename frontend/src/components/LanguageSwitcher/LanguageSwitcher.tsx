// src/components/LanguageSwitcher/LanguageSwitcher.tsx

import { Globe } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";

export function LanguageSwitcher() {
	const { i18n } = useTranslation();

	const changeLanguage = (lng: string) => {
		i18n.changeLanguage(lng);
		localStorage.setItem("i18nextLng", lng);
	};

	return (
		<div className="flex items-center space-x-1 px-2">
			<Button
				variant={i18n.language === "en" ? "secondary" : "ghost"}
				size="sm"
				onClick={() => changeLanguage("en")}
				className="w-full justify-start"
			>
				<Globe className="mr-2 h-4 w-4" />
				EN
			</Button>
			<Button
				variant={i18n.language === "ru" ? "secondary" : "ghost"}
				size="sm"
				onClick={() => changeLanguage("ru")}
				className="w-full justify-start"
			>
				<Globe className="mr-2 h-4 w-4" />
				RU
			</Button>
		</div>
	);
}
