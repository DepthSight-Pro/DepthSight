// src/components/OnboardingTutorial.tsx

import {
	CheckCircle2,
	ChevronLeft,
	ChevronRight,
	Compass,
	Lightbulb,
	Plus,
	Rocket,
	Sparkles,
	X,
} from "lucide-react";
import type React from "react";
import {
	useCallback,
	useEffect,
	useLayoutEffect,
	useRef,
	useState,
} from "react";
import { createPortal } from "react-dom";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import {
	Dialog,
	DialogContent,
	DialogDescription,
	DialogFooter,
	DialogHeader,
	DialogTitle,
} from "@/components/ui/dialog";
import { useToast } from "@/components/ui/use-toast";
import { useOnboardingStore } from "../stores/onboardingStore";
import { useStrategyEditorStore } from "../stores/strategyEditorStore";

/* ────────────────────────────── Step Definitions ────────────────────────── */

interface OnboardingStep {
	target: string;
	titleKey: string;
	contentKey: string;
	categoryKey: string;
	preferredPlacement?: "top" | "bottom" | "left" | "right";
	spotlightPadding?: number;
	allowQuickAction?: "add_rsi";
}

const STEPS: OnboardingStep[] = [
	{
		target: '[data-tutorial-id="strategy-params-card"]',
		titleKey: "onboarding.step1.title",
		contentKey: "onboarding.step1.content",
		categoryKey: "onboarding.catConfig",
		preferredPlacement: "left",
		spotlightPadding: 8,
	},
	{
		target: '[data-tutorial-id="ai-copilot-card"]',
		titleKey: "onboarding.step2.title",
		contentKey: "onboarding.step2.content",
		categoryKey: "onboarding.catAi",
		preferredPlacement: "bottom",
		spotlightPadding: 10,
	},
	{
		target: '[data-tutorial-id="palette-panel"]',
		titleKey: "onboarding.step3.title",
		contentKey: "onboarding.step3.content",
		categoryKey: "onboarding.catPalette",
		preferredPlacement: "right",
		spotlightPadding: 8,
	},
	{
		target: '[data-tutorial-id="entry-conditions-dropzone"]',
		titleKey: "onboarding.step4.title",
		contentKey: "onboarding.step4.content",
		categoryKey: "onboarding.catCanvas",
		preferredPlacement: "top",
		spotlightPadding: 10,
		allowQuickAction: "add_rsi",
	},
	{
		target: '[data-tutorial-id="filters-dropzone"]',
		titleKey: "onboarding.step5.title",
		contentKey: "onboarding.step5.content",
		categoryKey: "onboarding.catFilters",
		preferredPlacement: "bottom",
		spotlightPadding: 10,
	},
	{
		target: '[data-tutorial-id="initialization-section"]',
		titleKey: "onboarding.step6.title",
		contentKey: "onboarding.step6.content",
		categoryKey: "onboarding.catRisk",
		preferredPlacement: "top",
		spotlightPadding: 10,
	},
	{
		target: '[data-tutorial-id="management-section"]',
		titleKey: "onboarding.step7.title",
		contentKey: "onboarding.step7.content",
		categoryKey: "onboarding.catManagement",
		preferredPlacement: "top",
		spotlightPadding: 10,
	},
	{
		target: '[data-tutorial-id="backtest-panel"]',
		titleKey: "onboarding.step8.title",
		contentKey: "onboarding.step8.content",
		categoryKey: "onboarding.catLaunch",
		preferredPlacement: "left",
		spotlightPadding: 8,
	},
	{
		target: '[data-tutorial-id="deploy-panel"]',
		titleKey: "onboarding.step9.title",
		contentKey: "onboarding.step9.content",
		categoryKey: "onboarding.catDeploy",
		preferredPlacement: "left",
		spotlightPadding: 8,
	},
];

/* ────────────────────────────── Geometry & Placement ────────────────────── */

const SCREEN_PADDING = 16;
const TOOLTIP_GAP = 14;
const ARROW_SIZE = 8;
const OVERLAY_Z = 9999;

interface Rect {
	top: number;
	left: number;
	width: number;
	height: number;
}

function clamp(val: number, min: number, max: number): number {
	return Math.max(min, Math.min(max, val));
}

type Placement = "top" | "bottom" | "left" | "right";

