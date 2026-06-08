// pwa/contexts/SymbolSelectionSettingsContext.tsx

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type React from "react";
import { createContext, type ReactNode, useContext } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { api } from "../services/api";
import type { SymbolSelectionConfig } from "../types";

interface SymbolSelectionSettingsContextType {
	settings: SymbolSelectionConfig | undefined;
	isLoading: boolean;
	isError: boolean;
	updateSettings: (newSettings: Partial<SymbolSelectionConfig>) => void;
	isUpdating: boolean;
}

const SymbolSelectionSettingsContext = createContext<
	SymbolSelectionSettingsContextType | undefined
>(undefined);

export const SymbolSelectionSettingsProvider: React.FC<{
	children: ReactNode;
}> = ({ children }) => {
	const { t } = useTranslation("pwa-common");
	const queryClient = useQueryClient();

	const {
		data: settings,
		isLoading,
		isError,
	} = useQuery<SymbolSelectionConfig>({
		queryKey: ["symbolSelectionSettings"],
		queryFn: () => api.fetchSymbolSelectionSettings(),
		staleTime: 1000 * 60 * 5, // 5 minutes
	});

	const { mutate: mutateSettings, isPending: isUpdating } = useMutation({
		mutationFn: (newSettings: SymbolSelectionConfig) =>
			api.updateSymbolSelectionSettings(newSettings),
		onSuccess: (data) => {
			queryClient.setQueryData(["symbolSelectionSettings"], data);
			toast.success(t("settings.saveSuccess"));
		},
		onError: (error) => {
			toast.error(error.message || t("settings.saveError"));
		},
	});

	const updateSettings = (newSettings: Partial<SymbolSelectionConfig>) => {
		if (settings) {
			mutateSettings({ ...settings, ...newSettings });
		}
	};

	return (
		<SymbolSelectionSettingsContext.Provider
			value={{ settings, isLoading, isError, updateSettings, isUpdating }}
		>
			{children}
		</SymbolSelectionSettingsContext.Provider>
	);
};

export const useSymbolSelectionSettings = () => {
	const context = useContext(SymbolSelectionSettingsContext);
	if (context === undefined) {
		throw new Error(
			"useSymbolSelectionSettings must be used within a SymbolSelectionSettingsProvider",
		);
	}
	return context;
};
