// src/pages/onboardingStore.ts

import { create } from "zustand";
import { useStrategyEditorStore } from "./strategyEditorStore";

type OnboardingState = {
	isActive: boolean;
	currentStep: number;
};

type OnboardingActions = {
	start: () => void;
	nextStep: () => void;
	goToStep: (step: number) => void;
	end: () => void;
	reset: () => void;
};

const initialState: OnboardingState = {
	isActive: false,
	currentStep: 0,
};

export const useOnboardingStore = create<OnboardingState & OnboardingActions>(
	(set) => ({
		...initialState,
		start: () => {
			// Reset the strategy editor state before starting
			useStrategyEditorStore.getState().reset();
			set({ isActive: true, currentStep: 1 });
		},
		nextStep: () => set((state) => ({ currentStep: state.currentStep + 1 })),
		goToStep: (step) => set({ currentStep: step }),
		end: () => {
			localStorage.setItem("onboardingCompleted", "true");
			set({ isActive: false, currentStep: 0 });
		},
		reset: () => set(initialState),
	}),
);
