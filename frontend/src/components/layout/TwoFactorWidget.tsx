// src/components/layout/TwoFactorWidget.tsx

import React, { useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import {
  ShieldCheck,
  ShieldAlert,
  Loader2,
  Copy,
  Check,
  Settings as SettingsIcon,
  AlertTriangle,
  ExternalLink,
} from "lucide-react";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { InputOTP, InputOTPGroup, InputOTPSlot } from "@/components/ui/input-otp";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useToast } from "@/components/ui/use-toast";
import {
  useTotpStatus,
  useSetupTotp,
  useConfirmTotp,
  useDisableTotp,
} from "@/lib/api";
import type { TotpConfirmResponse, TotpSetupResponse } from "@/types/api";
import { cn } from "@/lib/utils";

interface TwoFactorWidgetProps {
  isExpanded?: boolean;
}

type TotpSetupWithSnake = TotpSetupResponse & {
  qr_code?: string;
  manual_entry_key?: string;
};

type TotpConfirmWithSnake = TotpConfirmResponse & {
  backup_codes?: string[];
};

export const TwoFactorWidget: React.FC<TwoFactorWidgetProps> = ({ isExpanded = true }) => {
  const { t } = useTranslation(["common", "account"]);
  const navigate = useNavigate();
  const { toast } = useToast();

  const { data: statusData, isLoading: isLoadingStatus } = useTotpStatus();
  const isTotpEnabled = statusData?.isTotpEnabled ?? false;
  const remainingCodes = statusData?.remainingBackupCodesCount ?? 0;

  // Popover state
  const [isPopoverOpen, setIsPopoverOpen] = useState(false);

  // Setup modal state
  const [isSetupOpen, setIsSetupOpen] = useState(false);
  const [setupData, setSetupData] = useState<TotpSetupResponse | null>(null);
  const [confirmCode, setConfirmCode] = useState("");
  const [copiedKey, setCopiedKey] = useState(false);

  // Disable modal state
  const [isDisableOpen, setIsDisableOpen] = useState(false);
  const [disableCode, setDisableCode] = useState("");
  const [disablePassword, setDisablePassword] = useState("");

  // Backup codes modal state
  const [newBackupCodes, setNewBackupCodes] = useState<string[] | null>(null);
  const [isBackupCodesOpen, setIsBackupCodesOpen] = useState(false);
  const [copiedBackupCodes, setCopiedBackupCodes] = useState(false);

  // Mutations
  const setupMutation = useSetupTotp();
  const confirmMutation = useConfirmTotp();
  const disableMutation = useDisableTotp();

  const handleStartSetup = async () => {
    setIsPopoverOpen(false);
    setIsSetupOpen(true);
    setConfirmCode("");
    setSetupData(null);
    try {
      const res = await setupMutation.mutateAsync();
      setSetupData(res);
    } catch (err: unknown) {
      setIsSetupOpen(false);
      toast({
        variant: "destructive",
        title: t("account:twoFactor.setupErrorTitle", "Setup Failed"),
        description:
          (err as Error)?.message ||
          t("account:twoFactor.setupErrorDesc", "Could not start 2FA setup."),
      });
    }
  };

  const handleConfirmSetup = async () => {
    const secret = setupData?.secret;
    if (!secret || confirmCode.length !== 6) return;

    try {
      const res = await confirmMutation.mutateAsync({
        secret,
        code: confirmCode,
      });
      setIsSetupOpen(false);
      setSetupData(null);
      setConfirmCode("");

      const codes = res.backupCodes || (res as TotpConfirmWithSnake)?.backup_codes;
      if (codes?.length) {
        setNewBackupCodes(codes);
        setIsBackupCodesOpen(true);
      }

      toast({
        title: t("account:twoFactor.enabledTitle", "2FA Enabled"),
        description: t(
          "account:twoFactor.enabledDesc",
          "Two-Factor Authentication is now active on your account.",
        ),
      });
    } catch (err: unknown) {
      toast({
        variant: "destructive",
        title: t("account:twoFactor.confirmErrorTitle", "Verification Failed"),
        description:
          (err as Error)?.message ||
          t("account:twoFactor.confirmErrorDesc", "Invalid code. Please try again."),
      });
    }
  };

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
        title: t("account:twoFactor.disabledTitle", "2FA Disabled"),
        description: t(
          "account:twoFactor.disabledDesc",
          "Two-Factor Authentication has been removed.",
        ),
      });
    } catch (err: unknown) {
      toast({
        variant: "destructive",
        title: t("account:twoFactor.disableErrorTitle", "Disable Failed"),
        description:
          (err as Error)?.message ||
          t(
            "account:twoFactor.disableErrorDesc",
            "Invalid code or password. Please verify and retry.",
          ),
      });
    }
  };

  const copySecret = () => {
    const key =
      setupData?.manualEntryKey ||
      (setupData as TotpSetupWithSnake)?.manual_entry_key ||
      setupData?.secret ||
      "";
    if (!key) return;
    navigator.clipboard.writeText(key);
    setCopiedKey(true);
    setTimeout(() => setCopiedKey(false), 2000);
    toast({
      description: t(
        "account:twoFactor.keyCopiedDesc",
        "Secret key copied to clipboard.",
      ),
    });
  };

  const copyBackupCodes = () => {
    if (!newBackupCodes?.length) return;
    navigator.clipboard.writeText(newBackupCodes.join("\n"));
    setCopiedBackupCodes(true);
    setTimeout(() => setCopiedBackupCodes(false), 2000);
    toast({
      description: t("copiedToClipboard", "copied to clipboard."),
    });
  };

  return (
    <>
      <Popover open={isPopoverOpen} onOpenChange={setIsPopoverOpen}>
        <Tooltip>
          <TooltipTrigger asChild>
            <PopoverTrigger asChild>
              <button
                type="button"
                className={cn(
                  "relative flex items-center justify-center rounded-lg border font-mono text-[11px] font-bold transition-all shadow-sm focus:outline-none",
                  isExpanded ? "h-8 px-2 gap-1.5" : "h-8 w-8",
                  isLoadingStatus
                    ? "border-white/10 bg-white/5 text-white/40"
                    : isTotpEnabled
                      ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-400 hover:bg-emerald-500/20 shadow-[0_0_10px_-2px_rgba(16,185,129,0.3)]"
                      : "border-rose-500/30 bg-rose-500/10 text-rose-400 hover:bg-rose-500/20 shadow-[0_0_10px_-2px_rgba(244,63,94,0.3)]",
                )}
                aria-label="2FA Status"
              >
                {isLoadingStatus ? (
                  <Loader2 size={14} className="animate-spin text-white/40" />
                ) : isTotpEnabled ? (
                  <ShieldCheck size={14} className="text-emerald-400 shrink-0" />
                ) : (
                  <ShieldAlert size={14} className="text-rose-400 shrink-0" />
                )}

                {isExpanded && <span>2FA</span>}

                <span
                  className={cn(
                    "rounded-full shrink-0",
                    isExpanded ? "h-1.5 w-1.5" : "absolute top-1 right-1 h-1.5 w-1.5",
                    isLoadingStatus
                      ? "bg-white/30"
                      : isTotpEnabled
                        ? "bg-emerald-400 animate-pulse"
                        : "bg-rose-400",
                  )}
                />
              </button>
            </PopoverTrigger>
          </TooltipTrigger>
          <TooltipContent side="right">
            {isTotpEnabled
              ? t("twoFactorMenu.tooltipActive", "2FA: Active (click for menu)")
              : t("twoFactorMenu.tooltipDisabled", "2FA: Disabled (click for menu)")}
          </TooltipContent>
        </Tooltip>

        <PopoverContent
          side={isExpanded ? "top" : "right"}
          align={isExpanded ? "start" : "end"}
          sideOffset={8}
          className="w-72 sm:w-80 p-0 bg-popover/95 border border-border text-popover-foreground shadow-2xl backdrop-blur-2xl rounded-2xl overflow-hidden animate-fade-up z-50"
        >
          {/* Header */}
          <div className="flex items-center justify-between p-3.5 border-b border-border/50 bg-muted/30">
            <div className="flex items-center gap-2.5">
              <div
                className={cn(
                  "p-2 rounded-xl border flex items-center justify-center shrink-0",
                  isTotpEnabled
                    ? "bg-emerald-500/10 border-emerald-500/20 text-emerald-600 dark:text-emerald-400"
                    : "bg-rose-500/10 border-rose-500/20 text-rose-600 dark:text-rose-400",
                )}
              >
                {isTotpEnabled ? (
                  <ShieldCheck className="h-4 w-4" />
                ) : (
                  <ShieldAlert className="h-4 w-4" />
                )}
              </div>
              <div className="min-w-0">
                <h4 className="text-[13px] font-bold text-foreground leading-tight truncate">
                  {t("twoFactorMenu.title", "2FA Security")}
                </h4>
                <p className="text-[10.5px] text-muted-foreground mt-0.5 truncate">
                  {isTotpEnabled
                    ? t("twoFactorMenu.protected", "Account Protected")
                    : t("twoFactorMenu.notProtected", "Not Protected")}
                </p>
              </div>
            </div>

            <Badge
              className={cn(
                "font-mono text-[9.5px] font-bold uppercase tracking-wider px-2 py-0.5 rounded-md shrink-0",
                isTotpEnabled
                  ? "bg-emerald-500/15 text-emerald-600 dark:text-emerald-400 border border-emerald-500/30"
                  : "bg-rose-500/15 text-rose-600 dark:text-rose-400 border border-rose-500/30",
              )}
            >
              {isTotpEnabled ? "ON" : "OFF"}
            </Badge>
          </div>

          {/* Body Content */}
          <div className="p-3.5 space-y-3">
            {isTotpEnabled ? (
              <>
                <div className="rounded-xl border border-border/70 bg-muted/30 p-2.5 flex items-center justify-between">
                  <span className="text-xs text-muted-foreground">
                    {t("account:twoFactor.recoveryCodesCountLabel", "Backup Codes:")}
                  </span>
                  <span
                    className={cn(
                      "font-mono text-xs font-bold px-2 py-0.5 rounded-md border",
                      remainingCodes > 2
                        ? "border-border/70 bg-card text-foreground"
                        : "border-rose-500/30 bg-rose-500/10 text-rose-600 dark:text-rose-400",
                    )}
                  >
                    {remainingCodes} {t("account:twoFactor.remaining", "remaining")}
                  </span>
                </div>

                <div className="flex flex-col gap-1.5 pt-0.5">
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => {
                      setIsPopoverOpen(false);
                      navigate("/account?tab=security");
                    }}
                    className="w-full h-8 text-xs font-semibold rounded-xl border border-border bg-card hover:bg-muted text-foreground justify-between shadow-sm"
                  >
                    <span className="flex items-center gap-1.5">
                      <SettingsIcon className="h-3.5 w-3.5 text-cyan" />
                      {t("twoFactorMenu.manageInProfile", "Security Settings")}
                    </span>
                    <ExternalLink className="h-3 w-3 text-muted-foreground" />
                  </Button>

                  <Button
                    variant="destructive"
                    size="sm"
                    onClick={() => {
                      setIsPopoverOpen(false);
                      setIsDisableOpen(true);
                    }}
                    className="w-full h-8 text-xs font-semibold rounded-xl border border-rose-500/30 bg-rose-500/10 hover:bg-rose-500/20 text-rose-600 dark:text-rose-400"
                  >
                    {t("twoFactorMenu.disable", "Disable 2FA")}
                  </Button>
                </div>
              </>
            ) : (
              <>
                <div className="rounded-xl border border-rose-500/20 bg-rose-500/[0.04] p-3 text-[11px] text-muted-foreground leading-relaxed flex items-start gap-2.5">
                  <ShieldAlert className="h-4 w-4 text-rose-500 dark:text-rose-400 shrink-0 mt-0.5" />
                  <div>
                    <span className="font-semibold text-foreground block mb-0.5">
                      {t("account:twoFactor.recommendationTitle", "Highly Recommended")}
                    </span>
                    {t(
                      "account:twoFactor.recommendationText",
                      "Enabling 2FA protects your trading bots, exchange balances, and withdrawal settings.",
                    )}
                  </div>
                </div>

                <div className="flex flex-col gap-1.5 pt-0.5">
                  <Button
                    size="sm"
                    onClick={handleStartSetup}
                    disabled={setupMutation.isPending}
                    className="w-full h-8 text-xs font-semibold rounded-xl bg-gradient-to-r from-azure to-cyan text-white shadow-[0_0_15px_-3px_rgba(0,212,255,0.5)] hover:brightness-110"
                  >
                    {setupMutation.isPending ? (
                      <Loader2 className="h-3.5 w-3.5 animate-spin mr-1.5" />
                    ) : (
                      <ShieldCheck className="h-3.5 w-3.5 mr-1.5" />
                    )}
                    {t("twoFactorMenu.setupNow", "Set Up 2FA")}
                  </Button>

                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => {
                      setIsPopoverOpen(false);
                      navigate("/account?tab=security");
                    }}
                    className="w-full h-8 text-xs text-muted-foreground hover:text-foreground"
                  >
                    {t("twoFactorMenu.learnMore", "Learn More")}
                  </Button>
                </div>
              </>
            )}
          </div>
        </PopoverContent>
      </Popover>

      {/* Setup 2FA Modal */}
      <Dialog open={isSetupOpen} onOpenChange={setIsSetupOpen}>
        <DialogContent className="sm:max-w-md bg-obsidian/95 border border-white/10 text-white shadow-2xl backdrop-blur-2xl rounded-2xl p-6">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2 text-base text-white">
              <ShieldCheck className="h-4 w-4 text-cyan" />
              {t("account:twoFactor.modalSetupTitle", "Set Up Two-Factor Authentication")}
            </DialogTitle>
            <DialogDescription className="text-xs text-white/50">
              {t(
                "account:twoFactor.modalSetupDesc",
                "Scan the QR code with your authenticator app (Google Authenticator, Aegis, 1Password), then enter the 6-digit verification code.",
              )}
            </DialogDescription>
          </DialogHeader>

          {!setupData || setupMutation.isPending ? (
            <div className="flex flex-col items-center justify-center py-12 space-y-3">
              <Loader2 className="h-8 w-8 animate-spin text-cyan" />
              <p className="text-xs text-white/50">
                {t("account:twoFactor.generatingSetup", "Generating QR code...")}
              </p>
            </div>
          ) : (
            <div className="space-y-4 py-2">
              <div className="flex flex-col items-center justify-center p-3.5 bg-white rounded-2xl shadow-xl border border-white/20 mx-auto max-w-[210px]">
                <img
                  src={setupData.qrCode || (setupData as TotpSetupWithSnake).qr_code}
                  alt="2FA QR Code"
                  className="w-40 h-40 object-contain rounded-lg"
                />
              </div>

              <div className="space-y-1.5 rounded-xl border border-white/10 bg-white/[0.03] p-3">
                <div className="flex items-center justify-between text-[11px] text-white/40 font-medium px-1">
                  <span>{t("account:twoFactor.manualKeyLabel", "Can't scan? Enter manually:")}</span>
                  <span className="text-[10px] text-cyan/80">
                    {t("account:twoFactor.clickToCopy", "Click to copy")}
                  </span>
                </div>

                <div
                  onClick={copySecret}
                  className="group cursor-pointer rounded-lg bg-black/40 border border-white/10 p-2.5 flex items-center justify-between gap-2 hover:border-cyan/50 transition"
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
                    className="shrink-0 h-7 px-2 text-xs text-white/60 pointer-events-none"
                  >
                    {copiedKey ? (
                      <Check className="h-3.5 w-3.5 text-emerald-400" />
                    ) : (
                      <Copy className="h-3.5 w-3.5" />
                    )}
                  </Button>
                </div>
              </div>

              <div className="space-y-2 text-center pt-1">
                <Label className="text-xs font-semibold text-white/70">
                  {t("account:twoFactor.enterCodeLabel", "Enter 6-digit code from app")}
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

          <DialogFooter className="gap-2 sm:gap-0 pt-2">
            <Button
              type="button"
              variant="ghost"
              onClick={() => setIsSetupOpen(false)}
              className="text-xs text-white/60 hover:text-white"
            >
              {t("cancel", "Cancel")}
            </Button>
            <Button
              type="button"
              onClick={handleConfirmSetup}
              disabled={confirmCode.length !== 6 || confirmMutation.isPending}
              className="rounded-xl bg-gradient-to-r from-azure to-cyan text-white text-xs font-semibold px-4 h-9 shadow-[0_0_15px_-3px_rgba(0,212,255,0.5)] disabled:opacity-50"
            >
              {confirmMutation.isPending && (
                <Loader2 className="h-3.5 w-3.5 animate-spin mr-1.5" />
              )}
              {t("account:twoFactor.btnConfirmAndEnable", "Confirm and Enable")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Disable 2FA Modal */}
      <Dialog open={isDisableOpen} onOpenChange={setIsDisableOpen}>
        <DialogContent className="sm:max-w-md bg-obsidian/95 border border-white/10 text-white shadow-2xl backdrop-blur-2xl rounded-2xl p-6">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2 text-base text-rose-400">
              <AlertTriangle className="h-4 w-4" />
              {t("account:twoFactor.modalDisableTitle", "Disable Two-Factor Authentication")}
            </DialogTitle>
            <DialogDescription className="text-xs text-white/50">
              {t(
                "account:twoFactor.modalDisableDesc",
                "To disable 2FA, enter your current 6-digit authenticator code (or account password).",
              )}
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-4 py-2">
            <div className="space-y-1.5">
              <Label className="text-xs font-medium text-white/70">
                {t("account:twoFactor.codeOrBackupLabel", "Code from app or backup code")}
              </Label>
              <Input
                type="text"
                placeholder="123456"
                value={disableCode}
                onChange={(e) => setDisableCode(e.target.value)}
                className="font-mono text-center tracking-widest text-sm bg-white/[0.04] border-white/10 text-white rounded-xl"
              />
            </div>

            <div className="flex items-center gap-2 text-[11px] text-white/30 uppercase tracking-wider justify-center">
              <span>— {t("or", "or")} —</span>
            </div>

            <div className="space-y-1.5">
              <Label className="text-xs font-medium text-white/70">
                {t("account:twoFactor.accountPasswordLabel", "Account Password")}
              </Label>
              <Input
                type="password"
                placeholder="••••••••"
                value={disablePassword}
                onChange={(e) => setDisablePassword(e.target.value)}
                className="bg-white/[0.04] border-white/10 text-white text-xs rounded-xl"
              />
            </div>
          </div>

          <DialogFooter className="gap-2 sm:gap-0 pt-2">
            <Button
              type="button"
              variant="ghost"
              onClick={() => setIsDisableOpen(false)}
              className="text-xs text-white/60 hover:text-white"
            >
              {t("cancel", "Cancel")}
            </Button>
            <Button
              type="button"
              variant="destructive"
              onClick={handleDisable}
              disabled={(!disableCode.trim() && !disablePassword) || disableMutation.isPending}
              className="rounded-xl border border-rose-500/30 bg-rose-500/10 hover:bg-rose-500/20 text-rose-400 text-xs font-semibold px-4 h-9"
            >
              {disableMutation.isPending && (
                <Loader2 className="h-3.5 w-3.5 animate-spin mr-1.5" />
              )}
              {t("account:twoFactor.btnConfirmDisable", "Confirm Disable")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Backup Codes Display Modal */}
      <Dialog open={isBackupCodesOpen} onOpenChange={setIsBackupCodesOpen}>
        <DialogContent className="sm:max-w-md bg-obsidian/95 border border-white/10 text-white shadow-2xl backdrop-blur-2xl rounded-2xl p-6">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2 text-base text-amber-400">
              <AlertTriangle className="h-4 w-4" />
              {t("account:twoFactor.modalBackupCodesTitle", "Save Your Backup Codes")}
            </DialogTitle>
            <DialogDescription className="text-xs text-white/50">
              {t(
                "account:twoFactor.modalBackupCodesDesc",
                "If you lose access to your authenticator app, these single-use codes are the only way to recover access.",
              )}
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-4 py-2">
            <div className="grid grid-cols-2 gap-2 p-3.5 bg-black/40 rounded-xl border border-white/10">
              {newBackupCodes?.map((code, idx) => (
                <div
                  key={idx}
                  className="font-mono text-xs font-semibold text-cyan text-center py-1 px-2 rounded bg-white/[0.03] border border-white/5"
                >
                  {code}
                </div>
              ))}
            </div>

            <Button
              type="button"
              variant="outline"
              onClick={copyBackupCodes}
              className="w-full rounded-xl border-white/10 bg-white/[0.03] hover:bg-white/[0.08] text-white text-xs h-9 gap-2"
            >
              {copiedBackupCodes ? (
                <Check className="h-3.5 w-3.5 text-emerald-400" />
              ) : (
                <Copy className="h-3.5 w-3.5" />
              )}
              {copiedBackupCodes
                ? t("copied", "Copied!")
                : t("account:twoFactor.btnCopyCodes", "Copy All Codes")}
            </Button>
          </div>

          <DialogFooter className="pt-2">
            <Button
              type="button"
              onClick={() => setIsBackupCodesOpen(false)}
              className="w-full rounded-xl bg-gradient-to-r from-azure to-cyan text-white text-xs font-semibold h-9"
            >
              {t("account:twoFactor.btnSavedDone", "I Have Saved My Codes")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
};

export default TwoFactorWidget;
