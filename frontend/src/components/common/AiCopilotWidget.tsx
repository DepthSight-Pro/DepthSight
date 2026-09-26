// frontend/src/components/common/AiCopilotWidget.tsx

import {
	Blocks,
	Bot,
	Loader2,
	MessageSquareText,
	Paperclip,
	Rocket,
	Send,
	Trash2,
	WandSparkles,
	X,
} from "lucide-react";
import type React from "react";
import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import Markdown from "react-markdown";
import { useLocation, useNavigate, useParams } from "react-router-dom";
import remarkGfm from "remark-gfm";
import { Button } from "@/components/ui/button";
import { Segmented } from "@/components/ui/quant-ui";
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

// --- Chat Window ---
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
	const [activeView, setActiveView] = useState<"chat" | "agent">("chat");
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
	// True while the user stays near the bottom — new messages then auto-scroll.
	// Opening the window always resets it so a long chat starts at the last message.
	const stickToBottomRef = useRef(true);

	const scrollChatToBottom = useCallback(() => {
		const el = chatContainerRef.current;
		if (el) el.scrollTop = el.scrollHeight;
	}, []);

	const handleChatScroll = useCallback(() => {
		const el = chatContainerRef.current;
		if (!el) return;
		stickToBottomRef.current =
			el.scrollHeight - el.scrollTop - el.clientHeight < 120;
	}, []);

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

	const switchView = (view: "chat" | "agent") => {
		setActiveView(view);
		if (view === "agent") {
			// Agent workspace needs more room; on mobile just use full width
			setWidth(
				window.innerWidth < 640
					? window.innerWidth
					: Math.max(540, Math.round(window.innerWidth / 2)),
			);
		} else {
			setWidth(540);
		}
	};

	const openMcpSettings = () => {
		onClose();
		navigate("/settings?tab=mcp");
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
		strategyJson: Record<string, unknown> | null | undefined,
	) => {
		if (!strategyJson) return;
		const finalConfig = strategyJson.config_data || strategyJson;
		useStrategyEditorStore.getState().loadStrategy(finalConfig);
		navigate("/editor");
		onClose();
	};

	useLayoutEffect(() => {
		// Window (re)mounted = opened: always start at the latest message.
		stickToBottomRef.current = true;
		scrollChatToBottom();
	}, [scrollChatToBottom]);

	useLayoutEffect(() => {
		// Follow new messages / typing indicator, unless the user scrolled up.
		// Also runs when switching back to the chat tab (freshly mounted list).
		if (activeView === "chat" && stickToBottomRef.current)
			scrollChatToBottom();
	}, [messages, isTyping, activeView, scrollChatToBottom]);

	// Close with Escape (no modal overlay anymore, the site header stays usable).
	useEffect(() => {
		const handleKeyDown = (e: KeyboardEvent) => {
			if (e.key === "Escape") onClose();
		};
		window.addEventListener("keydown", handleKeyDown);
		return () => window.removeEventListener("keydown", handleKeyDown);
	}, [onClose]);

	return (
		// Docked panel (non-modal): sits below the site header so it never covers
		// it, and the header Co-Pilot toggle stays clickable to close it.
		<div
			role="complementary"
			aria-label={t("ai_assistant.title")}
			style={{ width: `min(${width}px, 100vw)`, maxWidth: "100vw" }}
			className={cn(
				"fixed right-0 top-12 bottom-0 sm:top-14 z-50 flex flex-col gap-0 border-l border-t border-border/70 dark:border-white/10 bg-card/95 dark:bg-[#0b0e14]/90 backdrop-blur-2xl shadow-2xl rounded-tl-2xl animate-in fade-in-0 slide-in-from-right duration-300",
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
				<div
					onMouseDown={handleMouseDown}
					className="absolute top-0 left-0 h-full w-2 cursor-ew-resize hidden sm:block"
					title={t("ai_assistant.resizeHandleTitle")}
				/>
				<div className="px-3 sm:px-4 py-2.5 border-b border-border/50 dark:border-white/5 shrink-0">
					<div className="flex items-center gap-1.5 sm:gap-2">
						<span className="sr-only">{t("ai_assistant.title")}</span>
						<Segmented<"chat" | "agent">
							size="xs"
							value={activeView}
							onChange={switchView}
							options={[
								{
									value: "chat",
									label: t("ai_assistant.chatTab", "Chat"),
									icon: <MessageSquareText size={12} />,
								},
								{
									value: "agent",
									label: t("ai_assistant.agentTab", "Agent"),
									icon: <Bot size={12} />,
								},
							]}
						/>
						<div className="flex-1" />
						<button
							type="button"
							onClick={openMcpSettings}
							title={t("ai_assistant.mcpSettings", "MCP settings")}
							className="flex h-7 items-center gap-1.5 rounded-lg border border-border/60 dark:border-white/10 bg-black/[0.03] dark:bg-white/[0.04] px-2 text-[11px] font-medium text-muted-foreground dark:text-white/60 transition-all hover:border-cyan/40 hover:text-cyan"
						>
							<Blocks size={13} />
							<span className="hidden sm:inline">
								{t("ai_assistant.mcpSettings", "MCP settings")}
							</span>
						</button>
						<button
							type="button"
							onClick={onClose}
							aria-label="Close"
							className="flex h-7 w-7 items-center justify-center rounded-lg text-muted-foreground dark:text-white/40 transition-colors hover:bg-black/5 dark:hover:bg-white/5 hover:text-foreground dark:hover:text-white"
						>
							<X size={15} />
						</button>
					</div>
				</div>
				{activeView === "agent" ? (
					<div className="flex-1 min-h-0 overflow-y-auto p-3 sm:p-4">
						<AgentWorkspace onStrategyGenerated={handleLoadStrategy} />
					</div>
				) : (
					<>
						<div
							ref={chatContainerRef}
							onScroll={handleChatScroll}
							className="flex-1 min-h-0 overflow-y-auto p-3 sm:p-4 space-y-5"
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
														"rounded-lg px-4 py-2 max-w-[90%] border",
														msg.role === "user"
															? "bg-primary text-primary-foreground border-transparent"
															: "bg-black/[0.03] dark:bg-white/[0.04] border-border/60 dark:border-white/5 text-foreground",
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
																			msg.image_base64 ?? "",
																			msg.image_mime_type ?? "image/jpeg",
																		),
																		"_blank",
																	)
																}
															>
																<img
																	src={getImageSrc(
																		msg.image_base64 ?? "",
																		msg.image_mime_type ?? "image/jpeg",
																	)}
																	alt="Uploaded chart"
																	className="max-h-60 w-full object-contain"
																	onLoad={() => {
																		if (stickToBottomRef.current)
																			scrollChatToBottom();
																	}}
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
												<div className="rounded-lg px-4 py-2 bg-black/[0.03] dark:bg-white/[0.04] border border-border/60 dark:border-white/5">
													<p className="text-sm mb-2 text-foreground">
														{t(
															"ai_assistant.strategyGenerated",
															"Strategy configuration generated successfully!",
														)}
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
									<div className="rounded-lg px-4 py-2 bg-black/[0.03] dark:bg-white/[0.04] border border-border/60 dark:border-white/5 flex items-center space-x-2 text-foreground">
										<Loader2 className="h-5 w-5 animate-spin text-cyan" />
										<span>{t("ai_assistant.analyzing")}</span>
									</div>
								</div>
							)}
						</div>
						{/* Bottom Chat Input Form */}
						<div className="p-3 sm:p-4 border-t border-border/50 dark:border-white/5 flex flex-col space-y-2 shrink-0">
							{/* Image Preview (attached above textarea) */}
							{selectedImage && (
								<div className="flex items-center gap-2 border border-border rounded-xl p-2 bg-muted/40 max-w-fit animate-in fade-in">
									<div className="relative group">
										<img
											src={getImageSrc(selectedImage.base64, selectedImage.type)}
											className="h-16 w-24 object-cover rounded-lg border border-border shadow-sm"
											alt="Chart preview"
										/>
										<button
											onClick={removeSelectedImage}
											className="absolute -top-1.5 -right-1.5 bg-destructive text-white rounded-full h-5 w-5 flex items-center justify-center shadow-md hover:bg-destructive/90 transition cursor-pointer"
											type="button"
											title="Remove image"
										>
											<X className="h-3 w-3" />
										</button>
									</div>
									<div className="text-xs text-muted-foreground pr-2">
										<p className="font-medium text-foreground">
											{t("ai_assistant.chartAttached", "Chart screenshot attached")}
										</p>
										<p className="text-[10px]">
											{t("ai_assistant.chartAttachedDesc", "Will be sent and analyzed with your message")}
										</p>
									</div>
								</div>
							)}

							{/* Classic Multi-line Chat Textarea */}
							<div className="relative rounded-2xl border border-border/70 dark:border-white/10 bg-black/[0.02] dark:bg-white/[0.03] focus-within:border-cyan/50 focus-within:ring-1 focus-within:ring-cyan/20 shadow-lg transition-all">
								<textarea
									id="copilot-prompt-input"
									value={input}
									onChange={(e) => setInput(e.target.value)}
									onKeyDown={(e) => {
										if (e.key === "Enter" && !e.shiftKey) {
											e.preventDefault();
											if (!isTyping && (input.trim() || selectedImage)) {
												handleSend();
											}
										}
									}}
									onPaste={handlePaste}
									disabled={isTyping}
									rows={2}
									placeholder={t(
										"ai_assistant.placeholderWithHint",
										"Message AI Co-Pilot (Enter to send, Shift+Enter for new line)...",
									)}
									className="w-full bg-transparent px-3.5 pt-3 pb-11 text-sm text-foreground placeholder:text-muted-foreground/60 focus:outline-none resize-none disabled:opacity-50 scrollbar-thin"
								/>

								<div className="absolute bottom-2 left-3 right-3 flex items-center justify-between pointer-events-none">
									<div className="flex items-center gap-1.5 pointer-events-auto">
										<input
											type="file"
											accept="image/*"
											className="hidden"
											ref={fileInputRef}
											onChange={handleFileChange}
										/>
										<button
											type="button"
											onClick={handleClear}
											disabled={isTyping}
											className="p-1.5 rounded-lg border border-white/10 bg-white/[0.03] text-muted-foreground hover:text-destructive hover:border-destructive/40 transition disabled:opacity-50 flex items-center gap-1 text-xs cursor-pointer"
											title={t("ai_assistant.newChat", "Start new chat")}
										>
											<Trash2 className="w-3.5 h-3.5" />
											<span className="text-[10px] hidden sm:inline">
												{t("ai_assistant.clear", "Clear")}
											</span>
										</button>
										<button
											type="button"
											onClick={() => fileInputRef.current?.click()}
											disabled={isTyping}
											className="p-1.5 rounded-lg border border-white/10 bg-white/[0.03] text-muted-foreground hover:text-foreground hover:border-cyan/40 transition disabled:opacity-50 flex items-center gap-1 text-xs cursor-pointer"
											title={t("ai_assistant.uploadImage", "Upload chart screenshot")}
										>
											<Paperclip className="w-3.5 h-3.5" />
											<span className="text-[10px] hidden sm:inline">
												{t("ai_assistant.attachChart", "Attach Chart")}
											</span>
										</button>
									</div>

									<div className="flex items-center gap-2 pointer-events-auto">
										<button
											type="button"
											onClick={() => handleSend()}
											disabled={isTyping || (!input.trim() && !selectedImage)}
											className="bg-primary hover:bg-primary/90 text-white rounded-xl px-4 py-1.5 flex items-center gap-1.5 text-xs font-semibold shadow-md shadow-primary/20 transition disabled:opacity-40 cursor-pointer"
										>
											{isTyping ? (
												<>
													<Loader2 className="w-3.5 h-3.5 animate-spin" />
													<span>{t("ai_assistant.analyzing", "Analyzing...")}</span>
												</>
											) : (
												<>
													<Send className="w-3.5 h-3.5" />
													<span>{t("ai_assistant.send", "Send")}</span>
												</>
											)}
										</button>
									</div>
								</div>
							</div>

						<p className="text-[10px] text-muted-foreground/60 text-center leading-tight mb-0.5 px-2">
							{t("ai.disclaimer", { ns: "strategy-editor" })}
						</p>
					</div>
				</>
			)}
		</div>
	);
};

// --- Main Widget ---
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
		return null;
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
