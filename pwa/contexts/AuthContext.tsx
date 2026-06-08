// pwa/contexts/AuthContext.tsx

import type React from "react";
import {
	createContext,
	type ReactNode,
	useContext,
	useEffect,
	useState,
} from "react";
import { api } from "../services/api";
import type { Token, User } from "../types";

interface AuthContextType {
	user: User | null;
	token: Token | null;
	isLoading: boolean;
	login: (formData: FormData) => Promise<void>;
	logout: () => void;
	setAuthToken: (tokenData: Token) => void;
	loginWithTokenAndUser: (tokenData: Token, userData: User) => void;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export const AuthProvider: React.FC<{ children: ReactNode }> = ({
	children,
}) => {
	const [user, setUser] = useState<User | null>(null);
	const [token, setToken] = useState<Token | null>(() => {
		try {
			const tokenString = localStorage.getItem("authToken");
			return tokenString ? JSON.parse(tokenString) : null;
		} catch {
			return null;
		}
	});
	const [isLoading, setIsLoading] = useState(true);

	useEffect(() => {
		const validateToken = async () => {
			if (token) {
				try {
					const userData = await api.getMe();
					setUser(userData);
				} catch (error) {
					console.error("Token validation failed", error);
					setToken(null);
					setUser(null);
					localStorage.removeItem("authToken");
				}
			}
			setIsLoading(false);
		};
		validateToken();
	}, [token]);

	const handleAuthSuccess = (tokenData: Token, userData: User) => {
		setToken(tokenData);
		setUser(userData);
		localStorage.setItem("authToken", JSON.stringify(tokenData));
	};

	const login = async (formData: FormData) => {
		const { token: tokenData, user: userData } = await api.login(formData);
		handleAuthSuccess(tokenData, userData);
	};

	const logout = () => {
		setToken(null);
		setUser(null);
		localStorage.removeItem("authToken");
	};

	const setAuthToken = (tokenData: Token) => {
		console.log("[AuthContext] Setting auth token");
		setToken(tokenData);
		localStorage.setItem("authToken", JSON.stringify(tokenData));
	};

	const loginWithTokenAndUser = (tokenData: Token, userData: User) => {
		console.log("[AuthContext] Setting auth token and user data");
		setToken(tokenData);
		setUser(userData);
		localStorage.setItem("authToken", JSON.stringify(tokenData));
	};

	const value = {
		user,
		token,
		isLoading,
		login,
		logout,
		setAuthToken,
		loginWithTokenAndUser,
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
