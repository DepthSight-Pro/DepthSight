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
	const messagesEndRef = useRef<HTMLDivElement>(null);
	const { t } = useTranslation("pwa-common");
	const [isGenerating, setIsGenerating] = useState(false);

	useEffect(() => {
		messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
	}, []);

	const handleSendMessage = async () => {
		const userInput = inputRef.current?.value.trim();
		if (!userInput || isTyping || !sessionId) return;

		const newUserMessage: Message = {
			id: `user-${Date.now()}`,
			role: "user",
			content: userInput,
		};
		setMessages((prev) => [...prev, newUserMessage]);
		setIsTyping(true);
		if (inputRef.current) {
			inputRef.current.value = "";
		}

		const strategyConfig = useStrategyEditorStore.getState().toJson();

		try {
			const response = await api.aiChat({
				text_prompt: userInput,
				session_id: sessionId,
				backtest_id: backtestId,
				strategy_json: strategyConfig,
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

	const handleGenerateClick = (strategyJson: Partial<StrategyConfig>) => {
		if (strategyJson) {
			onStrategyGenerated(strategyJson);
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
		<div className="flex flex-col h-full bg-[hsl(var(--background))]">
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
				<div className="flex items-center gap-2">
					<button
						onClick={clearChat}
						className="p-3 rounded-full bg-[hsl(var(--secondary))] text-[hsl(var(--muted-foreground))] transition hover:bg-[hsl(var(--accent))]"
					>
						<ICONS.Trash className="w-5 h-5" />
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
		</div>
	);
};

export default AIChatScreen;
