// pwa/screens/ResetPasswordScreen.tsx

import { AlertCircle, CheckCircle2, Loader2 } from "lucide-react";
import type React from "react";
import { useState } from "react";
import { toast } from "react-hot-toast";
import { useTranslation } from "react-i18next";
import { Input } from "../components/ui/Input";

interface ResetPasswordScreenProps {
	token: string;
	onComplete: () => void;
}

const ResetPasswordScreen: React.FC<ResetPasswordScreenProps> = ({
	token,
	onComplete,
}) => {
	const [password, setPassword] = useState("");
	const [confirmPassword, setConfirmPassword] = useState("");
	const [loading, setLoading] = useState(false);
	const [success, setSuccess] = useState(false);
	const [error, setError] = useState<string | null>(null);
	const { t } = useTranslation("pwa-common");

	const handleSubmit = async (e: React.FormEvent) => {
		e.preventDefault();
		setError(null);

		if (password !== confirmPassword) {
			setError(t("auth.passwordsDoNotMatch"));
			return;
		}

		setLoading(true);

		try {
			const response = await fetch("/api/v1/auth/reset-password", {
				method: "POST",
				headers: { "Content-Type": "application/json" },
				body: JSON.stringify({ token, new_password: password }),
			});

			if (response.ok) {
				setSuccess(true);
				toast.success(t("auth.passwordResetSuccess"));
				setTimeout(() => onComplete(), 3000);
			} else {
				const data = await response.json();
				setError(data.error || data.detail || t("auth.invalidResetLink"));
				toast.error(t("auth.invalidResetLink"));
			}
		} catch (err) {
			console.error("Reset password error:", err);
			setError(t("auth.connectionError"));
			toast.error(t("auth.connectionError"));
		} finally {
			setLoading(false);
		}
	};

	if (success) {
		return (
			<div className="flex items-center justify-center min-h-screen bg-[hsl(var(--background))] p-4 text-center">
				<div className="w-full max-w-md p-8 space-y-6 bg-[hsl(var(--card))] rounded-lg shadow-md">
					<div className="mx-auto w-12 h-12 rounded-full bg-green-100 flex items-center justify-center">
						<CheckCircle2 className="h-6 w-6 text-green-600" />
					</div>
					<h2 className="text-2xl font-bold text-[hsl(var(--foreground))]">
						{t("auth.passwordResetSuccess")}
					</h2>
					<p className="text-sm text-[hsl(var(--muted-foreground))]">
						{t("auth.redirecting")}
					</p>
					<button
						onClick={onComplete}
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
				<h2 className="text-2xl font-bold text-center text-[hsl(var(--foreground))]">
					{t("auth.resetPasswordTitle")}
				</h2>
				<p className="text-sm text-center text-[hsl(var(--muted-foreground))]">
					{t("auth.resetPasswordDescription")}
				</p>

				<form onSubmit={handleSubmit} className="space-y-4">
					<div>
						<label
							className="text-sm text-[hsl(var(--muted-foreground))] mb-2 block"
							htmlFor="password"
						>
							{t("auth.newPassword")}
						</label>
						<Input
							id="password"
							type="password"
							placeholder="••••••••"
							value={password}
							onChange={(e) => setPassword(e.target.value)}
							required
							minLength={6}
							className="w-full"
						/>
					</div>

					<div>
						<label
							className="text-sm text-[hsl(var(--muted-foreground))] mb-2 block"
							htmlFor="confirmPassword"
						>
							{t("auth.confirmResetPassword")}
						</label>
						<Input
							id="confirmPassword"
							type="password"
							placeholder="••••••••"
							value={confirmPassword}
							onChange={(e) => setConfirmPassword(e.target.value)}
							required
							minLength={6}
							className="w-full"
						/>
					</div>

					{error && (
						<div className="flex items-center gap-2 p-3 rounded-lg bg-red-50 text-red-600 text-sm">
							<AlertCircle className="h-4 w-4" />
							{error}
						</div>
					)}

					<button
						type="submit"
						disabled={loading}
						className="w-full py-3 rounded-lg border-none text-base font-medium bg-[hsl(var(--primary))] text-[hsl(var(--primary-foreground))] transition hover:opacity-90 disabled:opacity-50 flex items-center justify-center"
					>
						{loading ? (
							<>
								<Loader2 className="mr-2 h-4 w-4 animate-spin" />
								{t("auth.redirecting")}
							</>
						) : (
							t("auth.resetPassword")
						)}
					</button>
				</form>
			</div>
		</div>
	);
};

export default ResetPasswordScreen;
