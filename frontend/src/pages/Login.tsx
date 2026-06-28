// src/pages/Login.tsx

import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation } from "@tanstack/react-query";
import { Loader2 } from "lucide-react";
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
const useLoginMutation = () => {
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


const useGoogleLoginMutation = () => {
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

	const form = useForm<LoginFormValues>({
		resolver: zodResolver(loginSchema(t)),
		defaultValues: { username: "", password: "" },
	});
	const loginMutation = useLoginMutation();
	const googleLoginMutation = useGoogleLoginMutation();

	const onSubmit = (data: LoginFormValues) => {
		const formData = new URLSearchParams();
		formData.append("username", data.username);
		formData.append("password", data.password);
		loginMutation.mutate(formData);
	};

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
		</div>
	);
}
