// src/components/OnboardingTutorial.tsx

import { Sparkles } from "lucide-react";
import type React from "react";
import { useEffect } from "react";

import { useTranslation } from "react-i18next";
import {
	ACTIONS,
	type EventData,
	Joyride,
	STATUS,
	type Step,
} from "react-joyride";
import {
	Dialog,
	DialogContent,
	DialogDescription,
	DialogFooter,
	DialogHeader,
	DialogTitle,
} from "@/components/ui/dialog";
import { useOnboardingStore } from "../stores/onboardingStore";
import { useStrategyEditorStore } from "../stores/strategyEditorStore";
import { Button } from "./ui/button";

const OnboardingTutorial: React.FC = () => {
	const { t } = useTranslation("strategy-editor");
	const { isActive, currentStep, nextStep, goToStep, end } =
		useOnboardingStore();

	const steps: Step[] = [
		{
			target: '[data-tutorial-id="strategy-name-input"]',
			title: t("onboarding.step1.title"),
			content: t("onboarding.step1.content"),
			skipBeacon: true,
		},
		{
			target: '[data-tutorial-id="indicators-accordion"]',
			title: t("onboarding.step2.title"),
			content: t("onboarding.step2.content"),
			skipBeacon: true,
		},
		{
			target: '[data-tutorial-id="rsi-block"]',
			title: t("onboarding.step3.title"),
			content: t("onboarding.step3.content"),
			skipBeacon: true,
		},
		{
			target: '[data-tutorial-id="rsi-condition-block"]',
			title: t("onboarding.step4.title"),
			content: t("onboarding.step4.content"),
			skipBeacon: true,
		},
		{
			target: '[data-tutorial-id="direction-long-button"]',
			title: t("onboarding.step5.title"),
			content: t("onboarding.step5.content"),
			skipBeacon: true,
		},
		{
			target: '[data-tutorial-id="run-backtest-button"]',
			title: t("onboarding.step6.title"),
			content: t("onboarding.step6.content"),
			skipBeacon: true,
		},
	];

	useEffect(() => {
		if (!isActive) return;

		// Using polling to track changes in the DOM or store that do not trigger a re-render
		const interval = setInterval(() => {
			const store = useStrategyEditorStore.getState();

			switch (currentStep) {
				case 2: {
					// Waiting for the accordion to open
					const indicatorsAccordion = document.querySelector(
						'[data-tutorial-id="indicators-accordion"]',
					);
					if (indicatorsAccordion?.getAttribute("data-state") === "open") {
						nextStep();
					}
					break;
				}
				case 4: {
					// Waiting for RSI settings (ensuring the block exists in the DOM)
					const rsiBlock = document.querySelector(
						'[data-tutorial-id="rsi-condition-block"]',
					);
					const rsiCondition = store.entryConditions?.children?.find(
						(c) => c.type === "rsi_condition",
					);
					if (
						rsiBlock &&
						rsiCondition &&
						rsiCondition.params?.operator === "lt" &&
						rsiCondition.params?.value === 30
					) {
						nextStep();
					}
					break;
				}
				case 5: // Waiting for direction selection
					if (store.initialization.params.direction === "LONG") {
						nextStep();
					}
					break;
			}
		}, 500);

		return () => clearInterval(interval);
	}, [isActive, currentStep, nextStep]);

	const handleJoyrideCallback = (data: EventData) => {
		const { status, action, index, type } = data;
		const finishedStatuses: string[] = [STATUS.FINISHED, STATUS.SKIPPED];

		if (finishedStatuses.includes(status)) {
			end();
			return;
		}

		// Handle next button clicks
		if (action === ACTIONS.NEXT && type === "step:after") {
			if (index === 0) {
				// After step 1 (name)
				goToStep(2);
			}
		}
	};

	if (!isActive) {
		return null;
	}

	if (currentStep === 7) {
		return (
			<Dialog open={true} onOpenChange={end}>
				<DialogContent>
					<DialogHeader>
						<DialogTitle className="flex items-center">
							<Sparkles className="w-6 h-6 mr-2 text-yellow-400" />
							{t("onboarding.finalDialog.title")}
						</DialogTitle>
						<DialogDescription>
							{t("onboarding.finalDialog.description")}
						</DialogDescription>
					</DialogHeader>
					<DialogFooter>
						<Button onClick={end}>{t("onboarding.finalDialog.button")}</Button>
					</DialogFooter>
				</DialogContent>
			</Dialog>
		);
	}

	return (
		<Joyride
			steps={steps}
			run={isActive}
			stepIndex={currentStep - 1}
			continuous
			onEvent={handleJoyrideCallback}
			options={{
				showProgress: true,
				blockTargetInteraction: false,
				overlayClickAction: false,
				skipScroll: false,
				arrowColor: "#1C2025",
				backgroundColor: "#1C2025",
				primaryColor: "#3B82F6",
				textColor: "#D1D5DB",
				zIndex: 10000,
				buttons: ["back", "close", "primary", "skip"],
			}}
			styles={{
				tooltip: {
					border: "1px solid #2A3038",
				},
				buttonPrimary: {
					borderRadius: "8px",
					fontSize: "14px",
					padding: "8px 12px",
				},
				buttonBack: {
					color: "#a1a1aa",
				},
				buttonSkip: {
					color: "#a1a1aa",
					fontSize: "12px",
				},
				overlay: {
					backgroundColor: "rgba(0, 0, 0, 0.5)",
				},
			}}
		/>
	);
};

export default OnboardingTutorial;
