// pwa/screens/ForgotPasswordScreen.tsx

import { ArrowLeft, Loader2, Mail } from "lucide-react";
import type React from "react";
import { useState } from "react";
import { toast } from "react-hot-toast";
import { useTranslation } from "react-i18next";
import { Input } from "../components/ui/Input";

interface ForgotPasswordScreenProps {
	onBack: () => void;
}

const ForgotPasswordScreen: React.FC<ForgotPasswordScreenProps> = ({
	onBack,
}) => {
	const [email, setEmail] = useState("");
	const [loading, setLoading] = useState(false);
	const [success, setSuccess] = useState(false);
	const { t } = useTranslation("pwa-common");

	const handleSubmit = async (e: React.FormEvent) => {
		e.preventDefault();
		setLoading(true);

		try {
			const response = await fetch("/api/v1/auth/forgot-password", {
				method: "POST",
				headers: { "Content-Type": "application/json" },
				body: JSON.stringify({ email, source: "pwa" }),
			});

			if (response.ok) {
				setSuccess(true);
				toast.success(t("auth.resetLinkSent"));
			} else {
				const data = await response.json();
				toast.error(
					data.detail ||
						t("common.error", { message: "Failed to send reset link" }),
				);
			}
		} catch (err) {
			console.error("Forgot password error:", err);
			toast.error(t("auth.connectionError"));
		} finally {
			setLoading(false);
		}
	};

	if (success) {
		return (
			<div className="flex items-center justify-center min-h-screen bg-[hsl(var(--background))] p-4">
				<div className="w-full max-w-md p-8 space-y-6 bg-[hsl(var(--card))] rounded-lg shadow-md text-center">
					<div className="mx-auto w-12 h-12 rounded-full bg-green-100 flex items-center justify-center">
						<Mail className="h-6 w-6 text-green-600" />
					</div>
					<h2 className="text-2xl font-bold text-[hsl(var(--foreground))]">
						{t("auth.forgotPasswordTitle")}
					</h2>
					<p className="text-sm text-[hsl(var(--muted-foreground))]">
						{t("auth.resetLinkSent")}
					</p>
					<button
						onClick={onBack}
						className="w-full py-3 rounded-lg border-none text-base font-medium bg-[hsl(var(--primary))] text-[hsl(var(--primary-foreground))] transition hover:opacity-90"
					>
						{t("auth.backToLogin")}
					</button>
				</div>
			</div>
		);
	}

	return (
		<div className="flex items-center justify-center min-h-screen bg-[hsl(var(--background))] p-4">
			<div className="w-full max-w-md p-8 space-y-6 bg-[hsl(var(--card))] rounded-lg shadow-md">
				<button
					onClick={onBack}
					className="flex items-center text-sm text-[hsl(var(--muted-foreground))] hover:text-[hsl(var(--foreground))] transition mb-4"
				>
					<ArrowLeft className="h-4 w-4 mr-1" />
					{t("auth.backToLogin")}
				</button>

				<h2 className="text-2xl font-bold text-center text-[hsl(var(--foreground))]">
					{t("auth.forgotPasswordTitle")}
				</h2>
				<p className="text-sm text-center text-[hsl(var(--muted-foreground))]">
					{t("auth.forgotPasswordDescription")}
				</p>

				<form onSubmit={handleSubmit} className="space-y-4">
					<div>
						<label
							className="text-sm text-[hsl(var(--muted-foreground))] mb-2 block"
							htmlFor="email"
						>
							{t("auth.email")}
						</label>
						<Input
							id="email"
							type="email"
							placeholder="email@example.com"
							value={email}
							onChange={(e) => setEmail(e.target.value)}
							required
							className="w-full"
						/>
					</div>

					<button
						type="submit"
						disabled={loading}
						className="w-full py-3 rounded-lg border-none text-base font-medium bg-[hsl(var(--primary))] text-[hsl(var(--primary-foreground))] transition hover:opacity-90 disabled:opacity-50 flex items-center justify-center"
					>
						{loading ? (
							<>
								<Loader2 className="mr-2 h-4 w-4 animate-spin" />
								{t("auth.resendingEmail")}
							</>
						) : (
							t("auth.sendResetLink")
						)}
					</button>
				</form>
			</div>
		</div>
	);
};

export default ForgotPasswordScreen;