interface TooltipLayout {
	top: number;
	left: number;
	width: number;
	placement: Placement;
	arrowStyle: React.CSSProperties;
}

function calculateTooltipLayout(
	target: Rect,
	tooltipSize: { width: number; height: number },
	preferred: Placement,
	padding: number,
): TooltipLayout {
	const vw = typeof window !== "undefined" ? window.innerWidth : 1920;
	const vh = typeof window !== "undefined" ? window.innerHeight : 1080;

	const width = Math.min(360, Math.max(280, vw - 32));
	const height = Math.max(160, tooltipSize.height || 220);

	const tTop = target.top - padding;
	const tBottom = target.top + target.height + padding;
	const tLeft = target.left - padding;
	const tRight = target.left + target.width + padding;

	const spaceTop = tTop;
	const spaceBottom = vh - tBottom;
	const spaceLeft = tLeft;
	const spaceRight = vw - tRight;

	// Determine candidate placement order based on space
	const order: Placement[] = [preferred];
	const remaining: Placement[] = ["bottom", "top", "right", "left"].filter(
		(p) => p !== preferred,
	) as Placement[];

	// Sort remaining by available space
	remaining.sort((a, b) => {
		const sA =
			a === "top"
				? spaceTop
				: a === "bottom"
					? spaceBottom
					: a === "left"
						? spaceLeft
						: spaceRight;
		const sB =
			b === "top"
				? spaceTop
				: b === "bottom"
					? spaceBottom
					: b === "left"
						? spaceLeft
						: spaceRight;
		return sB - sA;
	});

	const candidates = [...order, ...remaining];

	let chosenPlacement: Placement = preferred;

	for (const p of candidates) {
		if (p === "top" && spaceTop >= height + TOOLTIP_GAP + SCREEN_PADDING) {
			chosenPlacement = "top";
			break;
		}
		if (p === "bottom" && spaceBottom >= height + TOOLTIP_GAP + SCREEN_PADDING) {
			chosenPlacement = "bottom";
			break;
		}
		if (p === "left" && spaceLeft >= width + TOOLTIP_GAP + SCREEN_PADDING) {
			chosenPlacement = "left";
			break;
		}
		if (p === "right" && spaceRight >= width + TOOLTIP_GAP + SCREEN_PADDING) {
			chosenPlacement = "right";
			break;
		}
	}

	let top = 0;
	let left = 0;

	if (chosenPlacement === "top") {
		top = tTop - TOOLTIP_GAP - height;
		left = target.left + target.width / 2 - width / 2;
	} else if (chosenPlacement === "bottom") {
		top = tBottom + TOOLTIP_GAP;
		left = target.left + target.width / 2 - width / 2;
	} else if (chosenPlacement === "left") {
		top = target.top + target.height / 2 - height / 2;
		left = tLeft - TOOLTIP_GAP - width;
	} else if (chosenPlacement === "right") {
		top = target.top + target.height / 2 - height / 2;
		left = tRight + TOOLTIP_GAP;
	}

	// Clamp to viewport
	const clampedTop = clamp(top, SCREEN_PADDING, vh - height - SCREEN_PADDING);
	const clampedLeft = clamp(left, SCREEN_PADDING, vw - width - SCREEN_PADDING);

	// Compute arrow style pointing towards the center of the target
	let arrowStyle: React.CSSProperties = {};
	const targetCenterX = target.left + target.width / 2;
	const targetCenterY = target.top + target.height / 2;

	if (chosenPlacement === "top") {
		const arrowX = clamp(targetCenterX - clampedLeft, 20, width - 20);
		arrowStyle = {
			bottom: -ARROW_SIZE,
			left: arrowX,
			transform: "translateX(-50%) rotate(45deg)",
			borderBottom: "1px solid rgba(0, 212, 255, 0.35)",
			borderRight: "1px solid rgba(0, 212, 255, 0.35)",
			backgroundColor: "rgba(13, 19, 34, 0.85)",
			backdropFilter: "blur(16px)",
			WebkitBackdropFilter: "blur(16px)",
		};
	} else if (chosenPlacement === "bottom") {
		const arrowX = clamp(targetCenterX - clampedLeft, 20, width - 20);
		arrowStyle = {
			top: -ARROW_SIZE,
			left: arrowX,
			transform: "translateX(-50%) rotate(45deg)",
			borderTop: "1px solid rgba(0, 212, 255, 0.35)",
			borderLeft: "1px solid rgba(0, 212, 255, 0.35)",
			backgroundColor: "rgba(13, 19, 34, 0.85)",
			backdropFilter: "blur(16px)",
			WebkitBackdropFilter: "blur(16px)",
		};
	} else if (chosenPlacement === "left") {
		const arrowY = clamp(targetCenterY - clampedTop, 20, height - 20);
		arrowStyle = {
			right: -ARROW_SIZE,
			top: arrowY,
			transform: "translateY(-50%) rotate(45deg)",
			borderTop: "1px solid rgba(0, 212, 255, 0.35)",
			borderRight: "1px solid rgba(0, 212, 255, 0.35)",
			backgroundColor: "rgba(13, 19, 34, 0.85)",
			backdropFilter: "blur(16px)",
			WebkitBackdropFilter: "blur(16px)",
		};
	} else if (chosenPlacement === "right") {
		const arrowY = clamp(targetCenterY - clampedTop, 20, height - 20);
		arrowStyle = {
			left: -ARROW_SIZE,
			top: arrowY,
			transform: "translateY(-50%) rotate(45deg)",
			borderBottom: "1px solid rgba(0, 212, 255, 0.35)",
			borderLeft: "1px solid rgba(0, 212, 255, 0.35)",
			backgroundColor: "rgba(13, 19, 34, 0.85)",
			backdropFilter: "blur(16px)",
			WebkitBackdropFilter: "blur(16px)",
		};
	}

	return {
		top: clampedTop,
		left: clampedLeft,
		width,
		placement: chosenPlacement,
		arrowStyle,
	};
}

