// src/components/ThemeSwitcher.tsx

import { Moon, Sun } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import {
	Tooltip,
	TooltipContent,
	TooltipTrigger,
} from "@/components/ui/tooltip";
import { useTheme } from "@/context/ThemeProvider";

export function ThemeSwitcher() {
	const { t } = useTranslation(["common"]);
	const { theme, setTheme } = useTheme();

	const toggleTheme = () => {
		// If system or dark, toggle to light; otherwise dark
		if (theme === "dark") {
			setTheme("light");
		} else if (theme === "light") {
			setTheme("dark");
		} else {
			const prefersDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
			setTheme(prefersDark ? "light" : "dark");
		}
	};

	const isDark =
		theme === "dark" ||
		(theme === "system" &&
			typeof window !== "undefined" &&
			window.matchMedia("(prefers-color-scheme: dark)").matches);

	return (
		<Tooltip>
			<TooltipTrigger asChild>
				<Button
					variant="ghost"
					size="icon"
					className="relative h-8 w-8 rounded-lg text-muted-foreground hover:text-foreground hover:bg-black/5 dark:hover:bg-white/5 transition-colors"
					onClick={toggleTheme}
					aria-label={isDark ? t("common:theme.switchToLight", "Switch to Light Mode") : t("common:theme.switchToDark", "Switch to Dark Mode")}
				>
					<Sun className="h-4 w-4 rotate-0 scale-100 transition-all text-amber-500 dark:-rotate-90 dark:scale-0" />
					<Moon className="absolute h-4 w-4 rotate-90 scale-0 transition-all text-cyan dark:rotate-0 dark:scale-100" />
					<span className="sr-only">Toggle theme</span>
				</Button>
			</TooltipTrigger>
			<TooltipContent side="right">
				{isDark ? t("common:theme.switchToLight", "Switch to Light Mode") : t("common:theme.switchToDark", "Switch to Dark Mode")}
			</TooltipContent>
		</Tooltip>
	);
}
