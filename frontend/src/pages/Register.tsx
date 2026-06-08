// src/pages/Register.tsx

import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation } from "@tanstack/react-query";
import { Loader2 } from "lucide-react";
import { useEffect, useState } from "react";
import { useForm } from "react-hook-form";
import { useTranslation } from "react-i18next";
import { Link, useLocation, useNavigate } from "react-router-dom";
import * as z from "zod";
import { Button } from "@/components/ui/button";
import {
	Card,
	CardContent,
	CardDescription,
	CardHeader,
	CardTitle,
} from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import {
	Form,
	FormControl,
	FormField,
	FormItem,
	FormLabel,
	FormMessage,
} from "@/components/ui/form";
import { Input } from "@/components/ui/input";
import { useToast } from "@/components/ui/use-toast";

const registerSchema = (t: (key: string) => string) =>
	z
		.object({
			username: z.string().min(3, t("usernameMinLength")),
			email: z.string().email(t("invalidEmail")),
			password: z.string().min(6, t("passwordMinLength")),
			confirmPassword: z.string(),
			ref_code: z.string().optional(),
		})
		.refine((data) => data.password === data.confirmPassword, {
			message: t("passwordsDoNotMatch"),
			path: ["confirmPassword"],
		});

type RegisterFormValues = z.infer<ReturnType<typeof registerSchema>>;

const useRegisterMutation = (
	setRegistrationSuccess: (success: boolean) => void,
	setResendTimer: (timer: number) => void,
) => {
	const { toast } = useToast();
	const { t } = useTranslation("register");
	const navigate = useNavigate();

	return useMutation({
		mutationFn: async (data: Omit<RegisterFormValues, "confirmPassword">) => {
			const response = await fetch("/api/v1/register", {
				method: "POST",
				headers: { "Content-Type": "application/json" },
				body: JSON.stringify(data),
			});

			if (!response.ok) {
				const errorData = await response.json();
				if (response.status === 409) {
					if (errorData.detail.includes("Username")) {
						throw new Error(t("usernameTaken"));
					} else if (errorData.detail.includes("Email")) {
						throw new Error(t("emailTaken"));
					}
				}
				throw new Error(errorData.detail || t("registrationFailedTitle"));
			}
			return response.json();
		},
		onSuccess: (data) => {
			const requiresConfirmation = data.data.requires_confirmation !== false; // Default to true if missing

			toast({
				title: t("registrationSuccessTitle"),
				description: data.data.message,
			});

			if (requiresConfirmation) {
				setRegistrationSuccess(true);
				setResendTimer(60); // Set the timer immediately after registration
			} else {
				navigate("/login");
			}
			// Clear the referral code after successful use
			localStorage.removeItem("referralCode");
		},
		onError: (error: Error) => {
			toast({
				variant: "destructive",
				title: t("registrationFailedTitle"),
				description: error.message,
			});
		},
	});
};

