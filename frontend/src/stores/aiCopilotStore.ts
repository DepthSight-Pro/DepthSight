// src/stores/aiCopilotStore.ts

import { v4 as uuidv4 } from "uuid";
import { create } from "zustand";
import { apiClient } from "../lib/api"; // Import apiClient service

// As defined in the backend and api.ts
export interface Message {
	role: "user" | "assistant";
	content: string | null; // Allow content to be null
	strategy_json?: Record<string, unknown> | null;
	image_base64?: string;
	image_mime_type?: string;
}

interface DbMessage {
	role: string;
	content: string | null;
	strategy_json?: Record<string, unknown> | null;
	image_base64?: string;
	image_mime_type?: string;
}

type WidgetState = "open" | "minimized";

interface AiCopilotState {
	widgetState: WidgetState;
	messages: Message[];
	sessionId: string | null;
	isLoading: boolean;
	isTyping: boolean;
	setWidgetState: (newState: WidgetState) => void;
	addMessage: (message: Message) => void;
	setMessages: (messages: Message[]) => void;
	startNewSession: (initialMessage: string) => void;
	setSessionId: (sessionId: string) => void;
	setIsLoading: (isLoading: boolean) => void;
	setIsTyping: (isTyping: boolean) => void;
	clearChat: (initialMessage: string) => void;
	loadInitialSession: (initialGreeting: string) => Promise<void>;
	analyticsContext: Record<string, unknown> | null;
	setAnalyticsContext: (context: Record<string, unknown> | null) => void;
}

export const useAiCopilotStore = create<AiCopilotState>()((set, get) => ({
	widgetState: "minimized",
	messages: [],
	sessionId: null,
	isLoading: false,
	isTyping: false,
	analyticsContext: null,
	setAnalyticsContext: (context) => set({ analyticsContext: context }),
	setWidgetState: (newState) => set({ widgetState: newState }),
	addMessage: (message) =>
		set((state) => ({ messages: [...state.messages, message] })),
	setMessages: (messages) => set({ messages }),
	startNewSession: async (initialMessage: string) => {
		console.log(
			"AiCopilotStore: startNewSession called with initialMessage:",
			initialMessage,
		);
		const newSessionId = uuidv4();
		localStorage.setItem("ai-copilot-session-id", newSessionId);
		set({
			messages: [{ role: "assistant", content: initialMessage }],
			sessionId: newSessionId,
			widgetState: "open",
		});

		// Save initial greeting message to DB so this session is registered on server
		try {
			await apiClient("/ai/chat/history/init", {
				method: "POST",
				body: JSON.stringify({
					session_id: newSessionId,
					initial_message: initialMessage,
				}),
			});
			console.log(
				"AiCopilotStore: Initial greeting saved to server for session:",
				newSessionId,
			);
		} catch (error) {
			console.error(
				"AiCopilotStore: Failed to save initial greeting to server:",
				error,
			);
			// Non-critical error, continue anyway
		}
	},
	setSessionId: (sessionId) => {
		localStorage.setItem("ai-copilot-session-id", sessionId);
		set({ sessionId });
	},
	setIsLoading: (isLoading) => set({ isLoading }),
	setIsTyping: (isTyping) => set({ isTyping }),
	clearChat: async (initialMessage: string) => {
		console.log(
			"AiCopilotStore: clearChat called with initialMessage:",
			initialMessage,
		);
		const currentSessionId = get().sessionId;

		// Delete session from server if it exists
		if (currentSessionId) {
			try {
				console.log(
					"AiCopilotStore: Deleting session from server:",
					currentSessionId,
				);
				await apiClient(`/ai/chat/history/${currentSessionId}`, {
					method: "DELETE",
				});
				console.log("AiCopilotStore: Session deleted from server.");
			} catch (error) {
				console.error(
					"AiCopilotStore: Failed to delete session from server:",
					error,
				);
				// Continue with client-side clearing even if server fails
			}
		}

		// Clear localStorage and create new session
		localStorage.removeItem("ai-copilot-session-id");
		const newSessionId = uuidv4();
		localStorage.setItem("ai-copilot-session-id", newSessionId);
		set({
			messages: [{ role: "assistant", content: initialMessage }],
			sessionId: newSessionId,
		});
	},
	loadInitialSession: async (initialGreeting: string) => {
		console.log("AiCopilotStore: loadInitialSession called");
		set({ isLoading: true });

		try {
			// First, try to get the latest session from the server
			console.log("AiCopilotStore: Fetching latest session from server...");
			const latestSessionId = await apiClient<string | null>(
				"/ai/chat/latest-session",
			);

			if (latestSessionId) {
				console.log(
					"AiCopilotStore: Found latest session on server:",
					latestSessionId,
				);
				const history = await apiClient<DbMessage[]>(
					`/ai/chat/history/${latestSessionId}`,
				);
				console.log("AiCopilotStore: Loaded history:", history);

				const formattedMessages: Message[] = history.map((msg: DbMessage) => ({
					role: msg.role as "user" | "assistant",
					content: msg.content,
					strategy_json: msg.strategy_json || null,
					image_base64: msg.image_base64,
					image_mime_type: msg.image_mime_type,
				}));

				localStorage.setItem("ai-copilot-session-id", latestSessionId);

				// If history is empty, add initial greeting. Otherwise, use history as-is (it already has greeting)
				const messages =
					formattedMessages.length > 0
						? formattedMessages
						: ([
								{
									role: "assistant",
									content: initialGreeting as Message["content"],
								},
							] as Message[]);

				set({
					messages,
					sessionId: latestSessionId,
				});
			} else {
				console.log(
					"AiCopilotStore: No session on server, starting new session.",
				);
				await get().startNewSession(initialGreeting);
			}
		} catch (error) {
			console.error("AiCopilotStore: Error fetching latest session:", error);
			// Fallback to localStorage if server fails
			const savedSessionId = localStorage.getItem("ai-copilot-session-id");
			if (savedSessionId) {
				console.log(
					"AiCopilotStore: Fallback to localStorage session:",
					savedSessionId,
				);
				try {
					const history = await apiClient<DbMessage[]>(
						`/ai/chat/history/${savedSessionId}`,
					);
					const formattedMessages: Message[] = history.map(
						(msg: DbMessage) => ({
							role: msg.role as "user" | "assistant",
							content: msg.content,
							strategy_json: msg.strategy_json || null,
							image_base64: msg.image_base64,
							image_mime_type: msg.image_mime_type,
						}),
					);

					// If history is empty, add initial greeting. Otherwise, use history as-is
					const messages =
						formattedMessages.length > 0
							? formattedMessages
							: ([
									{
										role: "assistant",
										content: initialGreeting as Message["content"],
									},
								] as Message[]);

					set({ messages, sessionId: savedSessionId });
				} catch (historyError) {
					console.error(
						"AiCopilotStore: Failed to load localStorage session history:",
						historyError,
					);
					await get().startNewSession(initialGreeting);
				}
			} else {
				console.log("AiCopilotStore: Starting new session as fallback.");
				await get().startNewSession(initialGreeting);
			}
		} finally {
			set({ isLoading: false });
		}
	},
}));
