// pwa/contexts/AuthContext.tsx

import type React from "react";
import {
	createContext,
	type ReactNode,
	useContext,
	useEffect,
	useState,
} from "react";
import { api, readAccessToken, readRefreshToken } from "../services/api";
import type { LoginResponse, Token, User } from "../types";

interface AuthContextType {
	user: User | null;
	token: Token | null;
	isLoading: boolean;
	login: (formData: FormData) => Promise<LoginResponse>;
	logout: () => void;
	setAuthToken: (tokenData: Token) => void;
	loginWithTokenAndUser: (tokenData: Token, userData: User) => void;
	updateUser: (updates: Partial<User>) => void;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export const AuthProvider: React.FC<{ children: ReactNode }> = ({
	children,
}) => {
	const [user, setUser] = useState<User | null>(() => {
		try {
			const cachedUser = localStorage.getItem("authUser");
			return cachedUser ? JSON.parse(cachedUser) : null;
		} catch {
			return null;
		}
	});

	const [token, setToken] = useState<Token | null>(() => {
		try {
			const at = readAccessToken();
			const rt = readRefreshToken();
			if (at) {
				return {
					access_token: at,
					refresh_token: rt || "",
					token_type: "bearer",
				};
			}
			return null;
		} catch {
			return null;
		}
	});

	const [isLoading, setIsLoading] = useState(() => {
		return readAccessToken() !== null || readRefreshToken() !== null;
	});

	// Validate / refresh user session on mount
	useEffect(() => {
		let isMounted = true;
		const validateToken = async () => {
			const hasToken = readAccessToken() !== null || readRefreshToken() !== null;
			if (hasToken) {
				try {
					const userData = await api.getMe();
					if (isMounted) {
						setUser(userData);
						localStorage.setItem("authUser", JSON.stringify(userData));
						const at = readAccessToken();
						const rt = readRefreshToken();
						if (at) {
							setToken({
								access_token: at,
								refresh_token: rt || "",
								token_type: "bearer",
							});
						}
					}
				} catch (error) {
					console.error("[AuthContext] Token validation error:", error);
					// If token validation failed and refresh token is truly invalid/expired
					const hasAnyToken = readAccessToken() !== null || readRefreshToken() !== null;
					if (!hasAnyToken && isMounted) {
						setUser(null);
						setToken(null);
					}
				}
			} else {
				if (isMounted) {
					setUser(null);
					setToken(null);
					localStorage.removeItem("authUser");
				}
			}
			if (isMounted) {
				setIsLoading(false);
			}
		};

		validateToken();
		return () => {
			isMounted = false;
		};
	}, []);

	// Listen for token refresh or logout events dispatched by apiFetch
	useEffect(() => {
		const handleTokenRefreshed = (e: Event) => {
			const customEvent = e as CustomEvent<{
				token: string;
				refreshToken?: string;
				tokenData?: Token;
			}>;
			const detail = customEvent.detail;
			if (detail?.tokenData) {
				setToken(detail.tokenData);
			} else if (detail?.token) {
				setToken({
					access_token: detail.token,
					refresh_token: detail.refreshToken || readRefreshToken() || "",
					token_type: "bearer",
				});
			}
		};

		const handleLogout = () => {
			setToken(null);
			setUser(null);
			localStorage.removeItem("authToken");
			localStorage.removeItem("refreshToken");
			localStorage.removeItem("authUser");
		};

		window.addEventListener("auth:token-refreshed", handleTokenRefreshed);
		window.addEventListener("auth:logout", handleLogout);
		return () => {
			window.removeEventListener("auth:token-refreshed", handleTokenRefreshed);
			window.removeEventListener("auth:logout", handleLogout);
		};
	}, []);

	const handleAuthSuccess = (tokenData: Token, userData: User) => {
		setToken(tokenData);
		setUser(userData);
		localStorage.setItem("authToken", tokenData.access_token);
		if (tokenData.refresh_token) {
			localStorage.setItem("refreshToken", tokenData.refresh_token);
		}
		localStorage.setItem("authUser", JSON.stringify(userData));
	};

	const login = async (formData: FormData): Promise<LoginResponse> => {
		const res = await api.login(formData);
		if (res.requires_2fa && res.temp_token) {
			return res;
		}
		if (res.token && res.user) {
			handleAuthSuccess(res.token, res.user);
		}
		return res;
	};

	const logout = () => {
		setToken(null);
		setUser(null);
		localStorage.removeItem("authToken");
		localStorage.removeItem("refreshToken");
		localStorage.removeItem("authUser");
		if (typeof window !== "undefined") {
			window.dispatchEvent(new CustomEvent("auth:logout"));
		}
	};

	const setAuthToken = (tokenData: Token) => {
		console.log("[AuthContext] Setting auth token");
		setToken(tokenData);
		localStorage.setItem("authToken", tokenData.access_token);
		if (tokenData.refresh_token) {
			localStorage.setItem("refreshToken", tokenData.refresh_token);
		}
	};

	const loginWithTokenAndUser = (tokenData: Token, userData: User) => {
		console.log("[AuthContext] Setting auth token and user data");
		handleAuthSuccess(tokenData, userData);
	};

	const updateUser = (updates: Partial<User>) => {
		setUser((prev) => {
			if (!prev) return null;
			const updated = { ...prev, ...updates };
			localStorage.setItem("authUser", JSON.stringify(updated));
			return updated;
		});
	};

	const value = {
		user,
		token,
		isLoading,
		login,
		logout,
		setAuthToken,
		loginWithTokenAndUser,
		updateUser,
	};

	return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
};

export const useAuth = (): AuthContextType => {
	const context = useContext(AuthContext);
	if (context === undefined) {
		throw new Error("useAuth must be used within an AuthProvider");
	}
	return context;
};