export default function RegisterPage() {
	const { t } = useTranslation(["register", "common"]);
	const location = useLocation();
	const [refCode, setRefCode] = useState<string | undefined>(undefined);
	const [agreedToTerms, setAgreedToTerms] = useState(false);
	const [registrationSuccess, setRegistrationSuccess] = useState(false);
	const [registeredEmail, setRegisteredEmail] = useState<string>("");
	const [resendTimer, setResendTimer] = useState(0);
	const [isResending, setIsResending] = useState(false);
	const [showRefInput, setShowRefInput] = useState(false);
	const { toast } = useToast();

	useEffect(() => {
		const params = new URLSearchParams(location.search);
		const refFromUrl = params.get("ref");
		const savedRef = localStorage.getItem("referralCode");

		if (refFromUrl) {
			setRefCode(refFromUrl);
		} else if (savedRef) {
			setRefCode(savedRef);
		}
	}, [location]);

	const form = useForm<RegisterFormValues>({
		resolver: zodResolver(registerSchema(t)),
		defaultValues: {
			username: "",
			email: "",
			password: "",
			confirmPassword: "",
			ref_code: refCode,
		},
	});

	useEffect(() => {
		if (refCode) {
			form.setValue("ref_code", refCode);
		}
	}, [refCode, form]);

	const registerMutation = useRegisterMutation(
		setRegistrationSuccess,
		setResendTimer,
	);

	const onSubmit = (data: RegisterFormValues) => {
		const submissionData = { ...data };
		delete (submissionData as Partial<RegisterFormValues>).confirmPassword;
		setRegisteredEmail(data.email);
		registerMutation.mutate(submissionData);
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

			const data = await response.json();

			if (response.ok) {
				toast({
					title: t("resendSuccessTitle"),
					description: t("resendSuccessDescription"),
				});
				setResendTimer(60); // 1 minute
			} else {
				toast({
					variant: "destructive",
					title: t("resendFailedTitle"),
					description: data.detail || t("resendFailedDescription"),
				});
			}
		} catch {
			toast({
				variant: "destructive",
				title: t("resendFailedTitle"),
				description: t("resendFailedDescription"),
			});
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

	const isSubmitDisabled = registerMutation.isPending || !agreedToTerms;

	if (registrationSuccess) {
		return (
			<div className="fixed inset-0 flex items-center justify-center bg-background z-50">
				<Card className="w-full max-w-sm">
					<CardHeader>
						<CardTitle className="text-2xl">
							{t("registrationSuccessTitle")}
						</CardTitle>
						<CardDescription>{t("confirmEmailPrompt")}</CardDescription>
					</CardHeader>
					<CardContent className="text-center space-y-4">
						<p className="text-sm text-muted-foreground">
							{t("confirmEmailInstructions")}
						</p>

						<div className="space-y-2">
							<Button
								variant="outline"
								className="w-full"
								onClick={handleResendEmail}
								disabled={resendTimer > 0 || isResending}
							>
								{isResending ? (
									<>
										<Loader2 className="mr-2 h-4 w-4 animate-spin" />
										{t("resendingEmail")}
									</>
								) : resendTimer > 0 ? (
									t("resendEmailTimer", { seconds: resendTimer })
								) : (
									t("resendEmail")
								)}
							</Button>

							<Button asChild className="w-full">
								<Link to="/login">{t("backToLogin")}</Link>
							</Button>
						</div>
					</CardContent>
				</Card>
			</div>
		);
	}

	return (
		<div className="fixed inset-0 flex items-center justify-center bg-background z-50">
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
								name="email"
								render={({ field }) => (
									<FormItem>
										<FormLabel>{t("emailLabel")}</FormLabel>
										<FormControl>
											<Input
												type="email"
												placeholder={t("emailPlaceholder")}
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
							<FormField
								control={form.control}
								name="confirmPassword"
								render={({ field }) => (
									<FormItem>
										<FormLabel>{t("confirmPasswordLabel")}</FormLabel>
										<FormControl>
											<Input
												type="password"
												placeholder={t("confirmPasswordPlaceholder")}
												{...field}
											/>
										</FormControl>
										<FormMessage />
									</FormItem>
								)}
							/>

							{!refCode ? (
								!showRefInput ? (
									<div className="flex justify-center">
										<button
											type="button"
											onClick={() => setShowRefInput(true)}
											className="text-xs text-muted-foreground hover:text-primary underline-offset-4 hover:underline transition-colors"
										>
											{t("haveReferralCode", "Have a referral code?")}
										</button>
									</div>
								) : (
									<FormField
										control={form.control}
										name="ref_code"
										render={({ field }) => (
											<FormItem>
												<FormLabel>{t("referralCodeLabel")}</FormLabel>
												<FormControl>
													<Input
														placeholder={t("referralCodePlaceholder")}
														{...field}
													/>
												</FormControl>
												<FormMessage />
											</FormItem>
										)}
									/>
								)
							) : (
								<div className="flex items-center justify-center space-x-2 py-1 rounded-md bg-primary/5 border border-primary/10">
									<span className="text-[10px] uppercase tracking-wider font-semibold text-primary/70">
										{t("referralApplied", "Referral code applied")}
									</span>
									<span className="text-xs font-mono font-bold text-primary">
										{refCode}
									</span>
								</div>
							)}

							<div className="flex items-start space-x-2 pt-2">
								<Checkbox
									id="terms"
									checked={agreedToTerms}
									onCheckedChange={(checked) =>
										setAgreedToTerms(Boolean(checked))
									}
									aria-label="Agree to terms and conditions"
								/>
								<label
									htmlFor="terms"
									className="text-sm text-muted-foreground"
								>
									{t("iAgreeToThe")}{" "}
									<a
										href={`${import.meta.env.VITE_APP_URL || "https://depthsight.pro"}/terms-of-service`}
										target="_blank"
										rel="noopener noreferrer"
										className="underline hover:text-primary"
									>
										{t("common:termsOfService")}
									</a>{" "}
									{t("and")}{" "}
									<a
										href={`${import.meta.env.VITE_APP_URL || "https://depthsight.pro"}/privacy-policy`}
										target="_blank"
										rel="noopener noreferrer"
										className="underline hover:text-primary"
									>
										{t("common:privacyPolicy")}
									</a>
									.
								</label>
							</div>
							<Button
								type="submit"
								className="w-full"
								disabled={isSubmitDisabled}
							>
								{registerMutation.isPending ? (
									<Loader2 className="mr-2 h-4 w-4 animate-spin" />
								) : (
									t("button")
								)}
							</Button>
						</form>
					</Form>
					<div className="mt-4 text-center text-sm">
						{t("alreadyHaveAccount")}{" "}
						<Link to="/login" className="underline">
							{t("loginLink")}
						</Link>
					</div>
				</CardContent>
			</Card>
		</div>
	);
}
