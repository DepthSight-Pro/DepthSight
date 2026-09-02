// pwa/components/SecuritySettingsPwa.tsx

import {
	AlertTriangle,
	Check,
	Copy,
	ExternalLink,
	KeyRound,
	Loader2,
	RefreshCw,
	ShieldAlert,
	ShieldCheck,
	X,
} from "lucide-react";
import type React from "react";
import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { toast } from "react-hot-toast";
import { useTranslation } from "react-i18next";
import { api } from "../services/api";
import type { TotpSetupResponse, TotpStatusResponse } from "../types";
import {
	Card,
	CardContent,
	CardDescription,
	CardHeader,
	CardTitle,
} from "./Card";
import { Input } from "./ui/Input";

export const SecuritySettingsPwa: React.FC = () => {
	const { t } = useTranslation("pwa-common");

	const [statusData, setStatusData] = useState<TotpStatusResponse | null>(null);
	const [loadingStatus, setLoadingStatus] = useState(true);

	// Setup state
	const [isSetupOpen, setIsSetupOpen] = useState(false);
	const [setupData, setSetupData] = useState<TotpSetupResponse | null>(null);
	const [confirmCode, setConfirmCode] = useState("");
	const [actionLoading, setActionLoading] = useState(false);
	const [copiedKey, setCopiedKey] = useState(false);

	// Backup codes modal
	const [newBackupCodes, setNewBackupCodes] = useState<string[] | null>(null);
	const [isBackupCodesOpen, setIsBackupCodesOpen] = useState(false);
	const [copiedCodes, setCopiedCodes] = useState(false);

	// Disable state
	const [isDisableOpen, setIsDisableOpen] = useState(false);
	const [disableCode, setDisableCode] = useState("");
	const [disablePassword, setDisablePassword] = useState("");

	// Regenerate state
	const [isRegenerateOpen, setIsRegenerateOpen] = useState(false);
	const [regenCode, setRegenCode] = useState("");

	const fetchStatus = async () => {
		try {
			setLoadingStatus(true);
			const data = await api.getTotpStatus();
			setStatusData(data);
		} catch (err) {
			console.error("Failed to load 2FA status", err);
		} finally {
			setLoadingStatus(false);
		}
	};

	useEffect(() => {
		fetchStatus();
	}, []);

	// 1. Start Setup
	const handleStartSetup = async () => {
		try {
			setIsSetupOpen(true);
			setConfirmCode("");
			setSetupData(null);
			setActionLoading(true);
			const data = await api.setupTotp();
			const realData = (data as any)?.data || data;
			if (!realData || !realData.secret) {
				throw new Error("Failed to generate 2FA secret from server");
			}
			setSetupData(realData);
		} catch (err: any) {
			setIsSetupOpen(false);
			toast.error(err.message || t("twoFactor.setupError", "Failed to start 2FA setup"));
		} finally {
			setActionLoading(false);
		}
	};

	// 2. Confirm Setup
	const handleConfirmSetup = async (e: React.FormEvent) => {
		e.preventDefault();
		const secret = setupData?.secret;
		if (!secret || confirmCode.length !== 6) return;

		try {
			setActionLoading(true);
			const res = await api.confirmTotp({
				secret,
				code: confirmCode,
			});
			const realRes = (res as any)?.data || res;
			setIsSetupOpen(false);
			setSetupData(null);
			setConfirmCode("");

			const backupCodes =
				realRes?.backupCodes || (realRes as any)?.backup_codes;
			if (backupCodes?.length) {
				setNewBackupCodes(backupCodes);
				setIsBackupCodesOpen(true);
			}

			toast.success(t("twoFactor.enabledSuccess", "2FA successfully enabled!"));
			fetchStatus();
		} catch (err: any) {
			toast.error(err.message || t("twoFactor.invalidCode", "Invalid verification code"));
		} finally {
			setActionLoading(false);
		}
	};

	// 3. Disable 2FA
	const handleDisable = async (e: React.FormEvent) => {
		e.preventDefault();
		if (!disableCode && !disablePassword) return;

		try {
			setActionLoading(true);
			await api.disableTotp({
				code: disableCode.trim() || undefined,
				password: disablePassword || undefined,
			});
			setIsDisableOpen(false);
			setDisableCode("");
			setDisablePassword("");

			toast.success(t("twoFactor.disabledSuccess", "2FA has been disabled"));
			fetchStatus();
		} catch (err: any) {
			toast.error(err.message || t("twoFactor.disableError", "Failed to disable 2FA"));
		} finally {
			setActionLoading(false);
		}
	};

	// 4. Regenerate Backup Codes
	const handleRegenerateCodes = async (e: React.FormEvent) => {
		e.preventDefault();
		if (regenCode.length !== 6) return;

		try {
			setActionLoading(true);
			const res = await api.regenerateBackupCodes({ code: regenCode });
			setIsRegenerateOpen(false);
			setRegenCode("");

			if (res.backupCodes?.length) {
				setNewBackupCodes(res.backupCodes);
				setIsBackupCodesOpen(true);
			}

			toast.success(
				t("twoFactor.regenSuccess", "New recovery codes generated successfully"),
			);
			fetchStatus();
		} catch (err: any) {
			toast.error(
				err.message || t("twoFactor.invalidCode", "Invalid verification code"),
			);
		} finally {
			setActionLoading(false);
		}
	};

	const copyTextToClipboard = async (text: string): Promise<boolean> => {
		if (!text) return false;
		try {
			if (navigator.clipboard && window.isSecureContext) {
				await navigator.clipboard.writeText(text);
				return true;
			}
		} catch (err) {
			console.warn("navigator.clipboard failed, using fallback", err);
		}

		try {
			const textArea = document.createElement("textarea");
			textArea.value = text;
			textArea.style.position = "fixed";
			textArea.style.left = "-999999px";
			textArea.style.top = "-999999px";
			document.body.appendChild(textArea);
			textArea.focus();
			textArea.select();
			const successful = document.execCommand("copy");
			textArea.remove();
			return successful;
		} catch (fallbackErr) {
			console.error("Fallback clipboard copy failed", fallbackErr);
			return false;
		}
	};

	const copySecret = async () => {
		const key =
			setupData?.manualEntryKey ||
			(setupData as any)?.manual_entry_key ||
			setupData?.secret;
		if (!key) return;
		const ok = await copyTextToClipboard(key);
		if (ok) {
			setCopiedKey(true);
			toast.success(t("twoFactor.keyCopied", "Secret key copied"));
			setTimeout(() => setCopiedKey(false), 2500);
		} else {
			toast.error(t("twoFactor.copyFailed", "Failed to copy key"));
		}
	};

	const copyAllBackupCodes = async () => {
		if (!newBackupCodes) return;
		const ok = await copyTextToClipboard(newBackupCodes.join("\n"));
		if (ok) {
			setCopiedCodes(true);
			toast.success(t("twoFactor.codesCopied", "All backup codes copied!"));
			setTimeout(() => setCopiedCodes(false), 2500);
		}
	};

	const isTotpEnabled = statusData?.isTotpEnabled ?? false;
	const remainingBackupCodes = statusData?.remainingBackupCodesCount ?? 0;

	return (
		<div className="space-y-4">
			<Card>
				<CardHeader>
					<div className="flex items-center justify-between">
						<div className="flex items-center gap-2">
							<div className="w-9 h-9 rounded-xl bg-[hsl(var(--primary))]/10 flex items-center justify-center text-[hsl(var(--primary))] shrink-0">
								<KeyRound className="w-5 h-5" />
							</div>
							<div>
								<CardTitle>{t("twoFactor.cardTitle", "Two-Factor Auth (2FA)")}</CardTitle>
								<CardDescription className="text-xs">
									{t("twoFactor.pwaCardSub", "Time-based OTP protection (Google Authenticator)")}
								</CardDescription>
							</div>
						</div>
						<div>
							{loadingStatus ? (
								<Loader2 className="w-5 h-5 animate-spin text-[hsl(var(--muted-foreground))]" />
							) : isTotpEnabled ? (
								<span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-semibold bg-emerald-500/15 text-emerald-500 border border-emerald-500/30">
									<ShieldCheck className="w-3.5 h-3.5" />
									{t("twoFactor.badgeEnabled", "Active")}
								</span>
							) : (
								<span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-semibold bg-amber-500/15 text-amber-500 border border-amber-500/30">
									<ShieldAlert className="w-3.5 h-3.5" />
									{t("twoFactor.badgeDisabled", "Not Enabled")}
								</span>
							)}
						</div>
					</div>
				</CardHeader>
				<CardContent className="space-y-4 pt-2">
					{isTotpEnabled ? (
						<div className="space-y-3">
							<div className="rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--muted))]/40 p-3 space-y-1.5">
								<div className="flex items-center justify-between text-xs">
									<span className="text-[hsl(var(--muted-foreground))] font-medium">
										{t("twoFactor.recoveryCodesCountLabel", "Available Backup Codes:")}
									</span>
									<span
										className={`font-semibold px-2 py-0.5 rounded ${
											remainingBackupCodes > 2
												? "bg-[hsl(var(--primary))]/10 text-[hsl(var(--primary))]"
												: "bg-[hsl(var(--loss))]/15 text-[hsl(var(--loss))]"
										}`}
									>
										{remainingBackupCodes} {t("twoFactor.remaining", "remaining")}
									</span>
								</div>
								{remainingBackupCodes <= 2 && (
									<p className="text-xs text-amber-500 flex items-center gap-1">
										<AlertTriangle className="w-3.5 h-3.5 shrink-0" />
										{t(
											"twoFactor.lowCodesWarning",
											"Low backup codes remaining. Please regenerate.",
										)}
									</p>
								)}
							</div>

							<div className="flex gap-2 pt-1">
								<button
									type="button"
									onClick={() => setIsRegenerateOpen(true)}
									className="flex-1 py-2.5 px-3 rounded-xl border border-[hsl(var(--border))] hover:bg-[hsl(var(--muted))] text-xs font-medium text-[hsl(var(--foreground))] transition flex items-center justify-center gap-1.5"
								>
									<RefreshCw className="w-3.5 h-3.5" />
									{t("twoFactor.btnRegenerateCodes", "Regenerate Codes")}
								</button>
								<button
									type="button"
									onClick={() => setIsDisableOpen(true)}
									className="py-2.5 px-4 rounded-xl bg-[hsl(var(--destructive))]/15 hover:bg-[hsl(var(--destructive))]/25 text-xs font-medium text-[hsl(var(--destructive))] transition"
								>
									{t("twoFactor.btnDisable", "Disable 2FA")}
								</button>
							</div>
						</div>
					) : (
						<div className="space-y-3">
							<p className="text-xs text-[hsl(var(--muted-foreground))] leading-relaxed">
								{t(
									"twoFactor.cardDescription",
									"Protect your exchange keys and trading bots with an extra verification code when logging in.",
								)}
							</p>

							<button
								type="button"
								onClick={handleStartSetup}
								disabled={actionLoading}
								className="w-full py-3 px-4 bg-[hsl(var(--primary))] hover:opacity-90 disabled:opacity-50 text-[hsl(var(--primary-foreground))] font-semibold rounded-xl text-sm transition shadow-md flex items-center justify-center gap-2"
							>
								{actionLoading ? (
									<Loader2 className="w-4 h-4 animate-spin" />
								) : (
									<ShieldCheck className="w-4 h-4" />
								)}
								{t("twoFactor.btnEnable", "Enable 2FA Authentication")}
							</button>
						</div>
					)}
				</CardContent>
			</Card>

			{/* Setup Modal */}
			{typeof document !== "undefined" && isSetupOpen && createPortal(
				<div className="fixed inset-0 z-[9999] flex items-center justify-center p-4 bg-black/75 overflow-y-auto">
					<div
						className="fixed inset-0"
						onClick={() => setIsSetupOpen(false)}
					/>
					<div className="relative z-10 w-full max-w-sm rounded-3xl bg-[hsl(var(--card))] p-5 shadow-2xl border border-[hsl(var(--border))] space-y-4 max-h-[85dvh] overflow-y-auto my-auto">
						<div className="flex items-center justify-between">
							<div className="flex items-center gap-2 text-sm font-bold text-[hsl(var(--foreground))]">
								<ShieldCheck className="w-5 h-5 text-[hsl(var(--primary))]" />
								{t("twoFactor.modalSetupTitle", "Set Up 2FA")}
							</div>
							<button
								type="button"
								onClick={() => setIsSetupOpen(false)}
								className="text-[hsl(var(--muted-foreground))] hover:text-[hsl(var(--foreground))]"
							>
								<X className="w-5 h-5" />
							</button>
						</div>

						{!setupData || actionLoading ? (
							<div className="flex flex-col items-center justify-center py-12 space-y-3">
								<Loader2 className="w-8 h-8 animate-spin text-[hsl(var(--primary))]" />
								<p className="text-xs text-[hsl(var(--muted-foreground))]">
									{t("twoFactor.generatingSetup", "Generating QR code...")}
								</p>
							</div>
						) : (
							<form onSubmit={handleConfirmSetup} className="space-y-4">
								<p className="text-xs text-[hsl(var(--muted-foreground))] text-center">
									{t(
										"twoFactor.modalSetupDesc",
										"Scan QR code in Google Authenticator or Aegis, then enter the 6-digit code.",
									)}
								</p>

								{/* QR Code */}
								<div className="bg-white p-3 rounded-2xl w-44 h-44 mx-auto flex items-center justify-center shadow-inner border">
									<img
										src={setupData.qrCode || (setupData as any).qr_code}
										alt="2FA QR Code"
										className="w-full h-full object-contain"
									/>
								</div>

								{/* Direct App Link (Google Authenticator / Aegis deep link) */}
								{(setupData.otpauthUrl || (setupData as any).otpauth_url) && (
									<a
										href={setupData.otpauthUrl || (setupData as any).otpauth_url}
										className="w-full py-2.5 px-3 rounded-xl bg-[hsl(var(--secondary))] hover:bg-[hsl(var(--muted))] text-xs font-semibold text-[hsl(var(--foreground))] border border-[hsl(var(--border))] flex items-center justify-center gap-2 transition"
									>
										<ExternalLink className="w-4 h-4 text-[hsl(var(--primary))]" />
										{t("twoFactor.btnOpenInApp", "Open in Authenticator app")}
									</a>
								)}

								{/* Manual Key with Dedicated Copy Button */}
								<div className="space-y-2 rounded-2xl border border-[hsl(var(--border))] bg-[hsl(var(--muted))]/40 p-3">
									<div className="flex items-center justify-between text-[11px] text-[hsl(var(--muted-foreground))] font-medium">
										<span>{t("twoFactor.manualKeyLabel", "Can't scan? Copy key:")}</span>
										<span className="text-[10px] text-[hsl(var(--muted-foreground))]">
											{t("twoFactor.clickToCopy", "Click to copy")}
										</span>
									</div>

									<div
										onClick={copySecret}
										className="bg-[hsl(var(--card))] border border-[hsl(var(--border))] rounded-xl p-2.5 flex items-center justify-between gap-2 cursor-pointer active:scale-[0.99] transition shadow-xs"
										title={t("twoFactor.clickToCopy", "Click to copy")}
									>
										<code className="text-xs font-mono font-bold tracking-wider select-all break-all text-[hsl(var(--foreground))]">
											{setupData.manualEntryKey ||
												(setupData as any).manual_entry_key ||
												setupData.secret}
										</code>
									</div>

									<button
										type="button"
										onClick={copySecret}
										className={`w-full py-2.5 px-3 rounded-xl text-xs font-semibold transition flex items-center justify-center gap-1.5 shadow-xs ${
											copiedKey
												? "bg-emerald-600 text-white"
												: "bg-[hsl(var(--primary))] hover:opacity-90 text-[hsl(var(--primary-foreground))]"
										}`}
									>
										{copiedKey ? (
											<>
												<Check className="w-4 h-4 text-white" />
												<span>{t("twoFactor.keyCopied", "Secret key copied!")}</span>
											</>
										) : (
											<>
												<Copy className="w-4 h-4" />
												<span>{t("twoFactor.btnCopyKeyFull", "Copy Secret Key")}</span>
											</>
										)}
									</button>
								</div>

								{/* Code Input */}
								<div className="space-y-1.5 pt-1">
									<label className="text-xs text-[hsl(var(--muted-foreground))] block text-center font-medium">
										{t("twoFactor.enterCodeLabel", "Enter 6-digit code")}
									</label>
									<Input
										type="text"
										inputMode="numeric"
										pattern="[0-9]*"
										maxLength={6}
										value={confirmCode}
										onChange={(e) =>
											setConfirmCode(e.target.value.replace(/\D/g, "").slice(0, 6))
										}
										placeholder="••••••"
										className="text-center font-mono text-xl tracking-[0.3em] h-12"
									/>
								</div>

								<div className="flex gap-2 pt-2">
									<button
										type="button"
										onClick={() => setIsSetupOpen(false)}
										className="flex-1 py-2.5 px-3 rounded-xl border border-[hsl(var(--border))] text-xs font-medium text-[hsl(var(--muted-foreground))]"
									>
										{t("profile.cancel", "Cancel")}
									</button>
									<button
										type="submit"
										disabled={actionLoading || confirmCode.length !== 6 || !setupData}
										className="flex-1 py-2.5 px-3 rounded-xl bg-[hsl(var(--primary))] text-[hsl(var(--primary-foreground))] text-xs font-semibold hover:opacity-90 disabled:opacity-50 flex items-center justify-center gap-1.5"
									>
										{actionLoading && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
										{t("twoFactor.btnConfirmAndEnable", "Confirm & Enable")}
									</button>
								</div>
							</form>
						)}
					</div>
				</div>,
				document.body
			)}

			{/* Backup Codes Display Modal */}
			{typeof document !== "undefined" && isBackupCodesOpen && createPortal(
				<div className="fixed inset-0 z-[9999] flex items-center justify-center p-4 bg-black/75 overflow-y-auto">
					<div className="fixed inset-0" />
					<div className="relative z-10 w-full max-w-sm rounded-3xl bg-[hsl(var(--card))] p-5 shadow-2xl border border-[hsl(var(--border))] space-y-4 max-h-[85dvh] overflow-y-auto my-auto">
						<div className="text-center space-y-1">
							<div className="w-10 h-10 rounded-full bg-emerald-500/15 text-emerald-500 flex items-center justify-center mx-auto mb-2">
								<Check className="w-5 h-5" />
							</div>
							<h3 className="text-base font-bold text-[hsl(var(--foreground))]">
								{t("twoFactor.modalBackupCodesTitle", "Save Your Recovery Codes")}
							</h3>
							<p className="text-xs text-[hsl(var(--muted-foreground))]">
								{t(
									"twoFactor.modalBackupCodesDesc",
									"If you lose your device, these one-time codes are the ONLY way to recover your account.",
								)}
							</p>
						</div>

						<div className="p-3 bg-[hsl(var(--loss))]/10 border border-[hsl(var(--loss))]/25 rounded-2xl text-[11px] text-[hsl(var(--loss))] flex items-start gap-2">
							<AlertTriangle className="w-4 h-4 shrink-0 mt-0.5" />
							<span>
								{t(
									"twoFactor.backupWarningText",
									"These codes are shown only ONCE. Store them in a secure password manager.",
								)}
							</span>
						</div>

						{newBackupCodes && (
							<div className="grid grid-cols-2 gap-2 p-3 bg-[hsl(var(--muted))]/50 rounded-2xl font-mono text-xs font-semibold text-center select-all">
								{newBackupCodes.map((code, idx) => (
									<div
										key={idx}
										className="bg-[hsl(var(--card))] py-2 px-1 rounded-xl border border-[hsl(var(--border))] shadow-xs"
									>
										{code}
									</div>
								))}
							</div>
						)}

						<div className="flex gap-2 pt-1">
							<button
								type="button"
								onClick={copyAllBackupCodes}
								className="flex-1 py-2.5 px-3 rounded-xl border border-[hsl(var(--border))] text-xs font-medium text-[hsl(var(--foreground))] hover:bg-[hsl(var(--muted))] flex items-center justify-center gap-1.5"
							>
								{copiedCodes ? (
									<Check className="w-3.5 h-3.5 text-emerald-500" />
								) : (
									<Copy className="w-3.5 h-3.5" />
								)}
								{copiedCodes
									? t("twoFactor.copied", "Copied!")
									: t("twoFactor.btnCopyCodes", "Copy All Codes")}
							</button>
							<button
								type="button"
								onClick={() => setIsBackupCodesOpen(false)}
								className="flex-1 py-2.5 px-3 rounded-xl bg-[hsl(var(--primary))] text-[hsl(var(--primary-foreground))] text-xs font-semibold hover:opacity-90"
							>
								{t("twoFactor.btnSavedDone", "I've Saved Them")}
							</button>
						</div>
					</div>
				</div>,
				document.body
			)}

			{/* Disable Modal */}
			{typeof document !== "undefined" && isDisableOpen && createPortal(
				<div className="fixed inset-0 z-[9999] flex items-center justify-center p-4 bg-black/75 overflow-y-auto">
					<div
						className="fixed inset-0"
						onClick={() => setIsDisableOpen(false)}
					/>
					<div className="relative z-10 w-full max-w-sm rounded-3xl bg-[hsl(var(--card))] p-5 shadow-2xl border border-[hsl(var(--border))] space-y-4 max-h-[85dvh] overflow-y-auto my-auto">
						<div className="flex items-center justify-between">
							<div className="flex items-center gap-2 text-sm font-bold text-[hsl(var(--loss))]">
								<AlertTriangle className="w-5 h-5" />
								{t("twoFactor.modalDisableTitle", "Disable 2FA")}
							</div>
							<button
								type="button"
								onClick={() => setIsDisableOpen(false)}
								className="text-[hsl(var(--muted-foreground))] hover:text-[hsl(var(--foreground))]"
							>
								<X className="w-5 h-5" />
							</button>
						</div>

						<form onSubmit={handleDisable} className="space-y-3">
							<p className="text-xs text-[hsl(var(--muted-foreground))]">
								{t(
									"twoFactor.modalDisableDesc",
									"Enter your current 6-digit authenticator code (or account password) to disable 2FA.",
								)}
							</p>

							<div>
								<label className="text-xs text-[hsl(var(--muted-foreground))] block mb-1">
									{t("twoFactor.codeOrBackupLabel", "Authenticator or Backup Code")}
								</label>
								<Input
									type="text"
									value={disableCode}
									onChange={(e) => setDisableCode(e.target.value)}
									placeholder="123456 or XXXX-XXXX"
									className="text-sm"
								/>
							</div>

							<div className="text-[11px] text-center text-[hsl(var(--muted-foreground))]">
								— {t("auth.or", "OR")} —
							</div>

							<div>
								<label className="text-xs text-[hsl(var(--muted-foreground))] block mb-1">
									{t("twoFactor.accountPasswordLabel", "Account Password")}
								</label>
								<Input
									type="password"
									value={disablePassword}
									onChange={(e) => setDisablePassword(e.target.value)}
									placeholder="••••••••"
									className="text-sm"
								/>
							</div>

							<div className="flex gap-2 pt-2">
								<button
									type="button"
									onClick={() => setIsDisableOpen(false)}
									className="flex-1 py-2.5 px-3 rounded-xl border border-[hsl(var(--border))] text-xs font-medium text-[hsl(var(--muted-foreground))]"
								>
									{t("profile.cancel", "Cancel")}
								</button>
								<button
									type="submit"
									disabled={actionLoading || (!disableCode && !disablePassword)}
									className="flex-1 py-2.5 px-3 rounded-xl bg-[hsl(var(--destructive))] text-[hsl(var(--destructive-foreground))] text-xs font-semibold hover:opacity-90 disabled:opacity-50 flex items-center justify-center gap-1.5"
								>
									{actionLoading && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
									{t("twoFactor.btnConfirmDisable", "Confirm Disable")}
								</button>
							</div>
						</form>
					</div>
				</div>,
				document.body
			)}

			{/* Regenerate Modal */}
			{typeof document !== "undefined" && isRegenerateOpen && createPortal(
				<div className="fixed inset-0 z-[9999] flex items-center justify-center p-4 bg-black/75 overflow-y-auto">
					<div
						className="fixed inset-0"
						onClick={() => setIsRegenerateOpen(false)}
					/>
					<div className="relative z-10 w-full max-w-sm rounded-3xl bg-[hsl(var(--card))] p-5 shadow-2xl border border-[hsl(var(--border))] space-y-4 max-h-[85dvh] overflow-y-auto my-auto">
						<div className="flex items-center justify-between">
							<div className="flex items-center gap-2 text-sm font-bold text-[hsl(var(--foreground))]">
								<RefreshCw className="w-5 h-5 text-[hsl(var(--primary))]" />
								{t("twoFactor.modalRegenTitle", "Regenerate Backup Codes")}
							</div>
							<button
								type="button"
								onClick={() => setIsRegenerateOpen(false)}
								className="text-[hsl(var(--muted-foreground))] hover:text-[hsl(var(--foreground))]"
							>
								<X className="w-5 h-5" />
							</button>
						</div>

						<form onSubmit={handleRegenerateCodes} className="space-y-4">
							<p className="text-xs text-[hsl(var(--muted-foreground))]">
								{t(
									"twoFactor.modalRegenDesc",
									"This will invalidate old recovery codes. Enter your current 6-digit TOTP code to confirm.",
								)}
							</p>

							<div>
								<label className="text-xs text-[hsl(var(--muted-foreground))] block mb-1.5 text-center font-medium">
									{t("twoFactor.enterCodeLabel", "Enter 6-digit code")}
								</label>
								<Input
									type="text"
									inputMode="numeric"
									pattern="[0-9]*"
									maxLength={6}
									value={regenCode}
									onChange={(e) =>
										setRegenCode(e.target.value.replace(/\D/g, "").slice(0, 6))
									}
									placeholder="••••••"
									className="text-center font-mono text-xl tracking-[0.3em] h-12"
								/>
							</div>

							<div className="flex gap-2 pt-2">
								<button
									type="button"
									onClick={() => setIsRegenerateOpen(false)}
									className="flex-1 py-2.5 px-3 rounded-xl border border-[hsl(var(--border))] text-xs font-medium text-[hsl(var(--muted-foreground))]"
								>
									{t("profile.cancel", "Cancel")}
								</button>
								<button
									type="submit"
									disabled={actionLoading || regenCode.length !== 6}
									className="flex-1 py-2.5 px-3 rounded-xl bg-[hsl(var(--primary))] text-[hsl(var(--primary-foreground))] text-xs font-semibold hover:opacity-90 disabled:opacity-50 flex items-center justify-center gap-1.5"
								>
									{actionLoading && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
									{t("twoFactor.btnRegenConfirm", "Generate Codes")}
								</button>
							</div>
						</form>
					</div>
				</div>,
				document.body
			)}
		</div>
	);
};
