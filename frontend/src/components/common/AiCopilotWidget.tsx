// frontend/src/components/common/AiCopilotWidget.tsx

import {
	Loader2,
	Paperclip,
	Rocket,
	Send,
	Trash2,
	WandSparkles,
	X,
} from "lucide-react";
import type React from "react";
import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import Markdown from "react-markdown";
import { useLocation, useNavigate, useParams } from "react-router-dom";
import remarkGfm from "remark-gfm";
import { Button } from "@/components/ui/button";
import {
	Sheet,
	SheetContent,
	SheetDescription,
	SheetHeader,
	SheetTitle,
} from "@/components/ui/sheet";
import { Textarea } from "@/components/ui/textarea";
import {
	Tooltip,
	TooltipContent,
	TooltipProvider,
	TooltipTrigger,
} from "@/components/ui/tooltip";
import {
	type AIChatRequest,
	useGetChatHistory,
	usePostChatMessage,
} from "@/lib/api";
import { cn } from "@/lib/utils";
import { type Message, useAiCopilotStore } from "@/stores/aiCopilotStore";
import { useStrategyEditorStore } from "@/stores/strategyEditorStore";
import { AgentWorkspace } from "../agent/AgentWorkspace";

export type { Message } from "@/stores/aiCopilotStore";

const GENERATION_TRIGGER_PHRASES = [
	"Would you like me to prepare an updated strategy configuration?",
	"Please click the button",
	"Generate in Editor",
	"Create in Editor",
];

const containsGenerationTrigger = (text: string): boolean => {
	return GENERATION_TRIGGER_PHRASES.some((phrase) => text.includes(phrase));
};

const MAX_IMAGE_DIMENSION = 1000;
const ALLOWED_IMAGE_TYPES = new Set(["image/jpeg", "image/png", "image/webp"]);

type SelectedImage = { base64: string; type: string };

const getImageSrc = (base64: string, mimeType = "image/jpeg") =>
	base64.startsWith("data:") ? base64 : `data:${mimeType};base64,${base64}`;

const processImageFile = (file: File): Promise<SelectedImage> => {
	if (!ALLOWED_IMAGE_TYPES.has(file.type)) {
		return Promise.reject(
			new Error("Unsupported image type. Use JPEG, PNG, or WebP."),
		);
	}

	return new Promise((resolve, reject) => {
		const reader = new FileReader();
		reader.onerror = () => reject(new Error("Failed to read image file."));
		reader.onload = () => {
			const image = new Image();
			image.onerror = () => reject(new Error("Failed to decode image file."));
			image.onload = () => {
				const scale = Math.min(
					1,
					MAX_IMAGE_DIMENSION / Math.max(image.width, image.height),
				);
				const width = Math.max(1, Math.round(image.width * scale));
				const height = Math.max(1, Math.round(image.height * scale));
				const canvas = document.createElement("canvas");
				canvas.width = width;
				canvas.height = height;
				const ctx = canvas.getContext("2d");
				if (!ctx) {
					reject(new Error("Canvas is not available in this browser."));
					return;
				}
				ctx.drawImage(image, 0, 0, width, height);
				const mimeType =
					file.type === "image/png"
						? "image/png"
						: file.type === "image/webp"
							? "image/webp"
							: "image/jpeg";
				const dataUrl = canvas.toDataURL(mimeType, 0.86);
				const [, rawBase64 = ""] = dataUrl.split(",", 2);
				resolve({ base64: rawBase64, type: mimeType });
			};
			image.src = String(reader.result || "");
		};
		reader.readAsDataURL(file);
	});
};

