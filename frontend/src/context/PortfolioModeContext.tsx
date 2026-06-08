// src/context/PortfolioModeContext.tsx

/* eslint-disable react-refresh/only-export-components */
import type React from "react";
import {
	createContext,
	useCallback,
	useContext,
	useEffect,
	useMemo,
	useState,
} from "react";

type PortfolioMode = "live" | "paper";

interface PortfolioModeContextType {
	mode: PortfolioMode;
	setMode: (mode: PortfolioMode) => void;
}

const PortfolioModeContext = createContext<
	PortfolioModeContextType | undefined
>(undefined);
const PORTFOLIO_MODE_STORAGE_KEY = "portfolioMode";

export const PortfolioModeProvider: React.FC<{ children: React.ReactNode }> = ({
	children,
}) => {
	const [mode, setModeState] = useState<PortfolioMode>(() => {
		try {
			const storedMode = localStorage.getItem(PORTFOLIO_MODE_STORAGE_KEY);
			return storedMode === "live" || storedMode === "paper"
				? storedMode
				: "paper";
		} catch (error) {
			console.error("Failed to read from localStorage", error);
			return "paper";
		}
	});

	useEffect(() => {
		try {
			localStorage.setItem(PORTFOLIO_MODE_STORAGE_KEY, mode);
		} catch (error) {
			console.error("Failed to write to localStorage", error);
		}
	}, [mode]);

	const setMode = useCallback((newMode: PortfolioMode) => {
		try {
			localStorage.setItem(PORTFOLIO_MODE_STORAGE_KEY, newMode);
		} catch (error) {
			console.error("Failed to write to localStorage", error);
		}
		setModeState(newMode);
	}, []);

	const contextValue = useMemo(
		() => ({
			mode,
			setMode,
		}),
		[mode, setMode],
	);

	return (
		<PortfolioModeContext.Provider value={contextValue}>
			{children}
		</PortfolioModeContext.Provider>
	);
};

export const usePortfolioMode = (): PortfolioModeContextType => {
	const context = useContext(PortfolioModeContext);
	if (context === undefined) {
		throw new Error(
			"usePortfolioMode must be used within a PortfolioModeProvider",
		);
	}
	return context;
};