/** Generate SVG path with rounded rectangle hole cutout using evenodd fill rule */
function generateCutoutPath(
	vw: number,
	vh: number,
	rect: Rect | null,
	padding: number,
	r = 14,
): string {
	if (!rect) {
		return `M 0 0 H ${vw} V ${vh} H 0 Z`;
	}

	const x = Math.max(0, rect.left - padding);
	const y = Math.max(0, rect.top - padding);
	const w = Math.min(vw - x, rect.width + padding * 2);
	const h = Math.min(vh - y, rect.height + padding * 2);
	const rx = Math.min(r, w / 2, h / 2);

	// Outer clockwise rectangle + inner counter-clockwise rounded rectangle
	return (
		`M 0 0 H ${vw} V ${vh} H 0 Z ` +
		`M ${x + rx} ${y} ` +
		`H ${x + w - rx} ` +
		`a ${rx} ${rx} 0 0 1 ${rx} ${rx} ` +
		`V ${y + h - rx} ` +
		`a ${rx} ${rx} 0 0 1 -${rx} ${rx} ` +
		`H ${x + rx} ` +
		`a ${rx} ${rx} 0 0 1 -${rx} -${rx} ` +
		`V ${y + rx} ` +
		`a ${rx} ${rx} 0 0 1 ${rx} -${rx} Z`
	);
}

/* ────────────────────────────── Component ────────────────────────────────── */

