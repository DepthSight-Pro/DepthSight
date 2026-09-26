// src/components/account/SecuritySettings.tsx

import {
	AlertTriangle,
	Check,
	Copy,
	Loader2,
	RefreshCw,
	ShieldAlert,
	ShieldCheck,
} from "lucide-react";
import type React from "react";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import {
	Dialog,
	DialogContent,
	DialogDescription,
	DialogFooter,
	DialogHeader,
	DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import {
	InputOTP,
	InputOTPGroup,
	InputOTPSlot,
} from "@/components/ui/input-otp";
import { Label } from "@/components/ui/label";
import { useToast } from "@/components/ui/use-toast";
import {
	useConfirmTotp,
	useDisableTotp,
	useRegenerateBackupCodes,
	useSetupTotp,
	useTotpStatus,
} from "@/lib/api";
import type { TotpBackupCodesResponse, TotpConfirmResponse, TotpSetupResponse } from "@/types/api";

// --- Type helpers for snake_case fallback properties ---
// The backend may return snake_case keys; these types extend the
// canonical camelCase interfaces to allow safe fallback access.
type TotpSetupWithSnake = TotpSetupResponse & {
	qr_code?: string;
	manual_entry_key?: string;
};

type TotpConfirmWithSnake = TotpConfirmResponse & {
	backup_codes?: string[];
};

type TotpBackupCodesWithSnake = TotpBackupCodesResponse & {
	backup_codes?: string[];
};

/** Safely extract an error message from an unknown catch value. */
const getErrorMessage = (error: unknown): string => {
	if (error instanceof Error) return error.message;
	if (error && typeof error === "object" && "message" in error) {
		return String((error as { message: unknown }).message);
	}
	return "";
};

export const SecuritySettings: React.FC = () => {
	const { t } = useTranslation(["account", "common"]);
	const { toast } = useToast();

	const { data: statusData, isLoading: isLoadingStatus } = useTotpStatus();
	const isTotpEnabled = statusData?.isTotpEnabled ?? false;
	const remainingBackupCodes = statusData?.remainingBackupCodesCount ?? 0;

	// Mutations
	const setupMutation = useSetupTotp();
	const confirmMutation = useConfirmTotp();
	const disableMutation = useDisableTotp();
	const regenerateMutation = useRegenerateBackupCodes();

	// Modal states
	const [setupData, setSetupData] = useState<TotpSetupResponse | null>(null);
	const [isSetupOpen, setIsSetupOpen] = useState(false);
	const [confirmCode, setConfirmCode] = useState("");
	const [copiedKey, setCopiedKey] = useState(false);

	// Backup codes display modal
	const [newBackupCodes, setNewBackupCodes] = useState<string[] | null>(null);
	const [isBackupCodesOpen, setIsBackupCodesOpen] = useState(false);
	const [copiedBackupCodes, setCopiedBackupCodes] = useState(false);

	// Disable modal
	const [isDisableOpen, setIsDisableOpen] = useState(false);
	const [disableCode, setDisableCode] = useState("");
	const [disablePassword, setDisablePassword] = useState("");

	// Regenerate codes modal
	const [isRegenerateOpen, setIsRegenerateOpen] = useState(false);
	const [regenCode, setRegenCode] = useState("");

	// Start 2FA setup
	const handleStartSetup = async () => {
		try {
			setIsSetupOpen(true);
			setConfirmCode("");
			setSetupData(null);
			const res = await setupMutation.mutateAsync();
			const data = res;
			setSetupData(data);
		} catch (error: unknown) {
			setIsSetupOpen(false);
			toast({
				variant: "destructive",
				title: t("twoFactor.setupErrorTitle", "Setup Failed"),
				description:
					getErrorMessage(error) ||
					t("twoFactor.setupErrorDesc", "Could not start 2FA setup."),
			});
		}
	};

	// Confirm 2FA setup with OTP code
	const handleConfirmSetup = async () => {
		const secret = setupData?.secret;
		if (!secret || confirmCode.length !== 6) return;

		try {
			const res = await confirmMutation.mutateAsync({
				secret,
				code: confirmCode,
			});
			const data = res;
			setIsSetupOpen(false);
			setSetupData(null);
			setConfirmCode("");

			// Show backup codes modal immediately
			const backupCodes = data.backupCodes || (data as TotpConfirmWithSnake)?.backup_codes;
			if (backupCodes?.length) {
				setNewBackupCodes(backupCodes);
				setIsBackupCodesOpen(true);
			}

			toast({
				title: t("twoFactor.enabledTitle", "2FA Enabled"),
				description: t(
					"twoFactor.enabledDesc",
					"Two-Factor Authentication is now active on your account.",
				),
			});
		} catch (error: unknown) {
			toast({
				variant: "destructive",
				title: t("twoFactor.confirmErrorTitle", "Verification Failed"),
				description:
					getErrorMessage(error) ||
					t("twoFactor.confirmErrorDesc", "Invalid code. Please try again."),
			});
		}
	};

	// Disable 2FA
	const handleDisable = async () => {
		try {
			await disableMutation.mutateAsync({
				code: disableCode.trim() || undefined,
				password: disablePassword || undefined,
			});
			setIsDisableOpen(false);
			setDisableCode("");
			setDisablePassword("");

			toast({
				title: t("twoFactor.disabledTitle", "2FA Disabled"),
				description: t(
					"twoFactor.disabledDesc",
					"Two-Factor Authentication has been removed.",
				),
			});
		} catch (error: unknown) {
			toast({
				variant: "destructive",
				title: t("twoFactor.disableErrorTitle", "Disable Failed"),
				description:
					getErrorMessage(error) ||
					t(
						"twoFactor.disableErrorDesc",
						"Invalid code or password. Please verify and retry.",
					),
			});
		}
	};

	// Regenerate backup codes
	const handleRegenerateCodes = async () => {
		if (regenCode.length !== 6) return;

		try {
			const res = await regenerateMutation.mutateAsync({ code: regenCode });
			const data = res;
			setIsRegenerateOpen(false);
			setRegenCode("");

			const backupCodes = data.backupCodes || (data as TotpBackupCodesWithSnake)?.backup_codes;
			if (backupCodes?.length) {
				setNewBackupCodes(backupCodes);
				setIsBackupCodesOpen(true);
			}

			toast({
				title: t("twoFactor.regenSuccessTitle", "Backup Codes Regenerated"),
				description: t(
					"twoFactor.regenSuccessDesc",
					"Your old recovery codes are now invalidated.",
				),
			});
		} catch (error: unknown) {
			toast({
				variant: "destructive",
				title: t("twoFactor.regenErrorTitle", "Regeneration Failed"),
				description:
					getErrorMessage(error) ||
					t("twoFactor.regenErrorDesc", "Invalid 2FA code."),
			});
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
			(setupData as TotpSetupWithSnake | null)?.manual_entry_key ||
			setupData?.secret;
		if (!key) return;
		const ok = await copyTextToClipboard(key);
		if (ok) {
			setCopiedKey(true);
			toast({
				title: t("twoFactor.keyCopiedTitle", "Key Copied"),
				description: t("twoFactor.keyCopiedDesc", "Setup key copied to clipboard."),
			});
			setTimeout(() => setCopiedKey(false), 2500);
		}
	};

	const copyAllBackupCodes = async () => {
		if (!newBackupCodes) return;
		const ok = await copyTextToClipboard(newBackupCodes.join("\n"));
		if (ok) {
			setCopiedBackupCodes(true);
			toast({
				title: t("twoFactor.codesCopiedTitle", "Codes Copied"),
				description: t(
					"twoFactor.codesCopiedDesc",
					"All backup recovery codes copied to clipboard.",
				),
			});
			setTimeout(() => setCopiedBackupCodes(false), 2500);
		}
	};

	return (
		<>
			<div className="glass relative overflow-hidden rounded-2xl border border-white/10 p-6 shadow-2xl backdrop-blur-xl">
				{/* Ambient Glow */}
				<div
					className={cn(
						"pointer-events-none absolute -right-16 -top-16 h-48 w-48 rounded-full blur-3xl",
						isTotpEnabled ? "bg-emerald-500/10" : "bg-amber-500/10",
					)}
				/>

				<div className="relative z-10 space-y-5">
					{/* Header */}
					<div className="flex items-start justify-between gap-4 flex-wrap">
						<div className="flex items-start gap-3.5">
							<div
								className={cn(
									"flex h-11 w-11 shrink-0 items-center justify-center rounded-xl border transition-all",
									isTotpEnabled
										? "border-emerald-500/40 bg-emerald-500/10 text-emerald-400 shadow-[0_0_15px_-4px_rgba(16,224,160,0.5)]"
										: "border-amber-500/40 bg-amber-500/10 text-amber-400 shadow-[0_0_15px_-4px_rgba(245,158,11,0.4)]",
								)}
							>
								{isTotpEnabled ? (
									<ShieldCheck className="h-6 w-6" />
								) : (
									<ShieldAlert className="h-6 w-6" />
								)}
							</div>
							<div>
								<div className="flex items-center gap-2">
									<h2 className="text-base font-semibold text-white tracking-tight">
										{t("twoFactor.cardTitle", "Two-Factor Authentication (2FA)")}
									</h2>
								</div>
								<p className="text-xs text-white/50 mt-1 max-w-xl leading-relaxed">
									{t(
										"twoFactor.cardDescription",
										"Protect your exchange keys and account with an extra layer of security using Google Authenticator or any TOTP app.",
									)}
								</p>
							</div>
						</div>

						{isLoadingStatus ? (
							<Loader2 className="h-5 w-5 animate-spin text-white/40" />
						) : isTotpEnabled ? (
							<div className="inline-flex items-center gap-1.5 rounded-xl border border-emerald-500/40 bg-emerald-500/10 px-3 py-1 font-mono text-xs font-semibold text-emerald-400 shadow-[0_0_15px_-3px_rgba(16,224,160,0.4)]">
								<ShieldCheck className="h-3.5 w-3.5" />
								{t("twoFactor.badgeEnabled", "Active")}
							</div>
						) : (
							<div className="inline-flex items-center gap-1.5 rounded-xl border border-amber-500/40 bg-amber-500/10 px-3 py-1 font-mono text-xs font-semibold text-amber-400 shadow-[0_0_15px_-3px_rgba(245,158,11,0.4)]">
								<ShieldAlert className="h-3.5 w-3.5" />
								{t("twoFactor.badgeDisabled", "Not Enabled")}
							</div>
						)}
					</div>

					{/* Body Content */}
					{isTotpEnabled ? (
						<div className="space-y-4 pt-1">
							<div className="rounded-xl border border-border/80 dark:border-white/10 bg-muted/20 dark:bg-white/[0.02] p-4 flex items-center justify-between gap-4">
								<div>
									<div className="text-xs font-medium text-foreground/90 dark:text-white/80">
										{t("twoFactor.recoveryCodesCountLabel", "Available Backup Codes:")}
									</div>
									{remainingBackupCodes <= 2 && (
										<p className="text-[11px] text-amber-500 dark:text-amber-400 flex items-center gap-1 mt-0.5">
											<AlertTriangle className="h-3 w-3" />
											{t(
												"twoFactor.lowCodesWarning",
												"You have very few backup codes left. Consider regenerating them.",
											)}
										</p>
									)}
								</div>
								<div className="flex items-center gap-2">
									<span
										className={cn(
											"font-mono text-sm font-bold px-2.5 py-0.5 rounded-lg border",
											remainingBackupCodes > 2
												? "border-border/80 dark:border-white/10 bg-card dark:bg-white/[0.04] text-foreground dark:text-white"
												: "border-rose-500/30 bg-rose-500/10 text-rose-500 dark:text-rose-400",
										)}
									>
										{remainingBackupCodes} {t("twoFactor.remaining", "remaining")}
									</span>
								</div>
							</div>

							<div className="flex flex-wrap gap-2.5 pt-1">
								<Button
									type="button"
									variant="outline"
									onClick={() => setIsRegenerateOpen(true)}
									className="rounded-xl border border-border dark:border-white/10 bg-card dark:bg-white/[0.03] hover:bg-muted dark:hover:bg-white/[0.08] text-foreground dark:text-white text-xs h-9 px-4 gap-2 transition-all shadow-sm"
								>
									<RefreshCw className="h-3.5 w-3.5 text-cyan" />
									{t("twoFactor.btnRegenerateCodes", "Regenerate Backup Codes")}
								</Button>
								<Button
									type="button"
									variant="destructive"
									onClick={() => setIsDisableOpen(true)}
									className="rounded-xl border border-rose-500/30 bg-rose-500/10 hover:bg-rose-500/20 text-rose-500 dark:text-rose-400 hover:text-rose-600 dark:hover:text-rose-300 text-xs h-9 px-4 transition-all"
								>
									{t("twoFactor.btnDisable", "Disable 2FA")}
								</Button>
							</div>
						</div>
					) : (
						<div className="space-y-4 pt-1">
							<div className="rounded-xl border border-cyan/20 bg-cyan/[0.04] p-4 flex items-start gap-3">
								<ShieldCheck className="h-4 w-4 text-cyan shrink-0 mt-0.5" />
								<div>
									<div className="text-xs font-semibold text-white">
										{t("twoFactor.recommendationTitle", "Highly Recommended")}
									</div>
									<div className="text-[11.5px] text-white/50 mt-0.5 leading-relaxed">
										{t(
											"twoFactor.recommendationText",
											"Enabling 2FA safeguards your trading bots, exchange balances, and withdrawal settings against unauthorized access even if your password is stolen.",
										)}
									</div>
								</div>
							</div>

							<Button
								type="button"
								onClick={handleStartSetup}
								disabled={setupMutation.isPending}
								className="rounded-xl bg-gradient-to-r from-azure to-cyan text-white font-semibold text-xs h-9 px-5 shadow-[0_0_20px_-4px_rgba(0,212,255,0.6)] hover:brightness-110 transition-all gap-2"
							>
								{setupMutation.isPending ? (
									<Loader2 className="h-3.5 w-3.5 animate-spin" />
								) : (
									<ShieldCheck className="h-3.5 w-3.5" />
								)}
								{t("twoFactor.btnEnable", "Enable 2FA Authentication")}
							</Button>
						</div>
					)}
				</div>
			</div>

			{/* Modal: Setup 2FA */}
			<Dialog open={isSetupOpen} onOpenChange={setIsSetupOpen}>
				<DialogContent className="sm:max-w-md bg-obsidian/95 border border-white/10 text-white shadow-2xl backdrop-blur-2xl rounded-2xl p-6">
					<DialogHeader>
						<DialogTitle className="flex items-center gap-2 text-base text-white">
							<ShieldCheck className="h-4 w-4 text-cyan" />
							{t("twoFactor.modalSetupTitle", "Set Up Two-Factor Authentication")}
						</DialogTitle>
						<DialogDescription className="text-xs text-white/50">
							{t(
								"twoFactor.modalSetupDesc",
								"Scan the QR code with your authenticator app (Google Authenticator, Aegis, 1Password), then enter the 6-digit verification code.",
							)}
						</DialogDescription>
					</DialogHeader>

					{!setupData || setupMutation.isPending ? (
						<div className="flex flex-col items-center justify-center py-12 space-y-3">
							<Loader2 className="h-8 w-8 animate-spin text-cyan" />
							<p className="text-xs text-white/50">
								{t("twoFactor.generatingSetup", "Generating QR code...")}
							</p>
						</div>
					) : (
						<div className="space-y-4 py-2">
							{/* QR Code Container */}
							<div className="flex flex-col items-center justify-center p-3.5 bg-white rounded-2xl shadow-xl border border-white/20 mx-auto max-w-[210px]">
								<img
									src={setupData.qrCode || (setupData as TotpSetupWithSnake).qr_code}
									alt="2FA QR Code"
									className="w-40 h-40 object-contain rounded-lg"
								/>
							</div>

							{/* Manual Key */}
							<div className="space-y-1.5 rounded-xl border border-white/10 bg-white/[0.03] p-3">
								<div className="flex items-center justify-between text-[11px] text-white/40 font-medium px-1">
									<span>{t("twoFactor.manualKeyLabel", "Can't scan? Enter manually:")}</span>
									<span className="text-[10px] text-cyan/80">
										{t("twoFactor.clickToCopy", "Click to copy")}
									</span>
								</div>

								<div
									onClick={copySecret}
									className="group cursor-pointer rounded-lg bg-black/40 border border-white/10 p-2.5 flex items-center justify-between gap-2 hover:border-cyan/50 transition"
									title={t("twoFactor.clickToCopy", "Click to copy")}
								>
									<code className="text-[11.5px] font-mono font-semibold select-all tracking-wider break-all text-left text-cyan">
										{setupData.manualEntryKey ||
											(setupData as TotpSetupWithSnake).manual_entry_key ||
											setupData.secret}
									</code>
									<Button
										type="button"
										variant="ghost"
										size="sm"
										className="shrink-0 h-7 px-2.5 text-xs text-white/60 hover:text-white pointer-events-none"
									>
										{copiedKey ? (
											<Check className="h-3.5 w-3.5 text-emerald-400" />
										) : (
											<Copy className="h-3.5 w-3.5" />
										)}
									</Button>
								</div>
							</div>

							{/* Verification Code Input */}
							<div className="space-y-2 text-center pt-1">
								<Label className="text-xs font-semibold text-white/70">
									{t("twoFactor.enterCodeLabel", "Enter 6-digit code from app")}
								</Label>
								<div className="flex justify-center">
									<InputOTP
										maxLength={6}
										value={confirmCode}
										onChange={(val) => setConfirmCode(val)}
									>
										<InputOTPGroup className="gap-1.5">
											<InputOTPSlot index={0} className="border-white/15 bg-white/[0.04] text-white font-mono text-base rounded-lg" />
											<InputOTPSlot index={1} className="border-white/15 bg-white/[0.04] text-white font-mono text-base rounded-lg" />
											<InputOTPSlot index={2} className="border-white/15 bg-white/[0.04] text-white font-mono text-base rounded-lg" />
											<InputOTPSlot index={3} className="border-white/15 bg-white/[0.04] text-white font-mono text-base rounded-lg" />
											<InputOTPSlot index={4} className="border-white/15 bg-white/[0.04] text-white font-mono text-base rounded-lg" />
											<InputOTPSlot index={5} className="border-white/15 bg-white/[0.04] text-white font-mono text-base rounded-lg" />
										</InputOTPGroup>
									</InputOTP>
								</div>
							</div>
						</div>
					)}

					<DialogFooter className="sm:justify-between gap-2 pt-2">
						<Button
							type="button"
							variant="ghost"
							onClick={() => setIsSetupOpen(false)}
							className="rounded-xl border border-white/10 bg-white/[0.02] hover:bg-white/[0.06] text-white/60 text-xs h-9 px-4"
						>
							{t("common:cancel", "Cancel")}
						</Button>
						<Button
							type="button"
							onClick={handleConfirmSetup}
							disabled={confirmCode.length !== 6 || confirmMutation.isPending || !setupData}
							className="rounded-xl bg-gradient-to-r from-azure to-cyan text-white font-semibold text-xs h-9 px-5 shadow-[0_0_15px_rgba(0,212,255,0.5)] hover:brightness-110 transition-all gap-2"
						>
							{confirmMutation.isPending && (
								<Loader2 className="h-3.5 w-3.5 animate-spin" />
							)}
							{t("twoFactor.btnConfirmAndEnable", "Confirm & Enable")}
						</Button>
					</DialogFooter>
				</DialogContent>
			</Dialog>

			{/* Modal: Backup Codes Display */}
			<Dialog open={isBackupCodesOpen} onOpenChange={setIsBackupCodesOpen}>
				<DialogContent className="sm:max-w-md bg-obsidian/95 border border-white/10 text-white shadow-2xl backdrop-blur-2xl rounded-2xl p-6">
					<DialogHeader>
						<DialogTitle className="flex items-center gap-2 text-base text-emerald-400">
							<Check className="h-4 w-4" />
							{t("twoFactor.modalBackupCodesTitle", "Save Your Recovery Codes")}
						</DialogTitle>
						<DialogDescription className="text-xs text-white/50">
							{t(
								"twoFactor.modalBackupCodesDesc",
								"If you lose access to your phone or authenticator app, these one-time codes are the ONLY way to regain access to your DepthSight account.",
							)}
						</DialogDescription>
					</DialogHeader>

					<div className="rounded-xl border border-rose-500/30 bg-rose-500/10 p-3 flex items-start gap-2.5 my-1">
						<AlertTriangle className="h-4 w-4 text-rose-400 shrink-0 mt-0.5" />
						<div className="text-xs text-rose-300 leading-relaxed">
							<span className="font-bold block uppercase tracking-wide text-[10px]">
								{t("twoFactor.backupWarningTitle", "Important Warning")}
							</span>
							{t(
								"twoFactor.backupWarningText",
								"These codes are shown only ONCE and cannot be recovered if lost. Store them in a secure password manager or offline file.",
							)}
						</div>
					</div>

					{newBackupCodes && (
						<div className="grid grid-cols-2 gap-2 p-3 bg-black/40 rounded-xl border border-white/10 font-mono text-xs font-semibold tracking-wider text-center">
							{newBackupCodes.map((code, idx) => (
								<div key={idx} className="bg-white/[0.04] py-1.5 px-2 rounded-lg border border-white/5 text-white/90">
									{code}
								</div>
							))}
						</div>
					)}

					<DialogFooter className="sm:justify-between gap-2 pt-2">
						<Button
							type="button"
							variant="outline"
							onClick={copyAllBackupCodes}
							className="rounded-xl border border-white/10 bg-white/[0.03] hover:bg-white/[0.08] text-white text-xs h-9 px-4 gap-2 transition-all"
						>
							{copiedBackupCodes ? (
								<Check className="h-3.5 w-3.5 text-emerald-400" />
							) : (
								<Copy className="h-3.5 w-3.5" />
							)}
							{copiedBackupCodes
								? t("common:copied", "Copied!")
								: t("twoFactor.btnCopyCodes", "Copy All Codes")}
						</Button>
						<Button
							type="button"
							onClick={() => setIsBackupCodesOpen(false)}
							className="rounded-xl bg-gradient-to-r from-azure to-cyan text-white font-semibold text-xs h-9 px-5 shadow-[0_0_15px_rgba(0,212,255,0.5)] hover:brightness-110 transition-all"
						>
							{t("twoFactor.btnSavedDone", "I've Saved Them")}
						</Button>
					</DialogFooter>
				</DialogContent>
			</Dialog>

			{/* Modal: Disable 2FA */}
			<Dialog open={isDisableOpen} onOpenChange={setIsDisableOpen}>
				<DialogContent className="sm:max-w-md bg-obsidian/95 border border-white/10 text-white shadow-2xl backdrop-blur-2xl rounded-2xl p-6">
					<DialogHeader>
						<DialogTitle className="flex items-center gap-2 text-base text-rose-400">
							<AlertTriangle className="h-4 w-4" />
							{t("twoFactor.modalDisableTitle", "Disable Two-Factor Authentication")}
						</DialogTitle>
						<DialogDescription className="text-xs text-white/50">
							{t(
								"twoFactor.modalDisableDesc",
								"To disable 2FA, enter your current 6-digit authenticator code (or account password).",
							)}
						</DialogDescription>
					</DialogHeader>

					<div className="space-y-3.5 py-2">
						<div className="space-y-1.5">
							<Label htmlFor="disable-code" className="text-xs text-white/70">
								{t("twoFactor.codeOrBackupLabel", "Authenticator or Backup Code")}
							</Label>
							<Input
								id="disable-code"
								placeholder="123456 or XXXX-XXXX"
								value={disableCode}
								onChange={(e) => setDisableCode(e.target.value)}
								autoComplete="off"
								className="h-9 rounded-xl border border-white/10 bg-white/[0.03] text-xs text-white placeholder-white/30 focus:border-cyan/50"
							/>
						</div>
						<div className="text-[11px] text-center text-white/30 font-mono">— {t("common:or", "OR")} —</div>
						<div className="space-y-1.5">
							<Label htmlFor="disable-password" className="text-xs text-white/70">
								{t("twoFactor.accountPasswordLabel", "Account Password")}
							</Label>
							<Input
								id="disable-password"
								type="password"
								placeholder="••••••••"
								value={disablePassword}
								onChange={(e) => setDisablePassword(e.target.value)}
								className="h-9 rounded-xl border border-white/10 bg-white/[0.03] text-xs text-white placeholder-white/30 focus:border-cyan/50"
							/>
						</div>
					</div>

					<DialogFooter className="sm:justify-between gap-2 pt-2">
						<Button
							type="button"
							variant="ghost"
							onClick={() => setIsDisableOpen(false)}
							className="rounded-xl border border-white/10 bg-white/[0.02] hover:bg-white/[0.06] text-white/60 text-xs h-9 px-4"
						>
							{t("common:cancel", "Cancel")}
						</Button>
						<Button
							type="button"
							variant="destructive"
							onClick={handleDisable}
							disabled={(!disableCode && !disablePassword) || disableMutation.isPending}
							className="rounded-xl border border-rose-500/30 bg-rose-500/20 hover:bg-rose-500/30 text-rose-300 text-xs h-9 px-5 gap-2 transition-all"
						>
							{disableMutation.isPending && (
								<Loader2 className="h-3.5 w-3.5 animate-spin" />
							)}
							{t("twoFactor.btnConfirmDisable", "Confirm Disable")}
						</Button>
					</DialogFooter>
				</DialogContent>
			</Dialog>

			{/* Modal: Regenerate Backup Codes */}
			<Dialog open={isRegenerateOpen} onOpenChange={setIsRegenerateOpen}>
				<DialogContent className="sm:max-w-md bg-obsidian/95 border border-white/10 text-white shadow-2xl backdrop-blur-2xl rounded-2xl p-6">
					<DialogHeader>
						<DialogTitle className="flex items-center gap-2 text-base text-white">
							<RefreshCw className="h-4 w-4 text-cyan" />
							{t("twoFactor.modalRegenTitle", "Regenerate Backup Codes")}
						</DialogTitle>
						<DialogDescription className="text-xs text-white/50">
							{t(
								"twoFactor.modalRegenDesc",
								"This will invalidate all previously generated backup recovery codes. Enter your current 6-digit TOTP code to confirm.",
							)}
						</DialogDescription>
					</DialogHeader>

					<div className="space-y-2 py-4 flex flex-col items-center">
						<Label className="text-xs font-semibold text-white/70">
							{t("twoFactor.enterCodeLabel", "Enter 6-digit code from app")}
						</Label>
						<InputOTP
							maxLength={6}
							value={regenCode}
							onChange={(val) => setRegenCode(val)}
						>
							<InputOTPGroup className="gap-1.5">
								<InputOTPSlot index={0} className="border-white/15 bg-white/[0.04] text-white font-mono text-base rounded-lg" />
								<InputOTPSlot index={1} className="border-white/15 bg-white/[0.04] text-white font-mono text-base rounded-lg" />
								<InputOTPSlot index={2} className="border-white/15 bg-white/[0.04] text-white font-mono text-base rounded-lg" />
								<InputOTPSlot index={3} className="border-white/15 bg-white/[0.04] text-white font-mono text-base rounded-lg" />
								<InputOTPSlot index={4} className="border-white/15 bg-white/[0.04] text-white font-mono text-base rounded-lg" />
								<InputOTPSlot index={5} className="border-white/15 bg-white/[0.04] text-white font-mono text-base rounded-lg" />
							</InputOTPGroup>
						</InputOTP>
					</div>

					<DialogFooter className="sm:justify-between gap-2 pt-2">
						<Button
							type="button"
							variant="ghost"
							onClick={() => setIsRegenerateOpen(false)}
							className="rounded-xl border border-white/10 bg-white/[0.02] hover:bg-white/[0.06] text-white/60 text-xs h-9 px-4"
						>
							{t("common:cancel", "Cancel")}
						</Button>
						<Button
							type="button"
							onClick={handleRegenerateCodes}
							disabled={regenCode.length !== 6 || regenerateMutation.isPending}
							className="rounded-xl bg-gradient-to-r from-azure to-cyan text-white font-semibold text-xs h-9 px-5 shadow-[0_0_15px_rgba(0,212,255,0.5)] hover:brightness-110 transition-all gap-2"
						>
							{regenerateMutation.isPending && (
								<Loader2 className="h-3.5 w-3.5 animate-spin" />
							)}
							{t("twoFactor.btnRegenConfirm", "Generate New Codes")}
						</Button>
					</DialogFooter>
				</DialogContent>
			</Dialog>
		</>
	);
};
