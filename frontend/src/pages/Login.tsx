// src/pages/Login.tsx

import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation } from "@tanstack/react-query";
import { ArrowLeft, Loader2, ShieldCheck } from "lucide-react";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import * as z from "zod";
import { Button } from "@/components/ui/button";
import {
	Card,
	CardContent,
	CardDescription,
	CardHeader,
	CardTitle,
} from "@/components/ui/card";
import {
	Form,
	FormControl,
	FormField,
	FormItem,
	FormLabel,
	FormMessage,
} from "@/components/ui/form";
import { Input } from "@/components/ui/input";
import {
	InputOTP,
	InputOTPGroup,
	InputOTPSlot,
} from "@/components/ui/input-otp";
import { Label } from "@/components/ui/label";
import { useToast } from "@/components/ui/use-toast";
import { useAuth } from "@/context/AuthContext";
import { GoogleLogin } from "@react-oauth/google";

// Validation schema for the login form
const loginSchema = (t: (key: string) => string) =>
	z.object({
		username: z.string().min(1, t("usernameRequired")),
		password: z.string().min(1, t("passwordRequired")),
	});

type LoginFormValues = z.infer<ReturnType<typeof loginSchema>>;

// Hook for the login API request
const useLoginMutation = (onRequire2FA?: (tempToken: string) => void) => {
	const { login } = useAuth();
	const { toast } = useToast();
	const { t } = useTranslation("login");

	return useMutation({
		mutationFn: async (data: URLSearchParams) => {
			const response = await fetch("/api/v1/token", {
				method: "POST",
				headers: { "Content-Type": "application/x-www-form-urlencoded" },
				body: data.toString(),
			});

			if (!response.ok) {
				const errorData = await response.json();
				throw new Error(errorData.detail || t("toastFailureTitle"));
			}
			return response.json();
		},
		onSuccess: async (data) => {
			if (data.requires_2fa && data.temp_token) {
				onRequire2FA?.(data.temp_token);
				return;
			}
			await login(data);
			toast({ title: t("cardTitle"), description: t("toastSuccess") });
		},
		onError: (error: Error) => {
			toast({
				variant: "destructive",
				title: t("toastFailureTitle"),
				description: error.message,
			});
		},
	});
};

const useGoogleLoginMutation = (onRequire2FA?: (tempToken: string) => void) => {
	const { login } = useAuth();
	const { toast } = useToast();
	const { t } = useTranslation("login");

	return useMutation({
		mutationFn: async (googleToken: string) => {
			const response = await fetch("/api/v1/auth/google", {
				method: "POST",
				headers: { "Content-Type": "application/json" },
				body: JSON.stringify({ token: googleToken }),
			});

			if (!response.ok) {
				const errorData = await response.json();
				throw new Error(errorData.detail || t("toastFailureTitle"));
			}
			return response.json();
		},
		onSuccess: async (data) => {
			if (data.requires_2fa && data.temp_token) {
				onRequire2FA?.(data.temp_token);
				return;
			}
			await login(data);
			toast({ title: t("cardTitle"), description: t("toastSuccess") });
		},
		onError: (error: Error) => {
			toast({
				variant: "destructive",
				title: t("toastFailureTitle"),
				description: error.message,
			});
		},
	});
};

const useVerifyTotpLoginMutation = () => {
	const { login } = useAuth();
	const { toast } = useToast();
	const { t } = useTranslation("login");

	return useMutation({
		mutationFn: async ({
			tempToken,
			code,
		}: { tempToken: string; code: string }) => {
			const response = await fetch("/api/v1/auth/2fa/verify-login", {
				method: "POST",
				headers: { "Content-Type": "application/json" },
				body: JSON.stringify({ tempToken, code }),
			});

			if (!response.ok) {
				const errorData = await response.json();
				throw new Error(
					errorData.detail ||
						t("twoFactorError", "Verification code is invalid or expired."),
				);
			}
			return response.json();
		},
		onSuccess: async (data) => {
			await login(data);
			toast({ title: t("cardTitle"), description: t("toastSuccess") });
		},
		onError: (error: Error) => {
			toast({
				variant: "destructive",
				title: t("toastFailureTitle"),
				description: error.message,
			});
		},
	});
};

