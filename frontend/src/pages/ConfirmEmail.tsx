// src/pages/ConfirmEmail.tsx

import { AlertCircle, CircleCheck, Loader } from "lucide-react";
import type React from "react";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useNavigate, useParams } from "react-router-dom";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useAuth } from "@/context/AuthContext";

const ConfirmEmailPage: React.FC = () => {
	const { t } = useTranslation("confirmEmail");
	const { token } = useParams<{ token: string }>();
	const { login } = useAuth();
	const navigate = useNavigate();
	const [status, setStatus] = useState<"loading" | "success" | "error">(
		"loading",
	);
	const [message, setMessage] = useState("");

	useEffect(() => {
		const confirmEmail = async () => {
			if (!token) {
				setStatus("error");
				setMessage(t("tokenNotFound"));
				return;
			}

			try {
				const response = await fetch(`/api/v1/auth/confirm-email/${token}`);
				const data = await response.json();

				if (response.ok) {
					setStatus("success");
					setMessage(t("successMessageDefault"));
					await login(data);
					navigate("/");
				} else {
					setStatus("error");
					setMessage(data.detail || t("errorMessageDefault"));
				}
			} catch {
				setStatus("error");
				setMessage(t("connectionError"));
			}
		};

		confirmEmail();
	}, [token, t, login, navigate]);

	return (
		<div className="flex items-center justify-center min-h-screen">
			<Card className="w-[450px]">
				<CardHeader>
					<CardTitle>{t("cardTitle")}</CardTitle>
				</CardHeader>
				<CardContent>
					{status === "loading" && (
						<div className="flex flex-col items-center justify-center space-y-2">
							<Loader className="animate-spin h-8 w-8 text-primary" />
							<p>{t("loadingText")}</p>
						</div>
					)}
					{status === "success" && (
						<div className="flex flex-col items-center justify-center space-y-2">
							<CircleCheck className="h-8 w-8 text-green-500" />
							<p>{t("successMessageDefault")}</p>
							<p className="text-sm text-muted-foreground">
								{t("redirecting")}
							</p>
						</div>
					)}
					{status === "error" && (
						<Alert variant="destructive">
							<AlertCircle className="h-4 w-4" />
							<AlertTitle>{t("errorTitle")}</AlertTitle>
							<AlertDescription>{message}</AlertDescription>
							<Link
								to="/register"
								className="mt-4 inline-block bg-destructive text-destructive-foreground px-4 py-2 rounded hover:bg-destructive/90"
							>
								{t("backToRegister")}
							</Link>
						</Alert>
					)}
				</CardContent>
			</Card>
		</div>
	);
};

export default ConfirmEmailPage;
