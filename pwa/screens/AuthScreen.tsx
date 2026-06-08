// pwa/screens/AuthScreen.tsx

import { Loader2 } from "lucide-react";
import type React from "react";
import { useEffect, useState } from "react";
import { toast } from "react-hot-toast";
import { useTranslation } from "react-i18next";
import { Input } from "../components/ui/Input";
import { useAuth } from "../contexts/AuthContext";
import ForgotPasswordScreen from "./ForgotPasswordScreen";

const AuthScreen: React.FC = () => {
	const [isLogin, setIsLogin] = useState(true);
	const { login } = useAuth();
	const [error, setError] = useState("");
	const [loading, setLoading] = useState(false);
	const [registrationSuccess, setRegistrationSuccess] = useState(false);
	const [registeredEmail, setRegisteredEmail] = useState("");
	const [resendTimer, setResendTimer] = useState(0);
	const [isResending, setIsResending] = useState(false);
	const [refCode] = useState<string | undefined>(() => {
		const params = new URLSearchParams(window.location.search);
		let ref = params.get("ref");
		if (!ref && window.location.hash) {
			const hashParams = new URLSearchParams(
				window.location.hash.split("?")[1],
			);
			ref = hashParams.get("ref");
		}
		return ref || undefined;
	});
	const { t } = useTranslation("pwa-common");

	// Log referral code on mount
	useEffect(() => {
		console.log("[AuthScreen] Current URL:", window.location.href);
		console.log("[AuthScreen] Search params:", window.location.search);
		console.log("[AuthScreen] Hash:", window.location.hash);

		if (refCode) {
			console.log("[AuthScreen] Found referral code:", refCode);
		} else {
			console.log("[AuthScreen] No referral code found in URL");
		}
	}, [refCode]);

	const handleSubmit = async (e: React.FormEvent) => {
		e.preventDefault();
		setError("");
		setLoading(true);

		const formData = new FormData(e.currentTarget as HTMLFormElement);

		try {
			if (isLogin) {
				// For login, the API expects x-www-form-urlencoded, which FormData provides.
				await login(formData);
			} else {
				// For register, we need to construct a JSON object
				const registerData = Object.fromEntries(formData.entries());

				// Validate password confirmation
				if (registerData.password !== registerData.confirmPassword) {
					setError(t("auth.passwordsDoNotMatch"));
					setLoading(false);
					return;
				}

				// Remove confirmPassword before sending
				delete registerData.confirmPassword;

				// Add source to indicate registration from PWA
				registerData.source = "pwa";

				const response = await fetch("/api/v1/register", {
					method: "POST",
					headers: { "Content-Type": "application/json" },
					body: JSON.stringify(registerData),
				});

				const responseData = await response.json();

				if (!response.ok) {
					const errorData = responseData;
					if (response.status === 409) {
						if (
							typeof errorData.detail === "string" &&
							errorData.detail.includes("Username")
						) {
							throw new Error(t("auth.usernameTaken"));
						} else if (
							typeof errorData.detail === "string" &&
							errorData.detail.includes("Email")
						) {
							throw new Error(t("auth.emailTaken"));
						}
					}
					throw new Error(errorData.detail || t("auth.registrationError"));
				}

				const requiresConfirmation =
					responseData.data?.requires_confirmation !== false; // Default to true

				if (requiresConfirmation) {
					setRegisteredEmail(registerData.email as string);
					setRegistrationSuccess(true);
					setResendTimer(60); // Start timer immediately
				} else {
					// Auto-switch to login
					toast.success(
						t("auth.registrationSuccessTitle") || "Registration successful",
					);
					setIsLogin(true);
				}
			}
		} catch (err) {
			console.error("Auth error:", err);
			const errorMessage =
				err instanceof Error
					? err.message
					: (isLogin
							? t("auth.invalidCredentials")
							: t("auth.registrationError"));
			setError(errorMessage);
		} finally {
			setLoading(false);
		}
	};

	const handleResendEmail = async () => {
		if (resendTimer > 0 || !registeredEmail) return;

		setIsResending(true);
		try {
			const response = await fetch("/api/v1/auth/resend-confirmation", {
				method: "POST",
				headers: { "Content-Type": "application/json" },
				body: JSON.stringify({ email: registeredEmail }),
			});

			if (response.ok) {
				setResendTimer(60); // 1 minute
			} else {
				const data = await response.json();
				setError(data.detail || t("auth.resendFailedDescription"));
			}
		} catch {
			setError(t("auth.resendFailedDescription"));
		} finally {
			setIsResending(false);
		}
	};

	useEffect(() => {
		if (resendTimer > 0) {
			const timer = setTimeout(() => setResendTimer(resendTimer - 1), 1000);
			return () => clearTimeout(timer);
		}
	}, [resendTimer]);

	const [view, setView] = useState<"auth" | "forgot-password">("auth");

	if (view === "forgot-password") {
		return (
			<div className="flex items-center justify-center min-h-screen bg-[hsl(var(--background))] p-4">
				<ForgotPasswordScreen onBack={() => setView("auth")} />
			</div>
		);
	}

	if (registrationSuccess) {
		return (
			<div className="flex items-center justify-center min-h-screen bg-[hsl(var(--background))] p-4">
				<div className="w-full max-w-md p-8 space-y-6 bg-[hsl(var(--card))] rounded-lg shadow-md">
					<h2 className="text-2xl font-bold text-center text-[hsl(var(--foreground))]">
						{t("auth.registrationSuccessTitle")}
					</h2>
					<p className="text-sm text-center text-[hsl(var(--muted-foreground))]">
						{t("auth.confirmEmailPrompt")}
					</p>
					<p className="text-sm text-center text-[hsl(var(--muted-foreground))]">
						{t("auth.confirmEmailInstructions")}
					</p>

					<div className="space-y-3">
						<button
							onClick={handleResendEmail}
							disabled={resendTimer > 0 || isResending}
							className="w-full py-3 rounded-lg border border-[hsl(var(--border))] text-base font-medium bg-transparent text-[hsl(var(--foreground))] transition hover:bg-[hsl(var(--accent))] disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center"
						>
							{isResending ? (
								<>
									<Loader2 className="mr-2 h-4 w-4 animate-spin" />
									{t("auth.resendingEmail")}
								</>
							) : resendTimer > 0 ? (
								t("auth.resendEmailTimer", { seconds: resendTimer })
							) : (
								t("auth.resendEmail")
							)}
						</button>

						<button
							onClick={() => {
								setRegistrationSuccess(false);
								setIsLogin(true);
								setError("");
							}}
							className="w-full py-3 rounded-lg border-none text-base font-medium bg-[hsl(var(--primary))] text-[hsl(var(--primary-foreground))] transition hover:opacity-90"
						>
							{t("auth.backToLogin")}
						</button>
					</div>
				</div>
			</div>
		);
	}

	return (
		<div className="flex items-center justify-center min-h-screen bg-[hsl(var(--background))] p-4">
			<div className="w-full max-w-md p-8 space-y-6 bg-[hsl(var(--card))] rounded-lg shadow-md">
				<h2 className="text-2xl font-bold text-center text-[hsl(var(--foreground))]">
					{isLogin ? t("auth.loginToAccount") : t("auth.createAccount")}
				</h2>
				<form onSubmit={handleSubmit} className="space-y-4">
					{!isLogin && (
						<div>
							<label
								className="text-sm text-[hsl(var(--muted-foreground))] mb-2 block"
								htmlFor="email"
							>
								{t("auth.email")}
							</label>
							<Input
								id="email"
								name="email"
								type="email"
								placeholder="email@example.com"
								required
								className="w-full"
							/>
						</div>
					)}
					<div>
						<label
							className="text-sm text-[hsl(var(--muted-foreground))] mb-2 block"
							htmlFor="username"
						>
							{t("auth.username")}
						</label>
						<Input
							id="username"
							name="username"
							type="text"
							placeholder="username"
							required
							className="w-full"
						/>
					</div>
					<div>
						<div className="flex justify-between items-center mb-2">
							<label
								className="text-sm text-[hsl(var(--muted-foreground))]"
								htmlFor="password"
							>
								{t("auth.password")}
							</label>
							{isLogin && (
								<button
									type="button"
									onClick={() => setView("forgot-password")}
									className="text-xs text-[hsl(var(--primary))] hover:underline bg-transparent border-none cursor-pointer p-0"
								>
									{t("auth.forgotPassword")}
								</button>
							)}
						</div>
						<Input
							id="password"
							name="password"
							type="password"
							placeholder="password"
							required
							minLength={6}
							className="w-full"
						/>
					</div>
					{!isLogin && (
						<div>
							<label
								className="text-sm text-[hsl(var(--muted-foreground))] mb-2 block"
								htmlFor="confirmPassword"
							>
								{t("auth.confirmPassword")}
							</label>
							<Input
								id="confirmPassword"
								name="confirmPassword"
								type="password"
								placeholder="password"
								required
								minLength={6}
								className="w-full"
							/>
						</div>
					)}
					{!isLogin && (
						<div>
							<label
								className="text-sm text-[hsl(var(--muted-foreground))] mb-2 block"
								htmlFor="ref_code"
							>
								{t("auth.referralCode")}
							</label>
							<Input
								id="ref_code"
								name="ref_code"
								type="text"
								placeholder={t("auth.referralCodePlaceholder")}
								defaultValue={refCode || ""}
								disabled={!!refCode}
								className="w-full"
							/>
						</div>
					)}
					{error && (
						<p className="text-sm text-center text-[hsl(var(--loss))] mb-4">
							{error}
						</p>
					)}
					<button
						type="submit"
						disabled={loading}
						className="w-full py-3 rounded-lg border-none text-base font-medium bg-[hsl(var(--primary))] text-[hsl(var(--primary-foreground))] transition hover:opacity-90 disabled:opacity-50 disabled:cursor-wait flex items-center justify-center"
					>
						{loading ? (
							<>
								<Loader2 className="mr-2 h-4 w-4 animate-spin" />
								{t("loadingScreen")}
							</>
						) : isLogin ? (
							t("auth.login")
						) : (
							t("auth.register")
						)}
					</button>
				</form>
				<p className="text-center text-sm text-[hsl(var(--muted-foreground))]">
					{isLogin ? t("auth.noAccount") : t("auth.alreadyHaveAccount")}
					<button
						onClick={() => {
							setIsLogin(!isLogin);
							setError("");
							setRegistrationSuccess(false);
						}}
						className="font-medium text-[hsl(var(--primary))] ml-2 bg-transparent border-none cursor-pointer"
					>
						{isLogin ? t("auth.create") : t("auth.login")}
					</button>
				</p>
			</div>
		</div>
	);
};

export default AuthScreen;
