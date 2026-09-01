import React, { useState } from "react";
import { useTranslation } from "react-i18next";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  useWalletNonce,
  useWalletVerify,
  useWalletStatus,
  useDisconnectWallet,
} from "@/lib/api";
import {
  ShieldCheck,
  ShieldAlert,
  Wallet,
  CheckCircle2,
  Loader2,
  LogOut,
  ExternalLink,
  Copy,
  Check,
} from "lucide-react";
import { toast } from "sonner";

interface NodeWalletModalProps {
  isOpen: boolean;
  onClose: () => void;
  onWalletActivated: () => void;
}

export const NodeWalletModal: React.FC<NodeWalletModalProps> = ({
  isOpen,
  onClose,
  onWalletActivated,
}) => {
  const { t } = useTranslation(["mining", "common"]);
  const [isConnecting, setIsConnecting] = useState(false);
  const [copied, setCopied] = useState(false);

  const { data: walletStatus, isLoading: isStatusLoading } = useWalletStatus();
  const getNonceMutation = useWalletNonce();
  const verifyWalletMutation = useWalletVerify();
  const disconnectMutation = useDisconnectWallet();

  const isWalletConfigured = walletStatus?.walletConfigured;
  const currentAddress = walletStatus?.walletAddress;

  const handleConnectWallet = async () => {
    if (typeof window === "undefined" || !(window as any).ethereum) {
      toast.error(
        t(
          "metaMaskNotFound",
          "Web3 Wallet (MetaMask) not detected. Please install MetaMask browser extension or use Web3 browser."
        )
      );
      return;
    }

    setIsConnecting(true);
    try {
      const ethereum = (window as any).ethereum;

      // 1. Request user's EVM account
      const accounts = await ethereum.request({
        method: "eth_requestAccounts",
      });

      if (!accounts || accounts.length === 0) {
        toast.error(t("noAccountSelected", "No EVM account selected."));
        setIsConnecting(false);
        return;
      }

      const address = accounts[0];

      // 2. Fetch SIWE Nonce from backend
      const nonceRes = await getNonceMutation.mutateAsync({ address });
      const { nonce, message } = nonceRes;

      // 3. Request personal signature from wallet
      const signature = await ethereum.request({
        method: "personal_sign",
        params: [message, address],
      });

      // 4. Verify signature on backend & bind identity
      await verifyWalletMutation.mutateAsync({
        address,
        signature,
        nonce,
        message,
      });

      toast.success(
        t(
          "walletConnectedSuccess",
          "Wallet verified & connected successfully!"
        )
      );
      onWalletActivated();
      onClose();
    } catch (err: any) {
      console.error("Wallet connection error:", err);
      const errMsg = err?.message || err?.detail || "Failed to connect wallet";
      if (err?.code === 4001) {
        toast.error(
          t("userRejectedSignature", "Signature request was rejected in wallet.")
        );
      } else {
        toast.error(errMsg);
      }
    } finally {
      setIsConnecting(false);
    }
  };

  const handleDisconnect = async () => {
    try {
      await disconnectMutation.mutateAsync();
      toast.success(t("walletDisconnected", "Wallet disconnected successfully."));
    } catch (err: any) {
      toast.error(err?.message || "Failed to disconnect wallet");
    }
  };

  const copyAddress = () => {
    if (currentAddress) {
      navigator.clipboard.writeText(currentAddress);
      setCopied(true);
      toast.success(t("addressCopied", "Wallet address copied!"));
      setTimeout(() => setCopied(false), 2000);
    }
  };

  return (
    <Dialog open={isOpen} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="sm:max-w-lg bg-card border-border shadow-2xl rounded-2xl p-6 overflow-hidden">
        <DialogHeader className="space-y-2">
          <div className="flex items-center gap-3">
            <div className="p-2.5 rounded-xl bg-primary/10 text-primary border border-primary/20">
              <Wallet className="w-6 h-6" />
            </div>
            <div>
              <DialogTitle className="text-xl font-bold text-foreground">
                {t("walletTitle", "Node Web3 Identity (EVM Wallet)")}
              </DialogTitle>
              <DialogDescription className="text-xs text-muted-foreground">
                {t(
                  "walletSubtitle",
                  "Connect your EVM wallet (MetaMask / Web3) to secure your mining rewards and node identity."
                )}
              </DialogDescription>
            </div>
          </div>
        </DialogHeader>

        <div className="py-4 space-y-4">
          <div className="p-3.5 rounded-xl bg-primary/5 border border-primary/20 flex items-start gap-3">
            <ShieldCheck className="w-5 h-5 text-primary shrink-0 mt-0.5" />
            <p className="text-xs text-muted-foreground leading-relaxed">
              {t(
                "walletNoticeEVM",
                "Your private key never leaves your wallet. Server verifies ownership via cryptographically signed message. Rewards and node migration remain 100% under your control."
              )}
            </p>
          </div>

          {isStatusLoading ? (
            <div className="flex items-center justify-center py-8">
              <Loader2 className="w-6 h-6 animate-spin text-primary" />
            </div>
          ) : isWalletConfigured && currentAddress ? (
            <div className="space-y-4 pt-2">
              <div className="p-4 rounded-xl bg-emerald-500/10 border border-emerald-500/30 flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <CheckCircle2 className="w-6 h-6 text-emerald-400 shrink-0" />
                  <div>
                    <div className="text-xs font-semibold text-foreground flex items-center gap-2">
                      <span>
                        {t("connectedWallet", "Connected Web3 Wallet")}
                      </span>
                      <Badge
                        variant="outline"
                        className="text-[9px] bg-emerald-500/20 text-emerald-400 border-emerald-500/30"
                      >
                        EVM
                      </Badge>
                    </div>
                    <div className="font-mono text-sm font-bold text-emerald-300 mt-0.5">
                      {currentAddress.slice(0, 8)}...{currentAddress.slice(-6)}
                    </div>
                  </div>
                </div>
                <Button
                  variant="ghost"
                  size="icon"
                  onClick={copyAddress}
                  className="h-8 w-8 text-muted-foreground hover:text-foreground"
                >
                  {copied ? (
                    <Check className="w-4 h-4 text-emerald-400" />
                  ) : (
                    <Copy className="w-4 h-4" />
                  )}
                </Button>
              </div>

              <div className="flex items-center justify-between text-xs text-muted-foreground font-mono px-1">
                <span>Node UUID:</span>
                <span className="text-foreground font-bold">
                  {walletStatus?.nodeUuid?.slice(0, 16)}...
                </span>
              </div>

              <div className="pt-3 flex gap-2">
                <Button
                  variant="outline"
                  size="sm"
                  onClick={handleConnectWallet}
                  disabled={isConnecting}
                  className="flex-1 text-xs gap-2 border-primary/30 text-primary hover:bg-primary/10"
                >
                  {isConnecting ? (
                    <Loader2 className="w-3.5 h-3.5 animate-spin" />
                  ) : (
                    <Wallet className="w-3.5 h-3.5" />
                  )}
                  {t("switchWallet", "Switch Wallet")}
                </Button>

                <Button
                  variant="destructive"
                  size="sm"
                  onClick={handleDisconnect}
                  disabled={disconnectMutation.isPending}
                  className="text-xs gap-1.5"
                >
                  <LogOut className="w-3.5 h-3.5" />
                  {t("disconnect", "Disconnect")}
                </Button>
              </div>
            </div>
          ) : (
            <div className="pt-2 space-y-3">
              <Button
                onClick={handleConnectWallet}
                disabled={isConnecting}
                className="w-full py-6 font-bold text-sm bg-gradient-to-r from-primary to-purple-600 hover:from-primary/95 hover:to-purple-600/95 shadow-lg shadow-primary/20 gap-3"
              >
                {isConnecting ? (
                  <>
                    <Loader2 className="w-5 h-5 animate-spin" />
                    <span>{t("signingMessage", "Signing Message...")}</span>
                  </>
                ) : (
                  <>
                    <Wallet className="w-5 h-5 fill-current" />
                    <span>{t("connectMetaMask", "Connect EVM Wallet (MetaMask)")}</span>
                  </>
                )}
              </Button>
            </div>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
};
