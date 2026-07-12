// pwa/screens/AIChatScreen.tsx

import type React from "react";
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Logo } from "../components/ui/logo";
import { ICONS } from "../constants";
import { useAIChat } from "../contexts/AIChatContext";
import { api } from "../services/api";
import { useStrategyEditorStore } from "../stores/strategyEditorStore";
import type { Message, StrategyConfig } from "../types";
import { Paperclip, X } from "lucide-react";
import { AgentWorkspace } from "../components/agent/AgentWorkspace";

const MAX_IMAGE_DIMENSION = 1000;
const ALLOWED_IMAGE_TYPES = new Set(["image/jpeg", "image/png", "image/webp"]);

const getImageSrc = (base64: string, mimeType = "image/jpeg") =>
	base64.startsWith("data:") ? base64 : `data:${mimeType};base64,${base64}`;

const processImageFile = (file: File): Promise<{ base64: string; type: string }> => {
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

const GENERATION_TRIGGER_PHRASES = [
	"Would you like me to prepare an updated strategy configuration?",
	"Please click the button",
	"Generate in Editor",
];

const containsGenerationTrigger = (text: string): boolean => {
	return GENERATION_TRIGGER_PHRASES.some((phrase) => text.includes(phrase));
};

interface AIChatScreenProps {
	onStrategyGenerated: (strategyJson: Partial<StrategyConfig>) => void;
}

const AIChatScreen: React.FC<AIChatScreenProps> = ({ onStrategyGenerated }) => {
	const {
		messages,
		sessionId,
		backtestId,
		isLoading,
		isTyping,
		setMessages,
		setIsTyping,
		clearChat,
	} = useAIChat();
	const inputRef = useRef<HTMLInputElement>(null);
	const fileInputRef = useRef<HTMLInputElement>(null);
	const messagesEndRef = useRef<HTMLDivElement>(null);
	const { t } = useTranslation("pwa-common");
	const [isGenerating, setIsGenerating] = useState(false);
	const [selectedImage, setSelectedImage] = useState<{ base64: string; type: string } | null>(null);
	const [isAutopilotMode, setIsAutopilotMode] = useState(false);

	useEffect(() => {
		messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
	}, []);

	const attachImageFile = async (file: File) => {
		try {
			if (file.size > 4 * 1024 * 1024) {
				alert(t("aiChat.errorImageTooLarge", "Image is too large. Max size is 4MB."));
				return;
			}
			setSelectedImage(await processImageFile(file));
		} catch (error) {
			const message = error instanceof Error ? error.message : "Could not process image.";
			alert(t("aiChat.errorImageInvalid", message));
		}
	};

	const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
		const file = e.target.files?.[0];
		if (file) {
			void attachImageFile(file);
		}
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

	const handleSendMessage = async () => {
		const userInput = inputRef.current?.value.trim();
		if ((!userInput && !selectedImage) || isTyping || !sessionId) return;

		const newUserMessage: Message = {
			id: `user-${Date.now()}`,
			role: "user",
			content: userInput || "",
			image_base64: selectedImage?.base64 || undefined,
			image_mime_type: selectedImage?.type || undefined,
		};
		setMessages((prev) => [...prev, newUserMessage]);
		setIsTyping(true);
		if (inputRef.current) {
			inputRef.current.value = "";
		}
		const currentImage = selectedImage;
		setSelectedImage(null);

		const strategyConfig = useStrategyEditorStore.getState().toJson();

		try {
			const response = await api.aiChat({
				text_prompt: userInput || (currentImage ? "Analyze this image" : ""),
				session_id: sessionId,
				backtest_id: backtestId,
				strategy_json: strategyConfig,
				image_base64: currentImage?.base64 || undefined,
				image_mime_type: currentImage?.type || undefined,
			});

			const aiResponseMessage: Message = {
				id: `ai-${Date.now()}`,
				role: "ai",
				content: response.text_response,
				strategy_json: response.strategy_json,
			};
			setMessages((prev) => [...prev, aiResponseMessage]);
		} catch {
			const errorMessage: Message = {
				id: `err-${Date.now()}`,
				role: "ai",
				content: t("aiChat.errorMessage"),
			};
			setMessages((prev) => [...prev, errorMessage]);
		} finally {
			setIsTyping(false);
		}
	};

	const handleGenerateClick = (strategyJson: any) => {
		if (strategyJson) {
			onStrategyGenerated(strategyJson.config_data || strategyJson);
		}
	};

	const handleGenerateStrategy = async () => {
		if (!sessionId || isTyping || isGenerating) return;

		const userMessage: Message = {
			id: `user-${Date.now()}`,
			role: "user",
			content: t("aiChat.generateStrategy"),
		};
		setMessages((prev) => [...prev, userMessage]);
		setIsTyping(true);
		setIsGenerating(true);

		const strategyConfig = useStrategyEditorStore.getState().toJson();

		try {
			const response = await api.aiChat({
				text_prompt: t("aiChat.generateStrategy"),
				session_id: sessionId,
				backtest_id: backtestId,
				strategy_json: strategyConfig,
				mode: "generator",
			});

			const aiResponseMessage: Message = {
				id: `ai-${Date.now()}`,
				role: "ai",
				content: response.strategy_json ? null : t("aiChat.strategyGenerated"),
				strategy_json: response.strategy_json,
			};
			setMessages((prev) => [...prev, aiResponseMessage]);
		} catch {
			const errorMessage: Message = {
				id: `err-${Date.now()}`,
				role: "ai",
				content: t("aiChat.errorMessage"),
			};
			setMessages((prev) => [...prev, errorMessage]);
		} finally {
			setIsTyping(false);
			setIsGenerating(false);
		}
	};

	return (
		<div className="flex flex-col h-full bg-[hsl(var(--background))]" onPaste={handlePaste}>
			{/* Top Toggle Bar */}
			<div className="flex items-center justify-between px-4 py-2.5 bg-[hsl(var(--card))] border-b border-[hsl(var(--border))] shrink-0">
				<div className="flex items-center gap-2">
					<Logo size="sm" />
					<span className="font-semibold text-sm text-[hsl(var(--foreground))]">DepthSight Co-Pilot</span>
				</div>
				<div className="flex items-center gap-2">
					<button
						onClick={() => setIsAutopilotMode(!isAutopilotMode)}
						className={`px-3.5 py-1.5 rounded-full text-xs font-bold flex items-center gap-1.5 transition-all duration-300 ${
							isAutopilotMode
								? "bg-indigo-600 hover:bg-indigo-500 text-white shadow-indigo-500/20 shadow-lg"
								: "bg-[hsl(var(--secondary))] text-[hsl(var(--muted-foreground))] hover:text-[hsl(var(--foreground))]"
						}`}
						type="button"
					>
						🚀 Autopilot (Pro)
					</button>
				</div>
			</div>

			{isAutopilotMode ? (
				<div className="flex-1 overflow-hidden p-3 bg-[hsl(var(--background))]">
					<AgentWorkspace onStrategyGenerated={onStrategyGenerated} />
				</div>
			) : (
				<>
					<div className="flex-1 overflow-y-auto p-4 space-y-4">
						{isLoading && (
							<div className="flex justify-center items-center h-full">
								<Logo size="lg" className="mb-8 animate-pulse" />
							</div>
						)}
						{!isLoading &&
							messages.map((msg) => {
								const hasGenerationTrigger =
									msg.role === "ai" &&
									typeof msg.content === "string" &&
									containsGenerationTrigger(msg.content);
								const hasStrategyJson = msg.role === "ai" && msg.strategy_json;

								return (
									<div key={msg.id}>
										{/* Message bubble - don't show content if it's a strategy JSON response */}
										{!hasStrategyJson && (
											<div
												className={`flex gap-3 items-start ${msg.role === "user" ? "justify-end" : ""}`}
											>
												{msg.role === "ai" && (
													<div className="w-8 h-8 rounded-full bg-[hsl(var(--primary))] flex items-center justify-center flex-shrink-0 text-white font-bold text-sm">
														DS
													</div>
												)}
												<div
													className={`max-w-[80%] p-3 rounded-2xl shadow-sm ${msg.role === "user" ? "bg-[hsl(var(--primary))] text-white rounded-br-lg" : "bg-[hsl(var(--secondary))] text-[hsl(var(--card-foreground))] rounded-bl-lg"}`}
												>
													{msg.image_base64 && (
														<div className="mb-2 overflow-hidden rounded-md border border-border/50 bg-background/50">
															<button
																type="button"
																aria-label={t(
																	"aiChat.openImage",
																	"Open image",
																)}
																className="w-full h-full p-0 border-none bg-transparent cursor-zoom-in block"
																onClick={() =>
																	window.open(
																		getImageSrc(
																			msg.image_base64!,
																			msg.image_mime_type,
																		),
																		"_blank",
																	)
																}
															>
																<img
																	src={getImageSrc(
																		msg.image_base64!,
																		msg.image_mime_type,
																	)}
																	alt="Uploaded chart"
																	className="max-h-60 w-full object-contain"
																/>
															</button>
														</div>
													)}
													<div className="prose prose-sm dark:prose-invert">
														<ReactMarkdown remarkPlugins={[remarkGfm]}>
															{typeof msg.content === "string" ? msg.content : ""}
														</ReactMarkdown>
													</div>
												</div>
											</div>
										)}

										{/* Show generation button if trigger phrase is present */}
										{hasGenerationTrigger && (
											<div className="mt-2 flex justify-start pl-11">
												<button
													onClick={handleGenerateStrategy}
													disabled={isGenerating || isTyping}
													className="bg-[hsl(var(--primary))] text-white text-xs font-bold py-2 px-4 rounded-lg hover:bg-[hsl(var(--primary))]/90 transition disabled:opacity-50"
												>
													{t("aiChat.generateStrategy")}
												</button>
											</div>
										)}

										{/* Show 'Load to Editor' button for generated strategies */}
										{hasStrategyJson && (
											<div className="flex gap-3 items-start">
												<div className="w-8 h-8 rounded-full bg-[hsl(var(--primary))] flex items-center justify-center flex-shrink-0 text-white font-bold text-sm">
													DS
												</div>
												<div className="max-w-[80%] p-3 rounded-2xl shadow-sm bg-[hsl(var(--secondary))] text-[hsl(var(--card-foreground))] rounded-bl-lg">
													<p className="text-sm mb-2">
														{t("aiChat.strategyGenerated")}
													</p>
													<button
														onClick={() => handleGenerateClick(msg.strategy_json)}
														className="w-full bg-green-600 text-white text-xs font-bold py-2 px-3 rounded-lg hover:bg-green-700 transition"
													>
														{t("aiChat.loadToEditor")}
													</button>
												</div>
											</div>
										)}
									</div>
								);
							})}
						{isTyping && (
							<div className="flex gap-3 items-start">
								<div className="w-8 h-8 rounded-full bg-[hsl(var(--primary))] flex items-center justify-center flex-shrink-0 text-white font-bold text-sm translate-y-0.5">
									DS
								</div>
								<div className="max-w-[80%] p-3 rounded-2xl bg-[hsl(var(--secondary))] rounded-bl-lg flex items-center gap-1">
									<span className="w-2 h-2 bg-gray-400 rounded-full animate-bounce"></span>
									<span className="w-2 h-2 bg-gray-400 rounded-full animate-bounce [animation-delay:0.2s]"></span>
									<span className="w-2 h-2 bg-gray-400 rounded-full animate-bounce [animation-delay:0.4s]"></span>
								</div>
							</div>
						)}
						<div ref={messagesEndRef} />
					</div>
					<div className="p-4 bg-[hsl(var(--background))] border-t border-[hsl(var(--border))]">
						{selectedImage && (
							<div className="flex items-center gap-2 mb-2 p-2 bg-[hsl(var(--secondary))/0.5] rounded-xl relative group max-w-fit">
								<img
									src={getImageSrc(selectedImage.base64, selectedImage.type)}
									className="h-16 w-24 object-cover rounded-lg border border-[hsl(var(--border))] shadow-sm"
									alt="Preview"
								/>
								<button
									onClick={removeSelectedImage}
									className="absolute -top-2 -right-2 h-5 w-5 rounded-full bg-[hsl(var(--destructive))] text-[hsl(var(--destructive-foreground))] flex items-center justify-center shadow-md transition hover:opacity-90 border-none"
								>
									<X className="w-3 h-3" />
								</button>
							</div>
						)}
						<div className="flex items-center gap-2">
							<input
								type="file"
								accept="image/*"
								className="hidden"
								ref={fileInputRef}
								onChange={handleFileChange}
							/>
							<button
								onClick={clearChat}
								className="p-3 rounded-full bg-[hsl(var(--secondary))] text-[hsl(var(--muted-foreground))] transition hover:bg-[hsl(var(--accent))]"
							>
								<ICONS.Trash className="w-5 h-5" />
							</button>
							<button
								onClick={() => fileInputRef.current?.click()}
								disabled={isTyping}
								className="p-3 rounded-full bg-[hsl(var(--secondary))] text-[hsl(var(--muted-foreground))] transition hover:bg-[hsl(var(--accent))] disabled:opacity-50"
							>
								<Paperclip className="w-5 h-5" />
							</button>
							<input
								ref={inputRef}
								type="text"
								className="flex-1 p-3 bg-[hsl(var(--secondary))] border border-[hsl(var(--border))] rounded-full text-sm text-[hsl(var(--foreground))] outline-none focus:border-[hsl(var(--primary))]"
								placeholder={t("aiChat.askPlaceholder")}
								onKeyDown={(e) => e.key === "Enter" && handleSendMessage()}
								disabled={isTyping || isLoading}
							/>
							<button
								onClick={handleSendMessage}
								disabled={isTyping || isLoading}
								className="p-3 rounded-full bg-[hsl(var(--primary))] text-white disabled:opacity-50 transition"
							>
								<ICONS.Send className="w-5 h-5" />
							</button>
						</div>
					</div>
				</>
			)}
		</div>
	);
};

export default AIChatScreen;
