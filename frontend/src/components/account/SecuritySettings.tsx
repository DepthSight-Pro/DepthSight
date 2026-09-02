// src/components/account/SecuritySettings.tsx

import {
	AlertTriangle,
	Check,
	Copy,
	KeyRound,
	Loader2,
	RefreshCw,
	ShieldAlert,
	ShieldCheck,
} from "lucide-react";
import type React from "react";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
	Card,
	CardContent,
	CardDescription,
	CardHeader,
	CardTitle,
} from "@/components/ui/card";
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
import type { TotpSetupResponse } from "@/types/api";

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
			const data = (res as any)?.data || res;
			setSetupData(data);
		} catch (error: any) {
			setIsSetupOpen(false);
			toast({
				variant: "destructive",
				title: t("twoFactor.setupErrorTitle", "Setup Failed"),
				description:
					error.message ||
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
			const data = (res as any)?.data || res;
			setIsSetupOpen(false);
			setSetupData(null);
			setConfirmCode("");

			// Show backup codes modal immediately
			const backupCodes = data?.backupCodes || (data as any)?.backup_codes;
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
		} catch (error: any) {
			toast({
				variant: "destructive",
				title: t("twoFactor.confirmErrorTitle", "Verification Failed"),
				description:
					error.message ||
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
		} catch (error: any) {
			toast({
				variant: "destructive",
				title: t("twoFactor.disableErrorTitle", "Disable Failed"),
				description:
					error.message ||
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
			const data = (res as any)?.data || res;
			setIsRegenerateOpen(false);
			setRegenCode("");

			const backupCodes = data?.backupCodes || (data as any)?.backup_codes;
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
		} catch (error: any) {
			toast({
				variant: "destructive",
				title: t("twoFactor.regenErrorTitle", "Regeneration Failed"),
				description:
					error.message ||
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
			(setupData as any)?.manual_entry_key ||
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
			<Card>
				<CardHeader>
					<div className="flex items-center justify-between">
						<div className="space-y-1">
							<CardTitle className="flex items-center text-xl">
								<KeyRound className="mr-2 h-5 w-5 text-primary" />
								{t("twoFactor.cardTitle", "Two-Factor Authentication (2FA)")}
							</CardTitle>
							<CardDescription>
								{t(
									"twoFactor.cardDescription",
									"Protect your exchange keys and account with an extra layer of security using Google Authenticator or any TOTP app.",
								)}
							</CardDescription>
						</div>
						{isLoadingStatus ? (
							<Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
						) : isTotpEnabled ? (
							<Badge variant="default" className="bg-emerald-600 hover:bg-emerald-700 text-white gap-1 py-1 px-3">
								<ShieldCheck className="h-4 w-4" />
								{t("twoFactor.badgeEnabled", "Active")}
							</Badge>
						) : (
							<Badge variant="secondary" className="gap-1 py-1 px-3 text-amber-500 border-amber-500/30">
								<ShieldAlert className="h-4 w-4" />
								{t("twoFactor.badgeDisabled", "Not Enabled")}
							</Badge>
						)}
					</div>
				</CardHeader>
				<CardContent className="space-y-4">
					{isTotpEnabled ? (
						<div className="space-y-4">
							<div className="rounded-lg border bg-muted/40 p-4 space-y-2">
								<div className="flex items-center justify-between text-sm">
									<span className="font-medium text-muted-foreground">
										{t("twoFactor.recoveryCodesCountLabel", "Available Backup Codes:")}
									</span>
									<Badge variant={remainingBackupCodes > 2 ? "outline" : "destructive"}>
										{remainingBackupCodes} {t("twoFactor.remaining", "remaining")}
									</Badge>
								</div>
								{remainingBackupCodes <= 2 && (
									<p className="text-xs text-amber-500 flex items-center gap-1">
										<AlertTriangle className="h-3 w-3" />
										{t(
											"twoFactor.lowCodesWarning",
											"You have very few backup codes left. Consider regenerating them.",
										)}
									</p>
								)}
							</div>

							<div className="flex flex-wrap gap-3 pt-2">
								<Button
									variant="outline"
									onClick={() => setIsRegenerateOpen(true)}
									className="gap-2"
								>
									<RefreshCw className="h-4 w-4" />
									{t("twoFactor.btnRegenerateCodes", "Regenerate Backup Codes")}
								</Button>
								<Button
									variant="destructive"
									onClick={() => setIsDisableOpen(true)}
								>
									{t("twoFactor.btnDisable", "Disable 2FA")}
								</Button>
							</div>
						</div>
					) : (
						<div className="space-y-4">
							<Alert className="border-primary/20 bg-primary/5">
								<ShieldCheck className="h-4 w-4 text-primary" />
								<AlertTitle className="text-sm font-semibold">
									{t("twoFactor.recommendationTitle", "Highly Recommended")}
								</AlertTitle>
								<AlertDescription className="text-xs text-muted-foreground">
									{t(
										"twoFactor.recommendationText",
										"Enabling 2FA safeguards your trading bots, exchange balances, and withdrawal settings against unauthorized access even if your password is stolen.",
									)}
								</AlertDescription>
							</Alert>

							<Button
								onClick={handleStartSetup}
								disabled={setupMutation.isPending}
								className="gap-2"
							>
								{setupMutation.isPending ? (
									<Loader2 className="h-4 w-4 animate-spin" />
								) : (
									<ShieldCheck className="h-4 w-4" />
								)}
								{t("twoFactor.btnEnable", "Enable 2FA Authentication")}
							</Button>
						</div>
					)}
				</CardContent>
			</Card>

			{/* Modal: Setup 2FA */}
			<Dialog open={isSetupOpen} onOpenChange={setIsSetupOpen}>
				<DialogContent className="sm:max-w-md">
					<DialogHeader>
						<DialogTitle className="flex items-center gap-2">
							<ShieldCheck className="h-5 w-5 text-primary" />
							{t("twoFactor.modalSetupTitle", "Set Up Two-Factor Authentication")}
						</DialogTitle>
						<DialogDescription>
							{t(
								"twoFactor.modalSetupDesc",
								"Scan the QR code with your authenticator app (Google Authenticator, Aegis, 1Password), then enter the 6-digit verification code.",
							)}
						</DialogDescription>
					</DialogHeader>

					{!setupData || setupMutation.isPending ? (
						<div className="flex flex-col items-center justify-center py-12 space-y-3">
							<Loader2 className="h-8 w-8 animate-spin text-primary" />
							<p className="text-sm text-muted-foreground">
								{t("twoFactor.generatingSetup", "Generating QR code...")}
							</p>
						</div>
					) : (
						<div className="space-y-4 py-2">
							{/* QR Code Container */}
							<div className="flex flex-col items-center justify-center p-4 bg-white rounded-xl shadow-inner border mx-auto max-w-[220px]">
								<img
									src={setupData.qrCode || (setupData as any).qr_code}
									alt="2FA QR Code"
									className="w-44 h-44 object-contain"
								/>
							</div>

							{/* Manual Key */}
							<div className="space-y-2 rounded-xl border border-border/80 bg-muted/40 p-3">
								<div className="flex items-center justify-between text-xs text-muted-foreground font-medium px-1">
									<span>{t("twoFactor.manualKeyLabel", "Can't scan? Enter this key manually:")}</span>
									<span className="text-[10px] text-muted-foreground">
										{t("twoFactor.clickToCopy", "Click to copy")}
									</span>
								</div>

								<div
									onClick={copySecret}
									className="group cursor-pointer rounded-lg bg-background border border-input p-2.5 flex items-center justify-between gap-2 hover:border-primary/50 transition shadow-xs"
									title={t("twoFactor.clickToCopy", "Click to copy")}
								>
									<code className="text-xs font-mono font-semibold select-all tracking-wider break-all text-left">
										{setupData.manualEntryKey ||
											(setupData as any).manual_entry_key ||
											setupData.secret}
									</code>
									<Button
										type="button"
										variant={copiedKey ? "default" : "secondary"}
										size="sm"
										className="shrink-0 h-8 gap-1.5 text-xs pointer-events-none"
									>
										{copiedKey ? (
											<>
												<Check className="h-3.5 w-3.5 text-white" />
												<span>{t("twoFactor.copied", "Copied!")}</span>
											</>
										) : (
											<>
												<Copy className="h-3.5 w-3.5" />
												<span>{t("twoFactor.btnCopyKey", "Copy")}</span>
											</>
										)}
									</Button>
								</div>
							</div>

							{/* Verification Code Input */}
							<div className="space-y-2 text-center pt-2">
								<Label className="text-sm font-medium">
									{t("twoFactor.enterCodeLabel", "Enter 6-digit code from app")}
								</Label>
								<div className="flex justify-center">
									<InputOTP
										maxLength={6}
										value={confirmCode}
										onChange={(val) => setConfirmCode(val)}
									>
										<InputOTPGroup>
											<InputOTPSlot index={0} />
											<InputOTPSlot index={1} />
											<InputOTPSlot index={2} />
											<InputOTPSlot index={3} />
											<InputOTPSlot index={4} />
											<InputOTPSlot index={5} />
										</InputOTPGroup>
									</InputOTP>
								</div>
							</div>
						</div>
					)}

					<DialogFooter className="sm:justify-between gap-2">
						<Button
							type="button"
							variant="outline"
							onClick={() => setIsSetupOpen(false)}
						>
							{t("common:cancel", "Cancel")}
						</Button>
						<Button
							type="button"
							onClick={handleConfirmSetup}
							disabled={confirmCode.length !== 6 || confirmMutation.isPending || !setupData}
							className="gap-2"
						>
							{confirmMutation.isPending && (
								<Loader2 className="h-4 w-4 animate-spin" />
							)}
							{t("twoFactor.btnConfirmAndEnable", "Confirm & Enable")}
						</Button>
					</DialogFooter>
				</DialogContent>
			</Dialog>

			{/* Modal: Backup Codes Display */}
			<Dialog open={isBackupCodesOpen} onOpenChange={setIsBackupCodesOpen}>
				<DialogContent className="sm:max-w-md">
					<DialogHeader>
						<DialogTitle className="flex items-center gap-2 text-emerald-500">
							<Check className="h-5 w-5" />
							{t("twoFactor.modalBackupCodesTitle", "Save Your Recovery Codes")}
						</DialogTitle>
						<DialogDescription>
							{t(
								"twoFactor.modalBackupCodesDesc",
								"If you lose access to your phone or authenticator app, these one-time codes are the ONLY way to regain access to your DepthSight account.",
							)}
						</DialogDescription>
					</DialogHeader>

					<Alert variant="destructive" className="my-2">
						<AlertTriangle className="h-4 w-4" />
						<AlertTitle className="text-xs font-bold uppercase tracking-wide">
							{t("twoFactor.backupWarningTitle", "Important Warning")}
						</AlertTitle>
						<AlertDescription className="text-xs">
							{t(
								"twoFactor.backupWarningText",
								"These codes are shown only ONCE and cannot be recovered if lost. Store them in a secure password manager or offline file.",
							)}
						</AlertDescription>
					</Alert>

					{newBackupCodes && (
						<div className="grid grid-cols-2 gap-2 p-3 bg-muted/60 rounded-lg border font-mono text-sm font-semibold tracking-wider text-center">
							{newBackupCodes.map((code, idx) => (
								<div key={idx} className="bg-background py-1.5 px-2 rounded border shadow-sm">
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
							className="gap-2"
						>
							{copiedBackupCodes ? (
								<Check className="h-4 w-4 text-emerald-500" />
							) : (
								<Copy className="h-4 w-4" />
							)}
							{copiedBackupCodes
								? t("common:copied", "Copied!")
								: t("twoFactor.btnCopyCodes", "Copy All Codes")}
						</Button>
						<Button
							type="button"
							onClick={() => setIsBackupCodesOpen(false)}
						>
							{t("twoFactor.btnSavedDone", "I've Saved Them")}
						</Button>
					</DialogFooter>
				</DialogContent>
			</Dialog>

			{/* Modal: Disable 2FA */}
			<Dialog open={isDisableOpen} onOpenChange={setIsDisableOpen}>
				<DialogContent className="sm:max-w-md">
					<DialogHeader>
						<DialogTitle className="flex items-center gap-2 text-destructive">
							<AlertTriangle className="h-5 w-5" />
							{t("twoFactor.modalDisableTitle", "Disable Two-Factor Authentication")}
						</DialogTitle>
						<DialogDescription>
							{t(
								"twoFactor.modalDisableDesc",
								"To disable 2FA, enter your current 6-digit authenticator code (or account password).",
							)}
						</DialogDescription>
					</DialogHeader>

					<div className="space-y-4 py-2">
						<div className="space-y-2">
							<Label htmlFor="disable-code">
								{t("twoFactor.codeOrBackupLabel", "Authenticator or Backup Code")}
							</Label>
							<Input
								id="disable-code"
								placeholder="123456 or XXXX-XXXX"
								value={disableCode}
								onChange={(e) => setDisableCode(e.target.value)}
								autoComplete="off"
							/>
						</div>
						<div className="text-xs text-center text-muted-foreground">— {t("common:or", "OR")} —</div>
						<div className="space-y-2">
							<Label htmlFor="disable-password">
								{t("twoFactor.accountPasswordLabel", "Account Password")}
							</Label>
							<Input
								id="disable-password"
								type="password"
								placeholder="••••••••"
								value={disablePassword}
								onChange={(e) => setDisablePassword(e.target.value)}
							/>
						</div>
					</div>

					<DialogFooter className="sm:justify-between gap-2">
						<Button
							type="button"
							variant="outline"
							onClick={() => setIsDisableOpen(false)}
						>
							{t("common:cancel", "Cancel")}
						</Button>
						<Button
							type="button"
							variant="destructive"
							onClick={handleDisable}
							disabled={(!disableCode && !disablePassword) || disableMutation.isPending}
							className="gap-2"
						>
							{disableMutation.isPending && (
								<Loader2 className="h-4 w-4 animate-spin" />
							)}
							{t("twoFactor.btnConfirmDisable", "Confirm Disable")}
						</Button>
					</DialogFooter>
				</DialogContent>
			</Dialog>

			{/* Modal: Regenerate Backup Codes */}
			<Dialog open={isRegenerateOpen} onOpenChange={setIsRegenerateOpen}>
				<DialogContent className="sm:max-w-md">
					<DialogHeader>
						<DialogTitle className="flex items-center gap-2">
							<RefreshCw className="h-5 w-5 text-primary" />
							{t("twoFactor.modalRegenTitle", "Regenerate Backup Codes")}
						</DialogTitle>
						<DialogDescription>
							{t(
								"twoFactor.modalRegenDesc",
								"This will invalidate all previously generated backup recovery codes. Enter your current 6-digit TOTP code to confirm.",
							)}
						</DialogDescription>
					</DialogHeader>

					<div className="space-y-2 py-4 flex flex-col items-center">
						<Label className="text-sm font-medium">
							{t("twoFactor.enterCodeLabel", "Enter 6-digit code from app")}
						</Label>
						<InputOTP
							maxLength={6}
							value={regenCode}
							onChange={(val) => setRegenCode(val)}
						>
							<InputOTPGroup>
								<InputOTPSlot index={0} />
								<InputOTPSlot index={1} />
								<InputOTPSlot index={2} />
								<InputOTPSlot index={3} />
								<InputOTPSlot index={4} />
								<InputOTPSlot index={5} />
							</InputOTPGroup>
						</InputOTP>
					</div>

					<DialogFooter className="sm:justify-between gap-2">
						<Button
							type="button"
							variant="outline"
							onClick={() => setIsRegenerateOpen(false)}
						>
							{t("common:cancel", "Cancel")}
						</Button>
						<Button
							type="button"
							onClick={handleRegenerateCodes}
							disabled={regenCode.length !== 6 || regenerateMutation.isPending}
							className="gap-2"
						>
							{regenerateMutation.isPending && (
								<Loader2 className="h-4 w-4 animate-spin" />
							)}
							{t("twoFactor.btnRegenConfirm", "Generate New Codes")}
						</Button>
					</DialogFooter>
				</DialogContent>
			</Dialog>
		</>
	);
};
