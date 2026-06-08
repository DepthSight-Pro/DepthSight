// frontend/src/context/SymbolSelectionSettingsContext.tsx

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type React from "react";
import { createContext, type ReactNode, useContext } from "react";
import { useTranslation } from "react-i18next";
import { useToast } from "@/components/ui/use-toast";
import {
	fetchSymbolSelectionSettings,
	updateSymbolSelectionSettings,
} from "@/lib/api";
import type { SymbolSelectionConfig } from "@/types/api";

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
	const { toast } = useToast();
	const { t } = useTranslation(["common"]);
	const queryClient = useQueryClient();

	const {
		data: settings,
		isLoading,
		isError,
	} = useQuery<SymbolSelectionConfig>({
		queryKey: ["symbolSelectionSettings"],
		queryFn: fetchSymbolSelectionSettings,
		staleTime: 1000 * 60 * 5, // 5 minutes
		gcTime: 1000 * 60 * 10, // 10 minutes (formerly cacheTime)
	});

	const { mutate: mutateSettings, isPending: isUpdating } = useMutation({
		mutationFn: updateSymbolSelectionSettings,
		onSuccess: () => {
			queryClient.invalidateQueries({ queryKey: ["symbolSelectionSettings"] });
			toast({
				title: t("common:successTitle"),
				description: t("common:settingsSavedSuccessfully"),
			});
		},
		onError: (error) => {
			toast({
				title: t("common:errorTitle"),
				description: error.message || t("common:failedToSaveSettings"),
				variant: "destructive",
			});
		},
	});

	const updateSettings = (newSettings: Partial<SymbolSelectionConfig>) => {
		if (!settings) {
			console.error(
				"Attempted to update settings when settings object is undefined.",
			);
			toast({
				title: t("common:errorTitle"),
				description: t("common:failedToUpdateSettingsNoData"),
				variant: "destructive",
			});
			return;
		}
		const mergedSettings: SymbolSelectionConfig = {
			...settings,
			...newSettings,
		};
		mutateSettings(mergedSettings);
	};

	return (
		<SymbolSelectionSettingsContext.Provider
			value={{ settings, isLoading, isError, updateSettings, isUpdating }}
		>
			{children}
		</SymbolSelectionSettingsContext.Provider>
	);
};

// eslint-disable-next-line react-refresh/only-export-components
export const useSymbolSelectionSettings = () => {
	const context = useContext(SymbolSelectionSettingsContext);
	if (context === undefined) {
		throw new Error(
			"useSymbolSelectionSettings must be used within a SymbolSelectionSettingsProvider",
		);
	}
	return context;
};
