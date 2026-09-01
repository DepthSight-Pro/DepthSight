import React, { useState, useEffect } from "react";
import { useTranslation } from "react-i18next";
import { api } from "../services/api";
import {
  Wallet,
  ShieldCheck,
  ShieldAlert,
  CheckCircle2,
  Copy,
  Check,
  Loader2,
  X,
  LogOut,
} from "lucide-react";

interface NodeWalletBottomSheetProps {
  isOpen: boolean;
  onClose: () => void;
  onWalletActivated: () => void;
}

export const NodeWalletBottomSheet: React.FC<NodeWalletBottomSheetProps> = ({
  isOpen,
  onClose,
  onWalletActivated,
}) => {
  const { t } = useTranslation("pwa-common");
  const [isConnecting, setIsConnecting] = useState(false);
  const [isDisconnecting, setIsDisconnecting] = useState(false);
  const [copied, setCopied] = useState(false);
  const [errorMsg, setErrorMsg] = useState("");
  const [walletStatus, setWalletStatus] = useState<{
    walletAddress?: string;
    nodeUuid?: string;
    walletConfigured: boolean;
  }>({ walletConfigured: false });
  const [isLoadingStatus, setIsLoadingStatus] = useState(false);

  const fetchStatus = () => {
    setIsLoadingStatus(true);
    api
      .getWalletStatus()
      .then((res: any) => {
        setWalletStatus({
          walletAddress: res?.wallet_address ?? res?.walletAddress,
          nodeUuid: res?.node_uuid ?? res?.nodeUuid,
          walletConfigured: Boolean(res?.wallet_configured ?? res?.walletConfigured),
        });
      })
      .catch((err) => {
        console.error("Wallet status error:", err);
      })
      .finally(() => {
        setIsLoadingStatus(false);
      });
  };

  useEffect(() => {
    if (isOpen) {
      setErrorMsg("");
      fetchStatus();
    }
  }, [isOpen]);

  if (!isOpen) return null;

  const handleConnectWallet = async () => {
    if (typeof window === "undefined" || !(window as any).ethereum) {
      setErrorMsg(
        t(
          "mining.metaMaskNotFound",
          "Web3 Wallet (MetaMask) not detected. Please install MetaMask browser extension or use Web3 browser."
        )
      );
      return;
    }

    setIsConnecting(true);
    setErrorMsg("");
    try {
      const ethereum = (window as any).ethereum;

      // 1. Request accounts
      const accounts = await ethereum.request({
        method: "eth_requestAccounts",
      });

      if (!accounts || accounts.length === 0) {
        setErrorMsg(t("mining.noAccountSelected", "No EVM account selected."));
        setIsConnecting(false);
        return;
      }

      const address = accounts[0];

      // 2. Fetch SIWE Nonce
      const nonceRes = await api.getWalletNonce(address);
      const { nonce, message } = nonceRes;

      // 3. Request signature from wallet
      const signature = await ethereum.request({
        method: "personal_sign",
        params: [message, address],
      });

      // 4. Verify signature & bind node
      await api.verifyWalletSignature(address, signature, nonce, message);

      onWalletActivated();
      fetchStatus();
      onClose();
    } catch (err: any) {
      console.error("PWA Wallet connection error:", err);
      if (err?.code === 4001) {
        setErrorMsg(
          t(
            "mining.userRejectedSignature",
            "Signature request was rejected in wallet."
          )
        );
      } else {
        setErrorMsg(err?.message || err?.detail || "Failed to connect wallet");
      }
    } finally {
      setIsConnecting(false);
    }
  };

  const handleDisconnect = async () => {
    setIsDisconnecting(true);
    try {
      await api.disconnectWallet();
      fetchStatus();
    } catch (err: any) {
      setErrorMsg(err?.message || "Failed to disconnect wallet");
    } finally {
      setIsDisconnecting(false);
    }
  };

  const copyAddress = () => {
    if (walletStatus.walletAddress) {
      navigator.clipboard.writeText(walletStatus.walletAddress);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
  };

  return (
    <>
      {/* Backdrop */}
      <div
        className="fixed inset-0 bg-black/60 z-50 transition-opacity backdrop-blur-xs"
        onClick={onClose}
      />

      {/* Mobile Bottom Sheet Container */}
      <div className="fixed bottom-0 left-0 right-0 z-50 bg-[hsl(var(--card))] rounded-t-3xl border-t border-[hsl(var(--border))] shadow-2xl p-5 max-w-md mx-auto max-h-[90vh] overflow-y-auto animate-in slide-in-from-bottom duration-300">
        {/* Handle pill */}
        <div className="w-12 h-1.5 bg-[hsl(var(--border))] rounded-full mx-auto mb-4" />

        {/* Header */}
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-2.5">
            <div className="p-2 rounded-xl bg-[hsl(var(--primary))]/10 text-[hsl(var(--primary))] border border-[hsl(var(--primary))]/20">
              <Wallet className="w-5 h-5" />
            </div>
            <div>
              <h2 className="text-lg font-bold text-[hsl(var(--card-foreground))]">
                {t("mining.walletTitle", "Node Web3 Identity (EVM Wallet)")}
              </h2>
              <p className="text-xs text-[hsl(var(--muted-foreground))]">
                {t(
                  "mining.walletSubtitle",
                  "Connect your EVM wallet (MetaMask / Web3) to secure your mining rewards and node identity."
                )}
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-1.5 rounded-full text-[hsl(var(--muted-foreground))] hover:bg-[hsl(var(--secondary))]"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {errorMsg && (
          <div className="mb-4 p-3 rounded-xl bg-red-500/10 border border-red-500/20 text-red-400 text-xs flex items-center gap-2">
            <ShieldAlert className="w-4 h-4 shrink-0" />
            <span>{errorMsg}</span>
          </div>
        )}

        <div className="space-y-4">
          <div className="p-3.5 rounded-xl bg-[hsl(var(--primary))]/5 border border-[hsl(var(--primary))]/20 flex items-start gap-3">
            <ShieldCheck className="w-5 h-5 text-[hsl(var(--primary))] shrink-0 mt-0.5" />
            <p className="text-xs text-[hsl(var(--muted-foreground))] leading-relaxed">
              {t(
                "mining.walletNoticeEVM",
                "Your private key never leaves your wallet. Server verifies ownership via cryptographically signed message. Rewards and node migration remain 100% under your control."
              )}
            </p>
          </div>

          {isLoadingStatus ? (
            <div className="flex items-center justify-center py-8">
              <Loader2 className="w-6 h-6 animate-spin text-[hsl(var(--primary))]" />
            </div>
          ) : walletStatus.walletConfigured && walletStatus.walletAddress ? (
            <div className="space-y-4 pt-2">
              <div className="p-4 rounded-xl bg-emerald-500/10 border border-emerald-500/30 flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <CheckCircle2 className="w-6 h-6 text-emerald-400 shrink-0" />
                  <div>
                    <div className="text-xs font-semibold text-[hsl(var(--card-foreground))] flex items-center gap-2">
                      <span>
                        {t("mining.connectedWallet", "Connected Web3 Wallet")}
                      </span>
                      <span className="text-[9px] px-1.5 py-0.5 rounded bg-emerald-500/20 text-emerald-400 font-mono">
                        EVM
                      </span>
                    </div>
                    <div className="font-mono text-sm font-bold text-emerald-300 mt-0.5">
                      {walletStatus.walletAddress.slice(0, 8)}...
                      {walletStatus.walletAddress.slice(-6)}
                    </div>
                  </div>
                </div>
                <button
                  onClick={copyAddress}
                  className="p-2 rounded-lg hover:bg-[hsl(var(--secondary))] text-[hsl(var(--muted-foreground))]"
                >
                  {copied ? (
                    <Check className="w-4 h-4 text-emerald-400" />
                  ) : (
                    <Copy className="w-4 h-4" />
                  )}
                </button>
              </div>

              <div className="pt-2 flex gap-2">
                <button
                  onClick={handleConnectWallet}
                  disabled={isConnecting}
                  className="flex-1 py-3 px-4 rounded-xl font-bold text-xs bg-[hsl(var(--primary))]/10 text-[hsl(var(--primary))] border border-[hsl(var(--primary))]/30 flex items-center justify-center gap-2"
                >
                  {isConnecting ? (
                    <Loader2 className="w-4 h-4 animate-spin" />
                  ) : (
                    <Wallet className="w-4 h-4" />
                  )}
                  {t("mining.switchWallet", "Switch Wallet")}
                </button>

                <button
                  onClick={handleDisconnect}
                  disabled={isDisconnecting}
                  className="py-3 px-4 rounded-xl font-bold text-xs bg-red-500/10 text-red-400 border border-red-500/30 flex items-center justify-center gap-1.5"
                >
                  {isDisconnecting ? (
                    <Loader2 className="w-4 h-4 animate-spin" />
                  ) : (
                    <LogOut className="w-4 h-4" />
                  )}
                  {t("mining.disconnect", "Disconnect")}
                </button>
              </div>
            </div>
          ) : (
            <div className="pt-2">
              <button
                onClick={handleConnectWallet}
                disabled={isConnecting}
                className="w-full py-4 px-4 rounded-xl font-bold text-sm bg-gradient-to-r from-[hsl(var(--primary))] to-purple-600 hover:opacity-95 text-white shadow-lg flex items-center justify-center gap-3"
              >
                {isConnecting ? (
                  <>
                    <Loader2 className="w-5 h-5 animate-spin" />
                    <span>{t("mining.signingMessage", "Signing Message...")}</span>
                  </>
                ) : (
                  <>
                    <Wallet className="w-5 h-5" />
                    <span>
                      {t(
                        "mining.connectMetaMask",
                        "Connect EVM Wallet (MetaMask)"
                      )}
                    </span>
                  </>
                )}
              </button>
            </div>
          )}
        </div>
      </div>
    </>
  );
};
