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
					className={cn("h-8 w-8 rounded-lg text-white/50 hover:text-white hover:bg-white/5 transition-colors")}
					onClick={handleToggle}
				>
					{/* Display current language abbreviation */}
					<span className="text-[11px] font-bold font-mono">
						{currentLang.toUpperCase()}
					</span>
				</Button>
			</TooltipTrigger>
			<TooltipContent side="right">{tooltipText}</TooltipContent>
		</Tooltip>
	);
}
