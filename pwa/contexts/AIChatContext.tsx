// pwa/contexts/AIChatContext.tsx

import type React from "react";
import {
	createContext,
	type ReactNode,
	useCallback,
	useContext,
	useEffect,
	useState,
} from "react";
import { useTranslation } from "react-i18next";
import { api } from "../services/api";
import type { AIChatMessage, Message } from "../types";

interface AIChatContextType {
	messages: Message[];
	sessionId: string | null;
	backtestId: string | null; // ID of the backtest to be analyzed
	isLoading: boolean;
	isTyping: boolean;
	sendMessage: (content: string) => Promise<void>;
	setMessages: React.Dispatch<React.SetStateAction<Message[]>>;
	setBacktestId: (id: string | null) => void;
	clearChat: () => Promise<void>;
	setIsTyping: React.Dispatch<React.SetStateAction<boolean>>;
	setSessionId: React.Dispatch<React.SetStateAction<string | null>>;
}

const AIChatContext = createContext<AIChatContextType | undefined>(undefined);

export const AIChatProvider = ({ children }: { children: ReactNode }) => {
	const { t } = useTranslation("pwa-common");
	const [messages, setMessages] = useState<Message[]>([]);
	const [sessionId, setSessionId] = useState<string | null>(null);
	const [backtestId, setBacktestId] = useState<string | null>(null);
	const [isLoading, setIsLoading] = useState<boolean>(false);
	const [isTyping, setIsTyping] = useState<boolean>(false);

	const getInitialGreeting = useCallback(
		(): Message => ({
			id: "initial-greeting",
			role: "ai",
			content: t("aiChat.initialGreeting"),
		}),
		[t],
	);

	const startNewSession = useCallback(async () => {
		console.log("AIChatContext: Starting new session.");
		const newSessionId = `session-${Date.now()}`;
		const initialGreeting = getInitialGreeting();
		setSessionId(newSessionId);
		setMessages([initialGreeting]);
		console.log(
			"AIChatContext: setMessages called in startNewSession. New messages count:",
			[initialGreeting].length,
		);
		setBacktestId(null); // Clear any active backtest analysis context
		localStorage.setItem("ai-copilot-session-id", newSessionId);
		console.log("AIChatContext: New session started and saved:", newSessionId);

		// Save initial greeting message to DB so this session is registered on server
		try {
			await api.initChatSession(
				newSessionId,
				initialGreeting.content as string,
			);
			console.log(
				"AIChatContext: Initial greeting saved to server for session:",
				newSessionId,
			);
		} catch (error) {
			console.error(
				"AIChatContext: Failed to save initial greeting to server:",
				error,
			);
			// Non-critical error, continue anyway
		}
	}, [getInitialGreeting]);

	const loadSession = useCallback(
		async (sid: string) => {
			console.log("AIChatContext: Attempting to load session:", sid);
			setIsLoading(true);
			try {
				const history: AIChatMessage[] = await api.getChatHistory(sid);
				console.log(
					"AIChatContext: Successfully loaded history for session:",
					sid,
					history,
				);

				if (history.length === 0) {
					// If history is empty, add initial greeting
					const initialGreeting = getInitialGreeting();
					setMessages([initialGreeting]);
					console.log(
						"AIChatContext: Session exists but history empty, setting initial message.",
					);
				} else {
					const messages: Message[] = history.map((msg) => {
						let strategyJson = msg.strategy_json;
						let content = msg.content;

						// If content looks like JSON and no strategy_json, try to parse it
						if (
							!strategyJson &&
							msg.role === "assistant" &&
							typeof msg.content === "string"
						) {
							try {
								const trimmed = msg.content.trim();
								if (trimmed.startsWith("{") && trimmed.endsWith("}")) {
									strategyJson = JSON.parse(trimmed);
									content = null; // Don't show JSON as text
								}
							} catch {
								// Not JSON, keep as regular content
							}
						}

						return {
							id: msg.id,
							role: msg.role === "assistant" ? "ai" : "user",
							content: content,
							strategy_json: strategyJson,
						};
					});
					setMessages(messages);
					console.log(
						"AIChatContext: setMessages called in loadSession. New messages count:",
						messages.length,
					);
				}

				setSessionId(sid);
				localStorage.setItem("ai-copilot-session-id", sid); // Ensure it's saved if loaded successfully
			} catch (error) {
				console.error("AIChatContext: Failed to load chat session:", error);
				// If loading fails, start a new session as a fallback
				await startNewSession();
			} finally {
				setIsLoading(false);
			}
		},
		[startNewSession, getInitialGreeting],
	);

	const clearChat = useCallback(async () => {
		console.log("AIChatContext: Clearing chat.");
		if (sessionId) {
			try {
				console.log("AIChatContext: Deleting session from server:", sessionId);
				await api.deleteChatSession(sessionId);
				console.log("AIChatContext: Session deleted from server.");
			} catch (error) {
				console.error(
					"AIChatContext: Failed to delete chat session on the server:",
					error,
				);
				// Continue with client-side clearing even if server fails
			}
		}
		localStorage.removeItem("ai-copilot-session-id");
		await startNewSession();
	}, [sessionId, startNewSession]);

	useEffect(() => {
		const initializeChat = async () => {
			console.log("AIChatContext: useEffect triggered, initializing chat...");

			try {
				console.log("AIChatContext: Fetching latest session from server...");
				const latestSessionId = await api.getLatestChatSession();
				if (latestSessionId) {
					console.log(
						"AIChatContext: Found latest session on server:",
						latestSessionId,
					);
					await loadSession(latestSessionId);
				} else {
					console.log(
						"AIChatContext: No session on server, starting new session.",
					);
					await startNewSession();
				}
			} catch (error) {
				console.error("AIChatContext: Error fetching latest session:", error);
				// Fallback to localStorage if server fails
				const savedSessionId = localStorage.getItem("ai-copilot-session-id");
				if (savedSessionId) {
					console.log(
						"AIChatContext: Fallback to localStorage session:",
						savedSessionId,
					);
					await loadSession(savedSessionId);
				} else {
					console.log("AIChatContext: Starting new session as fallback.");
					await startNewSession();
				}
			}
		};

		initializeChat();
	}, [startNewSession, loadSession]);

	const sendMessage = async (content: string) => {
		if (!sessionId) {
			console.error("Cannot send message: no session ID.");
			return;
		}
		setIsTyping(true);
		const userMessage: Message = {
			id: `user-${Date.now()}`,
			role: "user",
			content,
		};
		setMessages((prev) => [...prev, userMessage]);

		try {
			const response = await api.aiChat({
				session_id: sessionId,
				text_prompt: content,
				backtest_id: backtestId,
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

	return (
		<AIChatContext.Provider
			value={{
				messages,
				sessionId,
				backtestId,
				isLoading,
				isTyping,
				sendMessage,
				setMessages,
				setBacktestId,
				clearChat,
				setIsTyping,
				setSessionId,
			}}
		>
			{children}
		</AIChatContext.Provider>
	);
};

export const useAIChat = () => {
	const context = useContext(AIChatContext);
	if (context === undefined) {
		throw new Error("useAIChat must be used within an AIChatProvider");
	}
	return context;
};