export default function LoginPage() {
	const { t } = useTranslation(["login", "common"]);
	const { toast } = useToast();

	// 2FA pending states
	const [twoFactorPending, setTwoFactorPending] = useState(false);
	const [tempToken, setTempToken] = useState<string | null>(null);
	const [otpCode, setOtpCode] = useState("");
	const [useBackupCode, setUseBackupCode] = useState(false);
	const [backupCodeInput, setBackupCodeInput] = useState("");

	const onRequire2FA = (token: string) => {
		setTempToken(token);
		setTwoFactorPending(true);
		setOtpCode("");
		setBackupCodeInput("");
	};

	const form = useForm<LoginFormValues>({
		resolver: zodResolver(loginSchema(t)),
		defaultValues: { username: "", password: "" },
	});

	const loginMutation = useLoginMutation(onRequire2FA);
	const googleLoginMutation = useGoogleLoginMutation(onRequire2FA);
	const verify2faMutation = useVerifyTotpLoginMutation();

	const onSubmit = (data: LoginFormValues) => {
		const formData = new URLSearchParams();
		formData.append("username", data.username);
		formData.append("password", data.password);
		loginMutation.mutate(formData);
	};

	const handleVerify2FA = (directCode?: string) => {
		if (!tempToken) return;
		const codeToSubmit = directCode || (useBackupCode ? backupCodeInput.trim() : otpCode);
		if (!codeToSubmit) return;

		verify2faMutation.mutate({
			tempToken,
			code: codeToSubmit,
		});
	};

	return (
		<div className="fixed inset-0 flex items-center justify-center bg-background z-50">
			{twoFactorPending ? (
				<Card className="w-full max-w-sm border shadow-xl">
					<CardHeader className="text-center pb-3">
						<div className="mx-auto w-12 h-12 rounded-full bg-primary/10 flex items-center justify-center mb-2 border border-primary/20">
							<ShieldCheck className="h-6 w-6 text-primary" />
						</div>
						<CardTitle className="text-2xl font-bold tracking-tight">
							{t("twoFactorTitle", "Two-Factor Authentication")}
						</CardTitle>
						<CardDescription className="text-xs">
							{useBackupCode
								? t(
										"twoFactorBackupDesc",
										"Enter one of your 8-character single-use recovery codes.",
									)
								: t(
										"twoFactorCodeDesc",
										"Enter the 6-digit code from your authenticator app.",
									)}
						</CardDescription>
					</CardHeader>
					<CardContent className="space-y-4">
						{useBackupCode ? (
							<div className="space-y-2">
								<Label htmlFor="backup-code-input" className="text-xs font-medium">
									{t("backupCodeLabel", "Backup Recovery Code")}
								</Label>
								<Input
									id="backup-code-input"
									placeholder="XXXX-XXXX"
									value={backupCodeInput}
									onChange={(e) => setBackupCodeInput(e.target.value)}
									autoComplete="off"
									className="font-mono text-center uppercase tracking-wider text-base"
								/>
							</div>
						) : (
							<div className="space-y-2 flex flex-col items-center py-2">
								<InputOTP
									maxLength={6}
									value={otpCode}
									onChange={(val) => {
										setOtpCode(val);
										if (val.length === 6) {
											handleVerify2FA(val);
										}
									}}
								>
									<InputOTPGroup>
										<InputOTPSlot index={0} />
										<InputOTPSlot index={1} />
										<InputOTPSlot index={2} />
										<InputOTPSlot index={3} />
										<InputOTPSlot index={4} />
										<InputOTPSlot index={5} />
									</InputOTPGroup>
								</InputOTP>
							</div>
						)}

						<Button
							onClick={() => handleVerify2FA()}
							disabled={
								verify2faMutation.isPending ||
								(useBackupCode
									? !backupCodeInput.trim()
									: otpCode.length !== 6)
							}
							className="w-full"
						>
							{verify2faMutation.isPending ? (
								<Loader2 className="mr-2 h-4 w-4 animate-spin" />
							) : (
								t("verifyButton", "Verify & Continue")
							)}
						</Button>

						<div className="flex flex-col space-y-2 text-center text-xs pt-1">
							<button
								type="button"
								onClick={() => {
									setUseBackupCode(!useBackupCode);
									setOtpCode("");
									setBackupCodeInput("");
								}}
								className="text-primary hover:underline transition-colors"
							>
								{useBackupCode
									? t(
											"useAuthenticatorApp",
											"Use authenticator code instead",
										)
									: t(
											"useBackupCode",
											"Lost device? Use backup recovery code",
										)}
							</button>
							<button
								type="button"
								onClick={() => {
									setTwoFactorPending(false);
									setTempToken(null);
									setOtpCode("");
									setBackupCodeInput("");
								}}
								className="text-muted-foreground hover:text-foreground hover:underline flex items-center justify-center gap-1 transition-colors pt-1"
							>
								<ArrowLeft className="h-3 w-3" />
								{t("backToLogin", "Back to username and password")}
							</button>
						</div>
					</CardContent>
				</Card>
			) : (
				<Card className="w-full max-w-sm">
					<CardHeader>
						<CardTitle className="text-2xl">{t("cardTitle")}</CardTitle>
						<CardDescription>{t("cardDescription")}</CardDescription>
					</CardHeader>
					<CardContent>
						<Form {...form}>
							<form onSubmit={form.handleSubmit(onSubmit)} className="space-y-4">
								<FormField
									control={form.control}
									name="username"
									render={({ field }) => (
										<FormItem>
											<FormLabel>{t("usernameLabel")}</FormLabel>
											<FormControl>
												<Input
													placeholder={t("usernamePlaceholder")}
													{...field}
												/>
											</FormControl>
											<FormMessage />
										</FormItem>
									)}
								/>
								<FormField
									control={form.control}
									name="password"
									render={({ field }) => (
										<FormItem>
											<FormLabel>{t("passwordLabel")}</FormLabel>
											<FormControl>
												<Input
													type="password"
													placeholder={t("passwordPlaceholder")}
													{...field}
												/>
											</FormControl>
											<FormMessage />
										</FormItem>
									)}
								/>
								<Button
									type="submit"
									className="w-full"
									disabled={loginMutation.isPending}
								>
									{loginMutation.isPending ? (
										<Loader2 className="mr-2 h-4 w-4 animate-spin" />
									) : (
										t("button")
									)}
								</Button>
								<div className="text-center">
									<Link
										to="/forgot-password"
										className="text-sm text-muted-foreground hover:underline"
									>
										{t("forgotPassword")}
									</Link>
								</div>
							</form>
						</Form>

						<div className="relative my-4">
							<div className="absolute inset-0 flex items-center">
								<span className="w-full border-t" />
							</div>
							<div className="relative flex justify-center text-xs uppercase">
								<span className="bg-background px-2 text-muted-foreground">
									{t("common:or") || "Or"}
								</span>
							</div>
						</div>

						<div className="flex justify-center w-full my-2">
							<GoogleLogin
								onSuccess={(credentialResponse) => {
									if (credentialResponse.credential) {
										googleLoginMutation.mutate(credentialResponse.credential);
									}
								}}
								onError={() => {
									toast({
										variant: "destructive",
										title: t("toastFailureTitle"),
										description: "Google Login Failed",
									});
								}}
							/>
						</div>

						<div className="mt-4 text-center text-sm">
							{t("noAccount")}{" "}
							<Link to="/register" className="underline">
								{t("registerLink")}
							</Link>
						</div>
					</CardContent>
				</Card>
			)}
		</div>
	);
}
