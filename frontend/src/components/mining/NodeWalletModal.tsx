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
  Wallet,
  CheckCircle2,
  Loader2,
  LogOut,
  Copy,
  Check,
} from "lucide-react";
import { toast } from "sonner";

// Minimal EIP-1193 surface used by this modal (MetaMask / injected Web3 wallets).
interface Eip1193Provider {
  request(args: { method: string; params?: unknown[] }): Promise<unknown>;
}

/** Returns the injected wallet provider, if the page runs in a Web3 browser. */
const getEthereumProvider = (): Eip1193Provider | undefined => {
  if (typeof window === "undefined") return undefined;
  return (window as Window & { ethereum?: Eip1193Provider }).ethereum;
};

/** Narrows an unknown catch value to the wallet error fields this modal reads. */
const parseWalletError = (
  error: unknown
): { code?: number; message?: string; detail?: string } => {
  if (error instanceof Error) return { message: error.message };
  if (error && typeof error === "object") {
    const candidate = error as {
      code?: unknown;
      message?: unknown;
      detail?: unknown;
    };
    return {
      code: typeof candidate.code === "number" ? candidate.code : undefined,
      message:
        typeof candidate.message === "string" ? candidate.message : undefined,
      detail:
        typeof candidate.detail === "string" ? candidate.detail : undefined,
    };
  }
  return {};
};

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
    const ethereum = getEthereumProvider();
    if (!ethereum) {
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
      // 1. Request user's EVM account
      const accounts = (await ethereum.request({
        method: "eth_requestAccounts",
      })) as string[] | null;

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
      const signature = (await ethereum.request({
        method: "personal_sign",
        params: [message, address],
      })) as string;

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
    } catch (err: unknown) {
      console.error("Wallet connection error:", err);
      const walletError = parseWalletError(err);
      const errMsg =
        walletError.message || walletError.detail || "Failed to connect wallet";
      if (walletError.code === 4001) {
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
    } catch (err: unknown) {
      toast.error(
        parseWalletError(err).message || "Failed to disconnect wallet"
      );
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
      <DialogContent className="sm:max-w-lg glass bg-[#0c121e]/90 border border-white/10 shadow-2xl rounded-2xl p-6 overflow-hidden backdrop-blur-xl">
        <div className="absolute -top-16 -right-16 w-48 h-48 rounded-full bg-cyan-500/10 blur-3xl pointer-events-none" />
        <DialogHeader className="space-y-2 relative">
          <div className="flex items-center gap-3">
            <div className="p-2.5 rounded-xl bg-cyan-500/10 text-cyan-400 border border-cyan-500/20">
              <Wallet className="w-6 h-6" />
            </div>
            <div>
              <DialogTitle className="text-xl font-bold text-white">
                {t("walletTitle", "Node Web3 Identity (EVM Wallet)")}
              </DialogTitle>
              <DialogDescription className="text-xs text-white/50">
                {t(
                  "walletSubtitle",
                  "Connect your EVM wallet (MetaMask / Web3) to secure your mining rewards and node identity."
                )}
              </DialogDescription>
            </div>
          </div>
        </DialogHeader>

        <div className="py-4 space-y-4 relative">
          <div className="p-3.5 rounded-xl bg-white/[0.03] border border-white/10 flex items-start gap-3">
            <ShieldCheck className="w-5 h-5 text-cyan-400 shrink-0 mt-0.5" />
            <p className="text-xs text-white/60 leading-relaxed">
              {t(
                "walletNoticeEVM",
                "Your private key never leaves your wallet. Server verifies ownership via cryptographically signed message. Rewards and node migration remain 100% under your control."
              )}
            </p>
          </div>

          {isStatusLoading ? (
            <div className="flex items-center justify-center py-8">
              <Loader2 className="w-6 h-6 animate-spin text-cyan-400" />
            </div>
          ) : isWalletConfigured && currentAddress ? (
            <div className="space-y-4 pt-2">
              <div className="p-4 rounded-xl bg-emerald-500/10 border border-emerald-500/30 flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <CheckCircle2 className="w-6 h-6 text-emerald-400 shrink-0" />
                  <div>
                    <div className="text-xs font-semibold text-white flex items-center gap-2">
                      <span>
                        {t("connectedWallet", "Connected Web3 Wallet")}
                      </span>
                      <Badge
                        variant="outline"
                        className="text-[9px] bg-emerald-500/20 text-emerald-400 border-emerald-500/30 font-mono"
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
                  className="h-8 w-8 text-white/60 hover:text-white hover:bg-white/10 rounded-lg"
                >
                  {copied ? (
                    <Check className="w-4 h-4 text-emerald-400" />
                  ) : (
                    <Copy className="w-4 h-4" />
                  )}
                </Button>
              </div>

              <div className="flex items-center justify-between text-xs text-white/50 font-mono px-1">
                <span>Node UUID:</span>
                <span className="text-white font-bold">
                  {walletStatus?.nodeUuid?.slice(0, 16)}...
                </span>
              </div>

              <div className="pt-3 flex gap-2">
                <Button
                  variant="outline"
                  size="sm"
                  onClick={handleConnectWallet}
                  disabled={isConnecting}
                  className="flex-1 text-xs gap-2 rounded-xl border-cyan-500/30 text-cyan-300 hover:bg-cyan-500/10"
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
                  className="text-xs gap-1.5 rounded-xl bg-rose-500/20 text-rose-300 border border-rose-500/30 hover:bg-rose-500/30"
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
                className="w-full py-5 rounded-xl font-bold text-sm bg-gradient-to-r from-cyan-400 to-blue-500 hover:from-cyan-300 hover:to-blue-400 text-slate-950 shadow-lg shadow-cyan-500/20 gap-3 transition-all"
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
