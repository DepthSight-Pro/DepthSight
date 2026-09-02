import { Loader2, ShieldCheck } from "lucide-react";
import type React from "react";
import { useEffect, useState } from "react";
import { toast } from "react-hot-toast";
import { useTranslation } from "react-i18next";
import { Input } from "../components/ui/Input";
import { useAuth } from "../contexts/AuthContext";
import { api } from "../services/api";
import ForgotPasswordScreen from "./ForgotPasswordScreen";
import { GoogleLogin } from "@react-oauth/google";

const AuthScreen: React.FC = () => {
	const [isLogin, setIsLogin] = useState(true);
	const { login, loginWithTokenAndUser } = useAuth();
	const [error, setError] = useState("");
	const [loading, setLoading] = useState(false);
	const [twoFactorPending, setTwoFactorPending] = useState(false);
	const [tempToken, setTempToken] = useState<string | null>(null);
	const [otpCode, setOtpCode] = useState("");
	const [useBackupCode, setUseBackupCode] = useState(false);
	const [backupCode, setBackupCode] = useState("");
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
				const res = await login(formData);
				if (res?.requires_2fa && res?.temp_token) {
					setTempToken(res.temp_token);
					setTwoFactorPending(true);
					setOtpCode("");
					setBackupCode("");
					setUseBackupCode(false);
					setLoading(false);
					return;
				}
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

	const handleGoogleSuccess = async (credentialResponse: any) => {
		if (!credentialResponse.credential) return;

		setLoading(true);
		setError("");

		try {
			const response = await fetch("/api/v1/auth/google", {
				method: "POST",
				headers: { "Content-Type": "application/json" },
				body: JSON.stringify({ token: credentialResponse.credential }),
			});

			if (!response.ok) {
				const errorData = await response.json();
				throw new Error(errorData.detail || "Google login failed");
			}

			const data = await response.json();
			if (data.requires_2fa && data.temp_token) {
				setTempToken(data.temp_token);
				setTwoFactorPending(true);
				setOtpCode("");
				setBackupCode("");
				setUseBackupCode(false);
				setLoading(false);
				return;
			}
			loginWithTokenAndUser(data.token, data.user);
			toast.success("Logged in successfully");
		} catch (err) {
			console.error("Google login error:", err);
			setError(err instanceof Error ? err.message : "Google login failed");
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

	const handleVerify2FADirect = async (codeToVerify: string) => {
		if (!tempToken || !codeToVerify) return;
		setLoading(true);
		setError("");
		try {
			const { token: tokenData, user: userData } = await api.verifyTotpLogin({
				tempToken,
				code: codeToVerify,
			});
			loginWithTokenAndUser(tokenData, userData);
			toast.success(t("auth.loginSuccess") || "Logged in successfully");
		} catch (err: any) {
			setError(err.message || t("twoFactor.invalidCode") || "Invalid verification code");
		} finally {
			setLoading(false);
		}
	};

	const handleVerify2FA = async (e?: React.FormEvent) => {
		if (e) e.preventDefault();
		const code = useBackupCode ? backupCode.trim() : otpCode.trim();
		handleVerify2FADirect(code);
	};

	if (twoFactorPending) {
		return (
			<div className="flex flex-col items-center justify-center min-h-[100dvh] bg-[hsl(var(--background))] p-4 overflow-y-auto py-8">
				<div className="w-full max-w-md p-6 sm:p-8 space-y-6 bg-[hsl(var(--card))] rounded-3xl shadow-xl border border-[hsl(var(--border))] my-auto">
					<div className="text-center space-y-2">
						<div className="mx-auto w-14 h-14 rounded-2xl bg-[hsl(var(--primary))]/10 border border-[hsl(var(--primary))]/20 flex items-center justify-center text-[hsl(var(--primary))] mb-3">
							<ShieldCheck className="w-7 h-7" />
						</div>
						<h2 className="text-2xl font-bold text-[hsl(var(--foreground))]">
							{t("twoFactor.cardTitle", "Two-Factor Authentication")}
						</h2>
						<p className="text-sm text-[hsl(var(--muted-foreground))]">
							{useBackupCode
								? t(
										"twoFactor.enterBackupCode",
										"Enter one of your 8-character single-use recovery codes",
									)
								: t(
										"twoFactor.enterAuthenticatorCode",
										"Enter the 6-digit verification code from your authenticator app",
									)}
						</p>
					</div>

					{error && (
						<div className="p-3 text-sm text-[hsl(var(--loss))] bg-[hsl(var(--loss))]/10 rounded-xl border border-[hsl(var(--loss))]/20 text-center">
							{error}
						</div>
					)}

					<form onSubmit={handleVerify2FA} className="space-y-4">
						{useBackupCode ? (
							<div>
								<label className="text-sm text-[hsl(var(--muted-foreground))] mb-2 block font-medium">
									{t("twoFactor.backupCodeLabel", "Backup Recovery Code")}
								</label>
								<Input
									type="text"
									value={backupCode}
									onChange={(e) => setBackupCode(e.target.value.toUpperCase())}
									placeholder="XXXX-XXXX"
									className="w-full text-center font-mono text-lg tracking-widest uppercase"
								/>
							</div>
						) : (
							<div>
								<label className="text-sm text-[hsl(var(--muted-foreground))] mb-2 block text-center font-medium">
									{t("twoFactor.enterCodeLabel", "6-digit Authenticator Code")}
								</label>
								<Input
									type="text"
									inputMode="numeric"
									pattern="[0-9]*"
									maxLength={6}
									value={otpCode}
									onChange={(e) => {
										const val = e.target.value.replace(/\D/g, "").slice(0, 6);
										setOtpCode(val);
										if (val.length === 6) {
											setTimeout(() => {
												handleVerify2FADirect(val);
											}, 50);
										}
									}}
									placeholder="••••••"
									className="w-full text-center font-mono text-2xl tracking-[0.4em] h-14"
								/>
							</div>
						)}

						<button
							type="submit"
							disabled={
								loading ||
								(useBackupCode ? !backupCode.trim() : otpCode.length !== 6)
							}
							className="w-full py-3 px-4 bg-[hsl(var(--primary))] hover:opacity-90 disabled:opacity-50 text-[hsl(var(--primary-foreground))] font-semibold rounded-xl transition duration-200 flex items-center justify-center shadow-lg shadow-[hsl(var(--primary))]/20"
						>
							{loading ? (
								<Loader2 className="w-5 h-5 animate-spin" />
							) : (
								t("twoFactor.verifyAndLogin", "Verify & Log In")
							)}
						</button>
					</form>

					<div className="flex flex-col items-center space-y-3 pt-2 text-sm">
						<button
							type="button"
							onClick={() => {
								setUseBackupCode(!useBackupCode);
								setOtpCode("");
								setBackupCode("");
								setError("");
							}}
							className="text-[hsl(var(--primary))] hover:underline"
						>
							{useBackupCode
								? t(
										"twoFactor.useAuthenticatorCode",
										"Use authenticator app code instead",
									)
								: t(
										"twoFactor.useBackupCode",
										"Lost device? Use recovery backup code",
									)}
						</button>
						<button
							type="button"
							onClick={() => {
								setTwoFactorPending(false);
								setTempToken(null);
								setOtpCode("");
								setBackupCode("");
								setError("");
							}}
							className="text-[hsl(var(--muted-foreground))] hover:text-[hsl(var(--foreground))] hover:underline flex items-center gap-1 text-xs pt-1"
						>
							← {t("auth.backToLogin", "Back to username and password")}
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

				<div className="relative my-4">
					<div className="absolute inset-0 flex items-center">
						<span className="w-full border-t border-[hsl(var(--border))]" />
					</div>
					<div className="relative flex justify-center text-xs uppercase">
						<span className="bg-[hsl(var(--card))] px-2 text-[hsl(var(--muted-foreground))]">
							{t("auth.or") || "Or"}
						</span>
					</div>
				</div>

				<div className="flex justify-center w-full my-2">
					<GoogleLogin
						onSuccess={handleGoogleSuccess}
						onError={() => {
							toast.error("Google Login Failed");
						}}
					/>
				</div>

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
