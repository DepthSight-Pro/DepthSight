// src/pages/ForgotPassword.tsx

import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation } from "@tanstack/react-query";
import { ArrowLeft, Loader2 } from "lucide-react";
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

const forgotPasswordSchema = (t: (key: string) => string) =>
	z.object({
		email: z.string().email(t("invalidEmail")),
	});

type ForgotPasswordValues = z.infer<ReturnType<typeof forgotPasswordSchema>>;

export default function ForgotPasswordPage() {
	const { t } = useTranslation("login");
	const { toast } = useToast();

	const form = useForm<ForgotPasswordValues>({
		resolver: zodResolver(forgotPasswordSchema(t)),
		defaultValues: { email: "" },
	});

	const mutation = useMutation({
		mutationFn: async (data: ForgotPasswordValues) => {
			const response = await fetch("/api/v1/auth/forgot-password", {
				method: "POST",
				headers: { "Content-Type": "application/json" },
				body: JSON.stringify({ ...data, source: "desktop" }),
			});

			if (!response.ok) {
				const errorData = await response.json();
				throw new Error(errorData.detail || "Failed to request password reset");
			}
			return response.json();
		},
		onSuccess: () => {
			toast({
				title: t("forgotPasswordTitle"),
				description: t("resetLinkSent"),
			});
		},
		onError: (error: Error) => {
			toast({
				variant: "destructive",
				title: t("toastFailureTitle"),
				description: error.message,
			});
		},
	});

	const onSubmit = (data: ForgotPasswordValues) => {
		mutation.mutate(data);
	};

	return (
		<div className="fixed inset-0 flex items-center justify-center bg-background z-50">
			<Card className="w-full max-w-sm">
				<CardHeader>
					<div className="flex items-center gap-2 mb-2">
						<Link
							to="/login"
							className="text-muted-foreground hover:text-foreground transition-colors"
						>
							<ArrowLeft className="h-4 w-4" />
						</Link>
					</div>
					<CardTitle className="text-2xl">{t("forgotPasswordTitle")}</CardTitle>
					<CardDescription>{t("forgotPasswordDescription")}</CardDescription>
				</CardHeader>
				<CardContent>
					{mutation.isSuccess ? (
						<div className="space-y-4 text-center">
							<p className="text-sm text-muted-foreground">
								{t("resetLinkSent")}
							</p>
							<Button asChild className="w-full">
								<Link to="/login">{t("button")}</Link>
							</Button>
						</div>
					) : (
						<Form {...form}>
							<form
								onSubmit={form.handleSubmit(onSubmit)}
								className="space-y-4"
							>
								<FormField
									control={form.control}
									name="email"
									render={({ field }) => (
										<FormItem>
											<FormLabel>{t("emailLabel")}</FormLabel>
											<FormControl>
												<Input placeholder={t("emailPlaceholder")} {...field} />
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
										t("sendResetLink")
									)}
								</Button>
							</form>
						</Form>
					)}
				</CardContent>
			</Card>
		</div>
	);
}
