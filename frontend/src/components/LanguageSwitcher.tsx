// src/components/LanguageSwitcher.tsx

import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import {
	Tooltip,
	TooltipContent,
	TooltipTrigger,
} from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";

export function LanguageSwitcher() {
	const { i18n } = useTranslation();

	const handleToggle = () => {
		const currentLang = i18n.language.split("-")[0];
		const nextLang = currentLang === "en" ? "ru" : "en";
		i18n.changeLanguage(nextLang);
		localStorage.setItem("i18nextLng", nextLang);
	};

	const currentLang = i18n.language.split("-")[0];
	const tooltipText = `Switch to ${currentLang === "en" ? "Russian" : "English"}`;

	return (
		<Tooltip>
			<TooltipTrigger asChild>
				<Button
					variant="ghost"
					size="icon"
					className={cn("rounded-lg")} // Match NavItem style
					onClick={handleToggle}
				>
					{/* Display current language abbreviation */}
					<span className="text-sm font-semibold">
						{currentLang.toUpperCase()}
					</span>
				</Button>
			</TooltipTrigger>
			<TooltipContent side="right">{tooltipText}</TooltipContent>
		</Tooltip>
	);
}
