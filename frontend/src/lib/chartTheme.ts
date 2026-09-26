// src/lib/chartTheme.ts

import { ColorType } from "lightweight-charts";
import { useTheme } from "@/context/ThemeProvider";

export interface ChartThemeColors {
	background: string;
	textColor: string;
	gridColor: string;
	borderColor: string;
	upColor: string;
	downColor: string;
}

export function getChartThemeColors(isLight: boolean): ChartThemeColors {
	return {
		background: isLight ? "#ffffff" : "#07080b",
		textColor: isLight ? "rgba(15, 23, 42, 0.65)" : "rgba(255, 255, 255, 0.45)",
		gridColor: isLight ? "rgba(15, 23, 42, 0.05)" : "rgba(255, 255, 255, 0.03)",
		borderColor: isLight ? "rgba(15, 23, 42, 0.1)" : "rgba(255, 255, 255, 0.08)",
		upColor: isLight ? "#059669" : "#10b981",
		downColor: isLight ? "#e11d48" : "#f43f5e",
	};
}

export function useChartTheme() {
	const { theme } = useTheme();
	const isLight = theme === "light";
	return {
		theme,
		isLight,
		colors: getChartThemeColors(isLight),
	};
}
