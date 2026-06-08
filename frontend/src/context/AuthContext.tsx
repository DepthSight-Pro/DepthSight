// frontend/src/context/AuthContext.tsx

import { useQueryClient } from "@tanstack/react-query";
/* eslint-disable react-refresh/only-export-components */
import type React from "react";
import {
	createContext,
	useCallback,
	useContext,
	useEffect,
	useState,
} from "react";
import { useNavigate } from "react-router-dom";
import { apiClient } from "@/lib/api";
import { resetUserScopedClientState } from "@/lib/clientState";
import type { User } from "@/types/api";

interface AuthContextType {
	user: User | null;
	token: string | null;
	isLoading: boolean;
	login: (data: {
		token: { access_token: string; refresh_token: string };
		user: User;
	}) => Promise<void>;
	logout: () => void;
	impersonate: (token: string) => void;
	stopImpersonating: () => void;
	isImpersonating: boolean;
}

const AuthContext = createContext<AuthContextType | null>(null);

export const AuthProvider: React.FC<{ children: React.ReactNode }> = ({
	children,
}) => {
	const [user, setUser] = useState<User | null>(null);
	const [token, setToken] = useState<string | null>(null);
	const [isLoading, setIsLoading] = useState(true);
	const navigate = useNavigate();
	const queryClient = useQueryClient();

	const [isImpersonating, setIsImpersonating] = useState(false);

	const logout = useCallback(() => {
		queryClient.clear();
		resetUserScopedClientState();
		setUser(null);
		setToken(null);
		localStorage.removeItem("authToken");
		localStorage.removeItem("refreshToken");
		localStorage.removeItem("originalAuthToken");
		localStorage.removeItem("originalRefreshToken");
		setIsImpersonating(false);

		navigate("/login");
	}, [navigate, queryClient]);

	useEffect(() => {
		const initializeAuth = async () => {
			const storedToken = localStorage.getItem("authToken");
			// --- Checking if there is an original token ---
			const originalToken = localStorage.getItem("originalAuthToken");
			if (originalToken) {
				setIsImpersonating(true);
			}

			if (storedToken) {
				try {
					const userData = await apiClient<User>("/users/me"); // Specify the User type
					setUser(userData);
					setToken(storedToken);
				} catch (error) {
					console.error("Failed to validate token on startup", error);
					// Clear storage without forced navigation
					localStorage.removeItem("authToken");
					localStorage.removeItem("refreshToken");
					localStorage.removeItem("originalAuthToken");
					localStorage.removeItem("originalRefreshToken");
					setUser(null);
					setToken(null);
					setIsImpersonating(false);
				}
			}
			setIsLoading(false);
		};

		initializeAuth();
	}, []);

	const login = async (data: {
		token: { access_token: string; refresh_token: string };
		user: User;
	}) => {
		const { token: tokenData, user: initialUserData } = data;
		queryClient.clear();
		resetUserScopedClientState();
		localStorage.setItem("authToken", tokenData.access_token);
		localStorage.setItem("refreshToken", tokenData.refresh_token);
		setToken(tokenData.access_token);

		// Set initial user data immediately for a responsive UI
		setUser(initialUserData);

		// Then, re-fetch the user data to get the absolute latest state after all login-related DB updates
		try {
			const freshUserData = await apiClient<User>("/users/me");
			setUser(freshUserData);
		} catch (error) {
			console.error(
				"Failed to re-fetch user after login, using initial data.",
				error,
			);
			// If re-fetch fails, we stick with the data from the login response
			setUser(initialUserData);
		}

		if (initialUserData.role === "admin") {
			navigate("/admin");
		} else {
			navigate("/");
		}
	};

	const impersonate = (newToken: string) => {
		const currentToken = localStorage.getItem("authToken");
		const currentRefreshToken = localStorage.getItem("refreshToken");
		if (currentToken) {
			localStorage.setItem("originalAuthToken", currentToken);
		}
		if (currentRefreshToken) {
			localStorage.setItem("originalRefreshToken", currentRefreshToken);
		}
		queryClient.clear();
		resetUserScopedClientState();
		localStorage.setItem("authToken", newToken);
		localStorage.removeItem("refreshToken"); // No refresh token during impersonation
		// Full reload to reset the entire application state
		window.location.href = "/";
	};

	const stopImpersonating = () => {
		const originalToken = localStorage.getItem("originalAuthToken");
		const originalRefreshToken = localStorage.getItem("originalRefreshToken");
		if (originalToken) {
			queryClient.clear();
			resetUserScopedClientState();
			localStorage.setItem("authToken", originalToken);
			localStorage.removeItem("originalAuthToken");
			if (originalRefreshToken) {
				localStorage.setItem("refreshToken", originalRefreshToken);
				localStorage.removeItem("originalRefreshToken");
			}
			// Returning to the users page in the admin panel
			window.location.href = "/admin/users";
		}
	};

	return (
		<AuthContext.Provider
			value={{
				user,
				token,
				isLoading,
				login,
				logout,
				impersonate,
				stopImpersonating,
				isImpersonating,
			}}
		>
			{children}
		</AuthContext.Provider>
	);
};

// Hook for convenient access to the context
export const useAuth = () => {
	const context = useContext(AuthContext);
	if (!context) {
		throw new Error("useAuth must be used within an AuthProvider");
	}
	return context;
};
