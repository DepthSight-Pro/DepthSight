// pwa/screens/ConfirmEmailScreen.tsx

import { AlertCircle, CircleCheck, Loader2 } from "lucide-react";
import type React from "react";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { useAuth } from "../contexts/AuthContext";

interface ConfirmEmailScreenProps {
	token: string;
	onComplete: () => void;
}

const ConfirmEmailScreen: React.FC<ConfirmEmailScreenProps> = ({
	token,
	onComplete,
}) => {
	const { t } = useTranslation("pwa-common");
	const { loginWithTokenAndUser } = useAuth();
	const [status, setStatus] = useState<"loading" | "success" | "error">(
		"loading",
	);
	const [message, setMessage] = useState("");

	useEffect(() => {
		const confirmEmail = async () => {
			if (!token) {
				console.error("[ConfirmEmail] No token provided");
				setStatus("error");
				setMessage(t("auth.tokenNotFound"));
				return;
			}

			console.log(
				"[ConfirmEmail] Starting confirmation with token:",
				`${token.substring(0, 10)}...`,
			);

			try {
				const response = await fetch(`/api/v1/auth/confirm-email/${token}`);
				console.log("[ConfirmEmail] Response status:", response.status);

				const data = await response.json();
				console.log("[ConfirmEmail] Response data:", data);

				if (response.ok) {
					console.log("[ConfirmEmail] Success! Token data:", data.token);
					setStatus("success");
					setMessage(t("auth.successMessageDefault"));

					// Save both auth token and user data using AuthContext
					console.log(
						"[ConfirmEmail] Setting auth token and user data via context",
					);
					loginWithTokenAndUser(data.token, data.user);

					// Clear URL and trigger completion after 2 seconds
					setTimeout(() => {
						console.log("[ConfirmEmail] Completing confirmation flow");
						onComplete();
					}, 2000);
				} else {
					console.error("[ConfirmEmail] Confirmation failed:", data.detail);
					setStatus("error");
					setMessage(data.detail || t("auth.errorMessageDefault"));
				}
			} catch (error) {
				console.error("[ConfirmEmail] Error during confirmation:", error);
				setStatus("error");
				setMessage(t("auth.connectionError"));
			}
		};

		confirmEmail();
	}, [token, t, onComplete, loginWithTokenAndUser]);

	return (
		<div className="flex items-center justify-center min-h-screen bg-[hsl(var(--background))] p-4">
			<div className="w-full max-w-md p-8 space-y-6 bg-[hsl(var(--card))] rounded-lg shadow-md">
				<h2 className="text-2xl font-bold text-center text-[hsl(var(--foreground))]">
					{t("auth.emailConfirmation")}
				</h2>

				<div className="flex flex-col items-center justify-center space-y-4">
					{status === "loading" && (
						<>
							<Loader2 className="animate-spin h-12 w-12 text-[hsl(var(--primary))]" />
							<p className="text-center text-[hsl(var(--muted-foreground))]">
								{t("auth.loadingText")}
							</p>
						</>
					)}

					{status === "success" && (
						<>
							<CircleCheck className="h-12 w-12 text-green-500" />
							<p className="text-center text-[hsl(var(--foreground))]">
								{t("auth.successMessageDefault")}
							</p>
							<p className="text-sm text-center text-[hsl(var(--muted-foreground))]">
								{t("auth.redirecting")}
							</p>
						</>
					)}

					{status === "error" && (
						<>
							<AlertCircle className="h-12 w-12 text-[hsl(var(--loss))]" />
							<p className="text-center text-[hsl(var(--loss))]">
								{t("auth.errorTitle")}
							</p>
							<p className="text-sm text-center text-[hsl(var(--muted-foreground))]">
								{message}
							</p>
							<button
								onClick={onComplete}
								className="w-full py-3 rounded-lg border-none text-base font-medium bg-[hsl(var(--primary))] text-[hsl(var(--primary-foreground))] transition hover:opacity-90"
							>
								{t("auth.backToLogin")}
							</button>
						</>
					)}
				</div>
			</div>
		</div>
	);
};

export default ConfirmEmailScreen;
