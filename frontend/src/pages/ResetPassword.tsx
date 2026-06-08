// src/pages/ResetPassword.tsx

import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation } from "@tanstack/react-query";
import { Loader2 } from "lucide-react";
import { useForm } from "react-hook-form";
import { useTranslation } from "react-i18next";
import { useNavigate, useParams } from "react-router-dom";
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

const resetPasswordSchema = (t: (key: string) => string) =>
	z
		.object({
			password: z.string().min(6, t("passwordRequired")),
			confirmPassword: z.string().min(6, t("passwordRequired")),
		})
		.refine((data) => data.password === data.confirmPassword, {
			message: t("passwordMismatch"),
			path: ["confirmPassword"],
		});

type ResetPasswordValues = z.infer<ReturnType<typeof resetPasswordSchema>>;

export default function ResetPasswordPage() {
	const { t } = useTranslation("login");
	const { toast } = useToast();
	const navigate = useNavigate();
	const { token } = useParams<{ token: string }>();

	const form = useForm<ResetPasswordValues>({
		resolver: zodResolver(resetPasswordSchema(t)),
		defaultValues: { password: "", confirmPassword: "" },
	});

	const mutation = useMutation({
		mutationFn: async (data: ResetPasswordValues) => {
			const response = await fetch("/api/v1/auth/reset-password", {
				method: "POST",
				headers: { "Content-Type": "application/json" },
				body: JSON.stringify({
					token,
					new_password: data.password,
				}),
			});

			if (!response.ok) {
				const errorData = await response.json();
				throw new Error(errorData.detail || t("invalidResetLink"));
			}
			return response.json();
		},
		onSuccess: () => {
			toast({
				title: t("resetPassword"),
				description: t("passwordResetSuccess"),
			});
			navigate("/login");
		},
		onError: (error: Error) => {
			toast({
				variant: "destructive",
				title: t("toastFailureTitle"),
				description: error.message,
			});
		},
	});

	const onSubmit = (data: ResetPasswordValues) => {
		mutation.mutate(data);
	};

	if (!token) {
		return (
			<div className="fixed inset-0 flex items-center justify-center bg-background z-50">
				<Card className="w-full max-w-sm">
					<CardHeader>
						<CardTitle className="text-destructive">
							{t("toastFailureTitle")}
						</CardTitle>
						<CardDescription>{t("invalidResetLink")}</CardDescription>
					</CardHeader>
					<CardContent>
						<Button asChild className="w-full">
							<a href="/login">{t("button")}</a>
						</Button>
					</CardContent>
				</Card>
			</div>
		);
	}

	return (
		<div className="fixed inset-0 flex items-center justify-center bg-background z-50">
			<Card className="w-full max-w-sm">
				<CardHeader>
					<CardTitle className="text-2xl">{t("resetPasswordTitle")}</CardTitle>
					<CardDescription>{t("resetPasswordDescription")}</CardDescription>
				</CardHeader>
				<CardContent>
					<Form {...form}>
						<form onSubmit={form.handleSubmit(onSubmit)} className="space-y-4">
							<FormField
								control={form.control}
								name="password"
								render={({ field }) => (
									<FormItem>
										<FormLabel>{t("newPassword")}</FormLabel>
										<FormControl>
											<Input
												type="password"
												placeholder="••••••••"
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
										<FormLabel>{t("confirmPassword")}</FormLabel>
										<FormControl>
											<Input
												type="password"
												placeholder="••••••••"
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
								disabled={mutation.isPending}
							>
								{mutation.isPending ? (
									<Loader2 className="mr-2 h-4 w-4 animate-spin" />
								) : (
									t("resetPassword")
								)}
							</Button>
						</form>
					</Form>
				</CardContent>
			</Card>
		</div>
	);
}