// --- Component 1: Launcher Button ---
const AiCopilotLauncher: React.FC<{ onClick: () => void }> = ({ onClick }) => {
	const { t } = useTranslation("navigation");
	return (
		<TooltipProvider>
			<Tooltip>
				<TooltipTrigger asChild>
					<div className="fixed bottom-4 right-4 z-50">
						<Button
							size="icon"
							className="rounded-full w-14 h-14 shadow-lg relative overflow-hidden bg-gradient-to-r from-purple-500 to-indigo-600 text-white hover:shadow-xl transition-shadow duration-300 ease-in-out before:content-[''] before:absolute before:top-0 before:-left-full before:w-full before:h-full before:bg-gradient-to-r before:from-transparent before:via-white/30 before:to-transparent before:animate-[shimmer_2s_infinite]"
							onClick={onClick}
							aria-label={t("ai_assistant.ariaLabel")}
						>
							<WandSparkles className="h-7 w-7" />
						</Button>
					</div>
				</TooltipTrigger>
				<TooltipContent>
					<p>{t("ai_assistant.ariaLabel", "Open AI Co-Pilot")}</p>
				</TooltipContent>
			</Tooltip>
		</TooltipProvider>
	);
};

// --- Component 2: Chat Window ---
interface AiCopilotChatWindowProps {
	isOpen: boolean;
	onClose: () => void;
}
const AiCopilotChatWindow: React.FC<AiCopilotChatWindowProps> = ({
	isOpen,
	onClose,
}) => {
	const { t } = useTranslation(["navigation", "strategy-editor"]);
	const [input, setInput] = useState("");
	const [isAutopilotMode, setIsAutopilotMode] = useState(false);
	const [selectedImage, setSelectedImage] = useState<SelectedImage | null>(
		null,
	);
	const [isDraggingImage, setIsDraggingImage] = useState(false);
	const fileInputRef = useRef<HTMLInputElement>(null);
	const navigate = useNavigate();
	const location = useLocation();
	const { runId } = useParams<{ runId?: string }>();

	const attachImageFile = useCallback(
		async (file: File) => {
			try {
				if (file.size > 4 * 1024 * 1024) {
					alert(
						t(
							"ai_assistant.errorImageTooLarge",
							"Image is too large. Max size is 4MB.",
						),
					);
					return;
				}
				setSelectedImage(await processImageFile(file));
			} catch (error) {
				const message =
					error instanceof Error ? error.message : "Could not process image.";
				alert(t("ai_assistant.errorImageInvalid", message));
			}
		},
		[t],
	);

	const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
		const file = e.target.files?.[0];
		if (file) {
			// Validate file size (e.g., 4MB limit)
			if (file.size > 4 * 1024 * 1024) {
				alert(
					t(
						"ai_assistant.errorImageTooLarge",
						"Image is too large. Max size is 4MB.",
					),
				);
				return;
			}

			void attachImageFile(file);
		}
		// Reset input so the same file can be selected again
		e.target.value = "";
	};

	const removeSelectedImage = () => {
		setSelectedImage(null);
	};

	const handlePaste = (e: React.ClipboardEvent) => {
		if (isTyping) return;
		const imageFile = Array.from(e.clipboardData.files).find((file) =>
			file.type.startsWith("image/"),
		);
		if (imageFile) {
			e.preventDefault();
			void attachImageFile(imageFile);
		}
	};

	const handleDrop = (e: React.DragEvent) => {
		e.preventDefault();
		setIsDraggingImage(false);
		if (isTyping) return;
		const imageFile = Array.from(e.dataTransfer.files).find((file) =>
			file.type.startsWith("image/"),
		);
		if (imageFile) {
			void attachImageFile(imageFile);
		}
	};

	const {
		messages,
		addMessage,
		sessionId,
		isTyping,
		setIsTyping,
		clearChat,
		setSessionId,
	} = useAiCopilotStore();

	const { mutate: postMessage } = usePostChatMessage();

	const chatContainerRef = useRef<HTMLDivElement>(null);
	const [width, setWidth] = useState(540);
	const isResizing = useRef(false);

	const initialMessage = t("ai_assistant.initialMessage");

	const handleMouseDown = (e: React.MouseEvent) => {
		e.preventDefault();
		isResizing.current = true;
		document.addEventListener("mousemove", handleMouseMove);
		document.addEventListener("mouseup", handleMouseUp);
	};

	const handleMouseMove = (e: MouseEvent) => {
		if (!isResizing.current) return;
		const newWidth = window.innerWidth - e.clientX;
		if (newWidth > 400 && newWidth < window.innerWidth * 0.8) {
			setWidth(newWidth);
		}
	};

	const handleMouseUp = () => {
		isResizing.current = false;
		document.removeEventListener("mousemove", handleMouseMove);
		document.removeEventListener("mouseup", handleMouseUp);
	};

	const handleGenerateStrategy = () => {
		if (!sessionId || isTyping) return;

		const prompt = t("ai_assistant.generateStrategyAction");
		addMessage({ role: "user", content: prompt });
		setIsTyping(true);

		const payload: AIChatRequest = {
			text_prompt: prompt,
			session_id: sessionId,
			mode: "generator",
		};

		// Add context: backtest_id if we're on backtest page
		if (runId) payload.backtest_id = runId;

		// Add context: current strategy if we're in editor
		if (location.pathname.includes("/editor")) {
			const currentStrategy = useStrategyEditorStore.getState().toJson();
			if (currentStrategy) {
				payload.strategy_json = currentStrategy as unknown as Record<
					string,
					unknown
				>;
			}
		}

		postMessage(payload, {
			onSuccess: (data) => {
				if (data.session_id && data.session_id !== sessionId) {
					setSessionId(data.session_id);
				}

				const assistantMessage: Message = {
					role: "assistant",
					content: data.strategy_json
						? null
						: "Configuration generated successfully.",
					strategy_json: data.strategy_json,
				};
				addMessage(assistantMessage);
			},
			onError: (error) => {
				addMessage({ role: "assistant", content: `Error: ${error.message}` });
			},
			onSettled: () => {
				setIsTyping(false);
			},
		});
	};

	const { analyticsContext, setAnalyticsContext } = useAiCopilotStore();

	useEffect(() => {
		if (analyticsContext && sessionId && !isTyping && isOpen) {
			const hasStrategy = !!analyticsContext.strategy_json;
			const initialPrompt = hasStrategy
				? t("ai_assistant.analystPromptStrategy")
				: t("ai_assistant.analystPromptOverall");

			addMessage({ role: "user", content: initialPrompt });
			setIsTyping(true);

			const payload: AIChatRequest = {
				text_prompt: initialPrompt,
				session_id: sessionId,
				mode: "advisor", // Fallback to advisor since we appended instructions
				analytics_context: analyticsContext,
			};

			setAnalyticsContext(null);

			postMessage(payload, {
				onSuccess: (data) => {
					if (data.session_id && data.session_id !== sessionId) {
						setSessionId(data.session_id);
					}

					const assistantMessage: Message = {
						role: "assistant",
						content: data.strategy_json ? null : data.text_response,
						strategy_json: data.strategy_json,
					};
					addMessage(assistantMessage);
				},
				onError: (error) => {
					addMessage({ role: "assistant", content: `Error: ${error.message}` });
				},
				onSettled: () => {
					setIsTyping(false);
				},
			});
		}
	}, [
		analyticsContext,
		sessionId,
		isTyping,
		isOpen,
		addMessage,
		setIsTyping,
		postMessage,
		setSessionId,
		setAnalyticsContext,
		t,
	]);

	const handleSend = () => {
		if ((!input.trim() && !selectedImage) || !sessionId) return;

		const userMessage: Message = {
			role: "user",
			content: input,
			image_base64: selectedImage?.base64 || undefined,
			image_mime_type: selectedImage?.type || undefined,
		};
		addMessage(userMessage);
		setInput("");
		const currentImage = selectedImage;
		setSelectedImage(null); // Clear image after sending
		setIsTyping(true);

		const payload: AIChatRequest = {
			text_prompt: input || (currentImage ? "Analyze this image" : ""),
			session_id: sessionId,
			mode: "advisor",
			image_base64: currentImage?.base64 || undefined,
			image_mime_type: currentImage?.type || undefined,
		};

		if (runId) payload.backtest_id = runId;
		if (location.pathname.includes("/editor")) {
			const currentStrategy = useStrategyEditorStore.getState().toJson();
			if (currentStrategy) {
				payload.strategy_json = currentStrategy as unknown as Record<
					string,
					unknown
				>;
			}
		}

		postMessage(payload, {
			onSuccess: (data) => {
				if (data.session_id && data.session_id !== sessionId) {
					setSessionId(data.session_id);
					console.log(
						"AiCopilotChatWindow: Updated sessionId from AI response:",
						data.session_id,
					);
				}

				const assistantMessage: Message = {
					role: "assistant",
					content: data.strategy_json ? null : data.text_response,
					strategy_json: data.strategy_json,
				};
				addMessage(assistantMessage);
			},
			onError: (error) => {
				addMessage({ role: "assistant", content: `Error: ${error.message}` });
			},
			onSettled: () => {
				setIsTyping(false);
			},
		});
	};

	const handleClear = async () => {
		// clearChat now handles deletion from server internally
		await clearChat(initialMessage);
	};

	const handleLoadStrategy = (
		strategyJson: any,
	) => {
		if (!strategyJson) return;
		const finalConfig = strategyJson.config_data || strategyJson;
		useStrategyEditorStore.getState().loadStrategy(finalConfig);
		navigate("/editor");
		onClose();
	};

	useEffect(() => {
		if (chatContainerRef.current) {
			chatContainerRef.current.scrollTop =
				chatContainerRef.current.scrollHeight;
		}
	}, []);

	return (
		<Sheet open={isOpen} onOpenChange={(open) => !open && onClose()}>
			<SheetContent
				style={{ width: `${width}px` }}
				className={cn(
					"flex flex-col p-0 border-l !max-w-none",
					isDraggingImage && "ring-2 ring-primary ring-inset",
				)}
				onPaste={handlePaste}
				onDragOver={(e) => {
					if (
						Array.from(e.dataTransfer.items).some(
							(item) =>
								item.kind === "file" &&
								(!item.type || item.type.startsWith("image/")),
						)
					) {
						e.preventDefault();
						setIsDraggingImage(true);
					}
				}}
				onDragLeave={(e) => {
					if (!e.currentTarget.contains(e.relatedTarget as Node | null)) {
						setIsDraggingImage(false);
					}
				}}
				onDrop={handleDrop}
			>
				<style>{`[data-radix-dialog-content] > button[aria-label="Close"] { display: none; }`}</style>
				<div
					onMouseDown={handleMouseDown}
					className="absolute top-0 left-0 h-full w-2 cursor-ew-resize"
					title={t("ai_assistant.resizeHandleTitle")}
				/>
				<SheetHeader className="p-4 border-b shrink-0 pl-6">
					<div className="flex justify-between items-center mr-6">
						<SheetTitle className="flex items-center">
							<WandSparkles className="mr-2 animate-pulse text-indigo-400" />
							{t("ai_assistant.title")}
						</SheetTitle>
						<Button
							variant={isAutopilotMode ? "default" : "secondary"}
							size="sm"
							onClick={() => {
								const nextMode = !isAutopilotMode;
								setIsAutopilotMode(nextMode);
								if (nextMode) {
									setWidth(Math.max(540, Math.round(window.innerWidth / 2)));
								} else {
									setWidth(540);
								}
							}}
							className={cn(
								"rounded-full text-xs font-bold flex items-center gap-1.5 transition-all duration-300",
								isAutopilotMode && "bg-indigo-600 hover:bg-indigo-500 text-white shadow-indigo-500/20 shadow-lg"
							)}
						>
							🚀 Autopilot (Pro)
						</Button>
						<SheetDescription className="sr-only">
							{t("ai_assistant.srDescription")}
						</SheetDescription>
					</div>
				</SheetHeader>
				{isAutopilotMode ? (
					<div className="flex-1 overflow-hidden p-4 bg-background">
						<AgentWorkspace onStrategyGenerated={handleLoadStrategy} />
					</div>
				) : (
					<>
						<div
							ref={chatContainerRef}
							className="flex-1 overflow-y-auto p-4 space-y-6"
						>
							{messages.map((msg, index) => {
								const hasGenerationTrigger =
									typeof msg.content === "string" &&
									containsGenerationTrigger(msg.content);

								// Check if content is a strategy JSON
								let strategyJson = msg.strategy_json;
								let isStrategyContent = false;
								if (
									!strategyJson &&
									msg.role === "assistant" &&
									typeof msg.content === "string" &&
									msg.content.trim().startsWith("{")
								) {
									try {
										const parsed = JSON.parse(msg.content);
										if (parsed.name || parsed.symbol || parsed.entryConditions) {
											strategyJson = parsed;
											isStrategyContent = true;
										}
									} catch {
										/* empty */
									}
								}

								const hasStrategyJson =
									(msg.role === "assistant" && msg.strategy_json) ||
									isStrategyContent;

								return (
									<div key={index}>
										{/* Don't show content if it's a strategy JSON response */}
										{!hasStrategyJson && (
											<div
												className={cn(
													"flex items-start gap-3",
													msg.role === "user" ? "justify-end" : "justify-start",
												)}
											>
												{msg.role === "assistant" && (
													<div className="w-8 h-8 rounded-full bg-primary flex items-center justify-center flex-shrink-0 text-primary-foreground font-bold text-sm translate-y-px">
														DS
													</div>
												)}
												<div
													className={cn(
														"rounded-lg px-4 py-2 max-w-[90%]",
														msg.role === "user"
															? "bg-primary text-primary-foreground"
															: "bg-muted",
													)}
												>
													{msg.image_base64 && (
														<div className="mb-2 overflow-hidden rounded-md border border-border/50 bg-background/50">
															<button
																type="button"
																aria-label={t(
																	"ai_assistant.openImage",
																	"Open image",
																)}
																className="w-full h-full p-0 border-none bg-transparent cursor-zoom-in block"
																onClick={() =>
																	window.open(
																		getImageSrc(
																			msg.image_base64,
																			msg.image_mime_type,
																		),
																		"_blank",
																	)
																}
															>
																<img
																	src={getImageSrc(
																		msg.image_base64,
																		msg.image_mime_type,
																	)}
																	alt="Uploaded chart"
																	className="max-h-60 w-full object-contain"
																/>
															</button>
														</div>
													)}
													<div className="prose prose-sm dark:prose-invert prose-p:my-0 prose-headings:my-2">
														<Markdown remarkPlugins={[remarkGfm]}>
															{typeof msg.content === "string" ? msg.content : ""}
														</Markdown>
													</div>
												</div>
											</div>
										)}

										{/* Show generation button if trigger phrase is present */}
										{hasGenerationTrigger && (
											<div className="mt-2 flex justify-start">
												<Button onClick={handleGenerateStrategy}>
													<WandSparkles className="w-4 h-4 mr-2" />
													{t("ai_assistant.generateStrategyAction")}
												</Button>
											</div>
										)}

										{/* Show 'Open in Editor' button instead of JSON */}
										{hasStrategyJson && (
											<div className="flex justify-start">
												<div className="rounded-lg px-4 py-2 bg-muted">
													<p className="text-sm mb-2">
														{t(
															"ai_assistant.strategyGenerated",
															"Strategy configuration generated successfully!",
												)	}
													</p>
													<Button onClick={() => handleLoadStrategy(strategyJson)}>
														<Rocket className="w-4 h-4 mr-2" />
														{t("ai_assistant.openInEditor")}
													</Button>
												</div>
											</div>
										)}
									</div>
								);
							})}
							{isTyping && (
								<div className="flex items-start gap-3">
									<div className="w-8 h-8 rounded-full bg-primary flex items-center justify-center flex-shrink-0 text-primary-foreground font-bold text-sm translate-y-px">
										DS
									</div>
									<div className="rounded-lg px-4 py-2 bg-muted flex items-center space-x-2">
										<Loader2 className="h-5 w-5 animate-spin" />
										<span>{t("ai_assistant.analyzing")}</span>
									</div>
								</div>
							)}
						</div>
						<div className="p-4 border-t flex flex-col space-y-2 shrink-0 bg-background">
							{selectedImage && (
								<div className="flex items-center gap-2 mb-2 p-2 bg-muted/50 rounded-md relative group max-w-fit">
									<img
										src={getImageSrc(selectedImage.base64, selectedImage.type)}
										className="h-16 w-24 object-cover rounded border border-border shadow-sm"
										alt="Preview"
									/>
									<Button
										variant="destructive"
										size="icon"
										className="absolute -top-2 -right-2 h-5 w-5 rounded-full shadow-md"
										onClick={removeSelectedImage}
									>
										<X className="h-3 w-3" />
									</Button>
								</div>
							)}
							<p className="text-[10px] text-muted-foreground/60 text-center leading-tight mb-1 px-2">
								{t("ai.disclaimer", { ns: "strategy-editor" })}
							</p>
							<div className="flex w-full items-center space-x-2">
								<input
									type="file"
									accept="image/*"
									className="hidden"
									ref={fileInputRef}
									onChange={handleFileChange}
								/>
								<Button
									variant="ghost"
									size="icon"
									onClick={handleClear}
									title={t("ai_assistant.newChat")}
									disabled={isTyping}
								>
									<Trash2 className="h-4 w-4" />
								</Button>
								<Button
									variant="ghost"
									size="icon"
									onClick={() => fileInputRef.current?.click()}
									title={t("ai_assistant.uploadImage", "Upload chart screenshot")}
									disabled={isTyping}
								>
									<Paperclip className="h-4 w-4" />
								</Button>
								<Textarea
									value={input}
									onChange={(e) => setInput(e.target.value)}
									placeholder={t("ai_assistant.placeholder")}
									onKeyDown={(e) => {
										if (e.key === "Enter" && !e.shiftKey) {
											e.preventDefault();
											handleSend();
										}
									}}
									disabled={isTyping}
									rows={1}
								/>
								<Button
									onClick={() => handleSend()}
									disabled={isTyping || (!input.trim() && !selectedImage)}
								>
									<Send className="h-4" />
								</Button>
							</div>
						</div>
					</>
				)}
			</SheetContent>
		</Sheet>
	);
};

// --- Component 3: Main Widget ---
export const AiCopilotWidget: React.FC = () => {
	const { widgetState, setWidgetState, sessionId, loadInitialSession } =
		useAiCopilotStore();
	useGetChatHistory(sessionId);
	const { t } = useTranslation("navigation");
	const initialMessage = t("ai_assistant.initialMessage");

	useEffect(() => {
		console.log("AiCopilotWidget: Initializing session.");
		loadInitialSession(initialMessage);
	}, [loadInitialSession, initialMessage]);

	useEffect(() => {
		console.log("AiCopilotWidget: SessionId changed to:", sessionId);
		if (sessionId) {
			localStorage.setItem("ai-copilot-session-id", sessionId);
			console.log("AiCopilotWidget: SessionId saved to localStorage.");
		}
	}, [sessionId]);

	if (widgetState === "minimized") {
		return <AiCopilotLauncher onClick={() => setWidgetState("open")} />;
	}

	if (widgetState === "open") {
		return (
			<AiCopilotChatWindow
				isOpen={true}
				onClose={() => setWidgetState("minimized")}
			/>
		);
	}

	return null;
};