const OnboardingTutorial: React.FC = () => {
	const { t } = useTranslation("strategy-editor");
	const { toast } = useToast();
	const { isActive, currentStep, nextStep, prevStep, goToStep, end } =
		useOnboardingStore();
	const addCondition = useStrategyEditorStore((s) => s.addCondition);

	const [targetRect, setTargetRect] = useState<Rect | null>(null);
	const [tooltipSize, setTooltipSize] = useState({ width: 340, height: 220 });
	const [isTransitioning, setIsTransitioning] = useState(false);

	const tooltipRef = useRef<HTMLDivElement>(null);
	const totalSteps = STEPS.length;
	const stepIndex = currentStep - 1;
	const step = STEPS[stepIndex] ?? null;

	// Measure tooltip DOM dimensions only when step changes or becomes active
	useLayoutEffect(() => {
		if (tooltipRef.current) {
			const rect = tooltipRef.current.getBoundingClientRect();
			if (rect.width > 0 && rect.height > 0) {
				setTooltipSize((prev) => {
					if (
						Math.abs(prev.width - rect.width) < 1 &&
						Math.abs(prev.height - rect.height) < 1
					) {
						return prev;
					}
					return { width: rect.width, height: rect.height };
				});
			}
		}
	}, [stepIndex, isActive]);

	// Locate and track target element across all resolutions, mutations, and scrolling containers
	useEffect(() => {
		if (!isActive || !step) {
			return;
		}

		let rafId: number;
		let isMounted = true;

		const updateTargetRect = () => {
			if (!isMounted) return;
			const el = document.querySelector(step.target);
			if (el && el instanceof HTMLElement) {
				const r = el.getBoundingClientRect();
				// Only update if visible
				if (r.width > 0 && r.height > 0) {
					setTargetRect((prev) => {
						if (
							prev &&
							Math.abs(prev.top - r.top) < 0.5 &&
							Math.abs(prev.left - r.left) < 0.5 &&
							Math.abs(prev.width - r.width) < 0.5 &&
							Math.abs(prev.height - r.height) < 0.5
						) {
							return prev;
						}
						return {
							top: r.top,
							left: r.left,
							width: r.width,
							height: r.height,
						};
					});
					return;
				}
			}
			setTargetRect(null);
		};

		const startTrackingLoop = (duration = 600) => {
			cancelAnimationFrame(rafId);
			const start = Date.now();
			const loop = () => {
				if (!isMounted) return;
				updateTargetRect();
				if (Date.now() - start < duration) {
					rafId = requestAnimationFrame(loop);
				}
			};
			rafId = requestAnimationFrame(loop);
		};

		// Scroll target element smoothly into view if offscreen
		const scrollTimer = setTimeout(() => {
			const el = document.querySelector(step.target);
			if (el && el instanceof HTMLElement) {
				el.scrollIntoView({
					behavior: "smooth",
					block: "nearest",
					inline: "nearest",
				});
			}
		}, 60);

		// Listen to all scroll events across any containers using capture: true
		window.addEventListener("scroll", updateTargetRect, {
			capture: true,
			passive: true,
		});
		window.addEventListener("resize", updateTargetRect, { passive: true });

		// Initial settling loop
		startTrackingLoop(800);

		// Subscribe to strategy store changes so adding/removing blocks immediately updates tutorial layout
		const unsubscribeStore = useStrategyEditorStore.subscribe(() => {
			startTrackingLoop(700);
		});

		return () => {
			isMounted = false;
			clearTimeout(scrollTimer);
			cancelAnimationFrame(rafId);
			window.removeEventListener("scroll", updateTargetRect, {
				capture: true,
			});
			window.removeEventListener("resize", updateTargetRect);
			unsubscribeStore();
		};
	}, [isActive, step]);

	// Keyboard shortcuts for quick navigation
	useEffect(() => {
		if (!isActive) return;

		const handleKeyDown = (e: KeyboardEvent) => {
			// Don't intercept if user is typing in an input
			const targetTag = (e.target as HTMLElement)?.tagName?.toLowerCase();
			if (targetTag === "input" || targetTag === "textarea") {
				if (e.key === "Escape") {
					end();
				}
				return;
			}

			if (e.key === "Escape") {
				end();
			} else if (e.key === "ArrowRight" || e.key === "Enter") {
				e.preventDefault();
				if (currentStep < totalSteps) {
					nextStep();
				} else {
					end();
				}
			} else if (e.key === "ArrowLeft") {
				e.preventDefault();
				if (currentStep > 1) {
					prevStep();
				}
			}
		};

		window.addEventListener("keydown", handleKeyDown);
		return () => window.removeEventListener("keydown", handleKeyDown);
	}, [isActive, currentStep, totalSteps, nextStep, prevStep, end]);

	const handleNext = useCallback(() => {
		if (stepIndex >= totalSteps - 1) {
			end();
			return;
		}
		setIsTransitioning(true);
		setTimeout(() => {
			nextStep();
			setIsTransitioning(false);
		}, 120);
	}, [stepIndex, totalSteps, end, nextStep]);

	const handlePrev = useCallback(() => {
		if (stepIndex > 0) {
			setIsTransitioning(true);
			setTimeout(() => {
				prevStep();
				setIsTransitioning(false);
			}, 120);
		}
	}, [stepIndex, prevStep]);

	const handleQuickAddRsi = useCallback(() => {
		addCondition("entryConditions", "rsi_condition", null);
		toast({
			title: t("onboarding.quickAddRsi"),
			description: t(
				"onboarding.rsiAddedToast",
				"Блок RSI добавлен в условия входа!",
			),
		});

		// Smoothly re-scroll target element into view after AI Co-Pilot unmounts
		setTimeout(() => {
			const el = document.querySelector('[data-tutorial-id="entry-conditions-dropzone"]');
			if (el && el instanceof HTMLElement) {
				el.scrollIntoView({
					behavior: "smooth",
					block: "nearest",
					inline: "nearest",
				});
			}
		}, 40);
	}, [addCondition, toast, t]);

	// Final completion celebration modal
	if (isActive && currentStep > totalSteps) {
		return (
			<Dialog open={true} onOpenChange={end}>
				<DialogContent className="glass border border-white/10 bg-[#0e131f]/85 text-white shadow-2xl rounded-3xl sm:max-w-md backdrop-blur-2xl p-6 overflow-hidden">
					<div className="pointer-events-none absolute -top-20 left-1/2 -translate-x-1/2 w-64 h-64 rounded-full bg-cyan/20 blur-3xl" />
					<DialogHeader>
						<div className="flex items-center justify-center w-14 h-14 rounded-2xl bg-cyan/10 border border-cyan/30 text-cyan mx-auto mb-3 shadow-[0_0_24px_rgba(0,212,255,0.4)]">
							<Rocket className="w-7 h-7 text-cyan animate-pulse" />
						</div>
						<DialogTitle className="text-center text-xl font-bold text-white tracking-tight">
							{t("onboarding.finalDialog.title")}
						</DialogTitle>
						<DialogDescription className="text-center text-white/60 text-sm mt-2 leading-relaxed">
							{t("onboarding.finalDialog.description")}
						</DialogDescription>
					</DialogHeader>

					<div className="my-4 p-3.5 rounded-2xl border border-white/5 bg-white/[0.02] flex items-center gap-3">
						<CheckCircle2 className="w-5 h-5 text-emerald-400 shrink-0" />
						<div className="text-xs text-white/70 leading-normal">
							{t(
								"onboarding.finalDialog.tip",
								"Все инструменты готовы к работе. Вы можете запустить бэктест прямо сейчас!",
							)}
						</div>
					</div>

					<DialogFooter className="mt-2">
						<Button
							onClick={end}
							className="w-full bg-gradient-to-r from-cyan to-azure hover:brightness-110 text-black font-semibold text-sm py-2.5 rounded-xl shadow-[0_0_20px_rgba(0,212,255,0.4)] transition-all"
						>
							{t("onboarding.finalDialog.button")}
						</Button>
					</DialogFooter>
				</DialogContent>
			</Dialog>
		);
	}

	if (!isActive || !step) return null;

	const padding = step.spotlightPadding ?? 8;
	const layout = targetRect
		? calculateTooltipLayout(
				targetRect,
				tooltipSize,
				step.preferredPlacement ?? "bottom",
				padding,
			)
		: null;

	const vw = typeof window !== "undefined" ? window.innerWidth : 1920;
	const vh = typeof window !== "undefined" ? window.innerHeight : 1080;
	const cutoutPath = generateCutoutPath(vw, vh, targetRect, padding, 14);

	return createPortal(
		<div
			style={{
				position: "fixed",
				inset: 0,
				zIndex: OVERLAY_Z,
				pointerEvents: "none",
			}}
			aria-label="Interactive Strategy Editor Tutorial"
		>
			{/* SVG Dimming Backdrop with Evenodd Cutout */}
			<svg
				style={{
					position: "fixed",
					inset: 0,
					width: "100%",
					height: "100%",
					pointerEvents: "none",
				}}
			>
				<defs>
					<linearGradient
						id="spotlight-border-grad"
						x1="0%"
						y1="0%"
						x2="100%"
						y2="100%"
					>
						<stop offset="0%" stopColor="#00d4ff" />
						<stop offset="100%" stopColor="#0080ff" />
					</linearGradient>
					<filter
						id="spotlight-neon-glow"
						x="-20%"
						y="-20%"
						width="140%"
						height="140%"
					>
						<feDropShadow
							dx="0"
							dy="0"
							stdDeviation="8"
							floodColor="#00d4ff"
							floodOpacity="0.45"
						/>
					</filter>
				</defs>

				{/* Unpainted hole allows clicks and drags through the cutout */}
				<path
					d={cutoutPath}
					fill="rgba(6, 10, 20, 0.55)"
					fillRule="evenodd"
					style={{
						pointerEvents: "none",
						transition: "d 0.28s cubic-bezier(0.4, 0, 0.2, 1)",
					}}
				/>

				{/* Animated glowing neon ring around spotlight target */}
				{targetRect && (
					<>
						<rect
							x={targetRect.left - padding}
							y={targetRect.top - padding}
							width={targetRect.width + padding * 2}
							height={targetRect.height + padding * 2}
							rx={14}
							fill="none"
							stroke="url(#spotlight-border-grad)"
							strokeWidth="2"
							filter="url(#spotlight-neon-glow)"
							style={{
								pointerEvents: "none",
								transition:
									"x 0.28s cubic-bezier(0.4, 0, 0.2, 1), y 0.28s cubic-bezier(0.4, 0, 0.2, 1), width 0.28s cubic-bezier(0.4, 0, 0.2, 1), height 0.28s cubic-bezier(0.4, 0, 0.2, 1)",
							}}
						/>
						{/* Subtle pulsing outer accent */}
						<rect
							x={targetRect.left - padding - 3}
							y={targetRect.top - padding - 3}
							width={targetRect.width + (padding + 3) * 2}
							height={targetRect.height + (padding + 3) * 2}
							rx={17}
							fill="none"
							stroke="rgba(0, 212, 255, 0.25)"
							strokeWidth="1"
							className="animate-pulse"
							style={{ pointerEvents: "none" }}
						/>
					</>
				)}
			</svg>

			{/* Tooltip Card */}
			{layout && (
				<div
					ref={tooltipRef}
					style={{
						position: "fixed",
						top: layout.top,
						left: layout.left,
						width: layout.width,
						zIndex: OVERLAY_Z + 10,
						pointerEvents: "auto",
						opacity: isTransitioning ? 0 : 1,
						transition: isTransitioning
							? "opacity 0.12s ease"
							: "top 0.28s cubic-bezier(0.4, 0, 0.2, 1), left 0.28s cubic-bezier(0.4, 0, 0.2, 1), opacity 0.2s ease",
					}}
					className="onboarding-tooltip"
				>
					{/* Pointer Arrow */}
					<div
						style={{
							position: "absolute",
							width: ARROW_SIZE * 2,
							height: ARROW_SIZE * 2,
							zIndex: OVERLAY_Z + 11,
							...layout.arrowStyle,
						}}
					/>

					{/* Card Container */}
					<div className="glass relative rounded-2xl border border-cyan/35 bg-[#0d1322]/80 backdrop-blur-2xl shadow-[0_16px_45px_rgba(0,0,0,0.6)] overflow-hidden">
						{/* Top Progress Bar */}
						<div className="h-1 bg-white/5 relative">
							<div
								className="h-full bg-gradient-to-r from-cyan to-azure transition-all duration-300 ease-out"
								style={{
									width: `${((stepIndex + 1) / totalSteps) * 100}%`,
								}}
							/>
						</div>

						{/* Content Area */}
						<div className="p-4 sm:p-5">
							{/* Header: Category Badge + Step Counter + Close */}
							<div className="flex items-center justify-between mb-2.5">
								<div className="flex items-center gap-2">
									<span className="px-2 py-0.5 rounded-full text-[10px] font-bold tracking-wider uppercase bg-cyan/15 border border-cyan/30 text-cyan">
										{t(step.categoryKey)}
									</span>
									<span className="text-[11px] font-medium text-white/40">
										{t("onboarding.stepBadge", {
											current: stepIndex + 1,
											total: totalSteps,
										})}
									</span>
								</div>

								<button
									type="button"
									onClick={end}
									className="p-1 rounded-lg text-white/40 hover:text-white hover:bg-white/10 transition-colors"
									aria-label="Close tutorial"
								>
									<X className="w-4 h-4" />
								</button>
							</div>

							{/* Step Title */}
							<h3 className="text-base font-bold text-white mb-2 leading-snug tracking-tight">
								{t(step.titleKey)}
							</h3>

							{/* Description */}
							<p className="text-xs sm:text-[13px] text-white/70 leading-relaxed mb-3.5">
								{t(step.contentKey)}
							</p>

							{/* Quick Action Button (e.g. Add RSI directly to canvas) */}
							{step.allowQuickAction === "add_rsi" && (
								<div className="mb-3.5">
									<Button
										type="button"
										size="sm"
										variant="outline"
										onClick={handleQuickAddRsi}
										className="w-full text-xs font-medium border-cyan/40 bg-cyan/10 hover:bg-cyan/20 text-cyan flex items-center justify-center gap-1.5 py-1.5 rounded-xl transition-all"
									>
										<Plus className="w-3.5 h-3.5" />
										<span>{t("onboarding.quickAddRsi")}</span>
									</Button>
								</div>
							)}

							{/* Action Tip Banner */}
							<div className="flex items-center gap-2 px-2.5 py-1.5 rounded-xl bg-white/[0.03] border border-white/5 mb-4">
								<Lightbulb className="w-3.5 h-3.5 text-amber-400 shrink-0" />
								<span className="text-[11px] text-white/50 leading-tight">
									{t("onboarding.actionHint")}
								</span>
							</div>

							{/* Footer Navigation */}
							<div className="flex items-center justify-between pt-1 border-t border-white/5">
								{/* Step Dots (Clickable) */}
								<div className="flex items-center gap-1">
									{Array.from({ length: totalSteps }).map((_, i) => (
										<button
											key={i}
											type="button"
											onClick={() => goToStep(i + 1)}
											className={`rounded-full transition-all duration-200 cursor-pointer ${
												i === stepIndex
													? "w-4 h-1.5 bg-cyan shadow-[0_0_8px_rgba(0,212,255,0.8)]"
													: i < stepIndex
														? "w-1.5 h-1.5 bg-cyan/50 hover:bg-cyan/80"
														: "w-1.5 h-1.5 bg-white/20 hover:bg-white/40"
											}`}
											aria-label={`Go to step ${i + 1}`}
										/>
									))}
								</div>

								{/* Action Buttons */}
								<div className="flex items-center gap-1.5">
									{stepIndex > 0 && (
										<button
											type="button"
											onClick={handlePrev}
											className="flex items-center justify-center w-7 h-7 rounded-lg text-white/50 hover:text-white hover:bg-white/5 transition-colors"
											aria-label={t("onboarding.prevButton")}
										>
											<ChevronLeft className="w-4 h-4" />
										</button>
									)}

									<button
										type="button"
										onClick={handleNext}
										className="flex items-center gap-1 px-3.5 py-1.5 rounded-xl bg-gradient-to-r from-cyan to-azure hover:brightness-110 text-black text-xs font-semibold shadow-[0_0_14px_rgba(0,212,255,0.3)] transition-all"
									>
										{stepIndex === totalSteps - 1 ? (
											<>
												<span>{t("onboarding.finishButton")}</span>
												<Sparkles className="w-3.5 h-3.5" />
											</>
										) : (
											<>
												<span>{t("onboarding.nextButton")}</span>
												<ChevronRight className="w-3.5 h-3.5" />
											</>
										)}
									</button>
								</div>
							</div>

							{/* Keyboard shortcut hint */}
							<div className="mt-2 text-center">
								<span className="text-[10px] text-white/30">
									{t("onboarding.keyboardHint")}
								</span>
							</div>
						</div>
					</div>
				</div>
			)}

			{/* Fallback floating card if element is currently loading */}
			{!layout && step && (
				<div
					ref={tooltipRef}
					style={{
						position: "fixed",
						top: "50%",
						left: "50%",
						transform: "translate(-50%, -50%)",
						width: 320,
						zIndex: OVERLAY_Z + 10,
						pointerEvents: "auto",
					}}
				>
					<div className="glass rounded-2xl border border-cyan/25 bg-[#0d1322]/80 backdrop-blur-2xl shadow-2xl p-5 text-center">
						<div className="animate-pulse flex items-center justify-center gap-2 text-cyan text-xs font-medium mb-3">
							<Compass className="w-4 h-4 animate-spin" />
							<span>{t("onboarding.waitingForElement")}</span>
						</div>
						<Button
							size="sm"
							variant="ghost"
							onClick={handleNext}
							className="text-xs text-white/60 hover:text-white"
						>
							{t("onboarding.nextButton")}
						</Button>
					</div>
				</div>
			)}
		</div>,
		document.body,
	);
};

export default OnboardingTutorial;
