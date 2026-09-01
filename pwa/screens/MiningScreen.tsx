// pwa/screens/MiningScreen.tsx

import React, { useState, useEffect } from "react";
import { useTranslation } from "react-i18next";
import { 
  Coins, 
  Flame, 
  Copy, 
  Check, 
  Lock, 
  ShieldCheck, 
  Loader2,
  Share2,
  Globe,
  Wallet,
  Info
} from "lucide-react";
import { api } from "../services/api";
import { Logo } from "../components/ui/logo";
import { NodeWalletBottomSheet } from "../components/NodeWalletBottomSheet";


const MiningScreen: React.FC = () => {
  const { t } = useTranslation("pwa-common");
  const [loading, setLoading] = useState(true);
  const [miningStatus, setMiningStatus] = useState<any>(null);
  const [referrerCode, setReferrerCode] = useState("");
  const [isActivating, setIsActivating] = useState(false);
  const [isDeactivating, setIsDeactivating] = useState(false);
  const [copiedCode, setCopiedCode] = useState(false);
  const [copiedLink, setCopiedLink] = useState(false);

  const fetchStatus = () => {
    setLoading(true);
    api.getMiningStatus()
      .then((res) => {
        if (res && res.data) {
          setMiningStatus(res.data);
        } else {
          setMiningStatus(res);
        }
      })
      .catch((err) => console.error("Failed to load mining status", err))
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    fetchStatus();
  }, []);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const urlRef = params.get("ref") || params.get("ref_code") || params.get("referrer_code");
    const localRef = localStorage.getItem("ref_code") || localStorage.getItem("referrer_code") || localStorage.getItem("ref");
    const apiRef = miningStatus?.referrerReferralCode || (miningStatus as any)?.referrer_referral_code;
    const foundCode = urlRef || localRef || apiRef || "";

    if (foundCode && !referrerCode) {
      setReferrerCode(foundCode);
    }
  }, [miningStatus]);

  const [isWalletOpen, setIsWalletOpen] = useState(false);

  const handleActivate = () => {
    setIsActivating(true);
    api.activateMining(referrerCode.trim() || undefined)
      .then((res) => {
        if (res && res.data) {
          setMiningStatus(res.data);
        } else {
          setMiningStatus(res);
        }
      })
      .catch((err: any) => {
        const msg = err?.message || String(err);
        if (msg.includes("WALLET_REQUIRED") || msg.includes("wallet")) {
          setIsWalletOpen(true);
        } else {
          console.error("Activation failed", err);
        }
      })
      .finally(() => setIsActivating(false));
  };

  const copyToClipboard = (text: string, isLink: boolean) => {
    navigator.clipboard.writeText(text);
    if (isLink) {
      setCopiedLink(true);
      setTimeout(() => setCopiedLink(false), 2000);
    } else {
      setCopiedCode(true);
      setTimeout(() => setCopiedCode(false), 2000);
    }
  };

  if (loading) {
    return (
      <div className="flex flex-col items-center justify-center min-h-[80vh]">
        <Logo size="xl" className="mb-8 animate-pulse" />
      </div>
    );
  }

  if (miningStatus?.isGlobalMiningEnabled === false) {
    return (
      <div className="flex flex-col items-center justify-center min-h-[50vh] p-6 text-center gap-3">
        <Lock className="w-12 h-12 text-[hsl(var(--muted-foreground))] opacity-60" />
        <h3 className="text-lg font-bold">{t("mining.disabledTitle", "Mining Disabled")}</h3>
        <p className="text-sm text-[hsl(var(--muted-foreground))] max-w-xs leading-normal">
          {t("mining.disabledDesc", "Mining features are temporarily disabled by the administrator.")}
        </p>
      </div>
    );
  }

  const isMiningActive = miningStatus?.isMiningEnabled;

  // Activation screen (if not enabled yet)
  if (!isMiningActive) {
    return (
      <div className="p-4 space-y-6 flex flex-col items-center justify-center min-h-[70vh]">
        <div className="text-center space-y-2">
          <div className="inline-flex p-3 rounded-full bg-[hsl(var(--primary))]/10 text-[hsl(var(--primary))] animate-bounce">
            <Coins className="w-12 h-12" />
          </div>
          <h2 className="text-2xl font-bold tracking-tight">
            {t("sideMenu.mining", "Trade Mining")}
          </h2>
          <p className="text-sm text-[hsl(var(--muted-foreground))] max-w-xs mx-auto">
            {t("mining.subtitle", "Share your trade telemetry and earn $DEPTH tokens on every trade.")}
          </p>
        </div>

        <div className="w-full max-w-sm rounded-2xl border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-5 space-y-5 shadow-sm">
          <div className="flex gap-3">
            <ShieldCheck className="w-6 h-6 text-emerald-500 shrink-0 mt-0.5" />
            <div className="space-y-1">
              <h4 className="text-sm font-semibold">{t("mining.privacyTitle", "What data is shared")}</h4>
              <p className="text-xs text-[hsl(var(--muted-foreground))] leading-relaxed">
                {t("mining.privacyDesc", "Required while Trade Mining is active: your closed trades (symbol, entry/exit prices, volume, PnL, duration, order IDs) and strategy parameters are shared with the Central Hub, linked to your node's wallet address and exchange UID. Your exchange API keys, passwords and asset balances are never transmitted. Disable by deactivating Trade Mining.")}
              </p>
            </div>
          </div>

          <div className="space-y-2">
            <label className="text-xs font-semibold text-[hsl(var(--muted-foreground))] uppercase tracking-wider block">
              {t("mining.enterReferrerCode", "Referrer Code (Optional)")}
            </label>
            <input
              type="text"
              placeholder="e.g. DSN-REF-XXXX-YYYY"
              value={referrerCode}
              onChange={(e) => setReferrerCode(e.target.value)}
              className="w-full text-sm rounded-lg bg-[hsl(var(--background))] border border-[hsl(var(--border))] p-3 text-[hsl(var(--foreground))] placeholder:text-[hsl(var(--muted-foreground))] focus:outline-none focus:border-[hsl(var(--primary))]"
            />
          </div>
          <div className="flex gap-2 p-3 rounded-xl bg-emerald-500/10 border border-emerald-500/20 text-emerald-500 text-[11px] leading-relaxed">
            <ShieldCheck className="w-4 h-4 shrink-0 mt-0.5" />
            <span>
              {t(
                "mining.uidLinkedNotice",
                "Your exchange UID will be resolved and linked automatically using your active API keys when you start mining."
              )}
            </span>
          </div>

          <button
            onClick={handleActivate}
            disabled={isActivating}
            className="w-full font-bold bg-[hsl(var(--primary))] text-[hsl(var(--primary-foreground))] rounded-xl py-3.5 flex items-center justify-center gap-2 hover:opacity-90 active:scale-[0.98] transition disabled:opacity-50 disabled:scale-100"
          >
            {isActivating ? (
              <>
                <Loader2 className="w-4 h-4 animate-spin" />
                {t("mining.activating", "Activating...")}
              </>
            ) : (
              <>
                <Flame className="w-5 h-5 fill-current" />
                {t("mining.activateButton", "Activate & Start Mining")}
              </>
            )}
          </button>

          <div className="pt-2 text-center">
            <button
              onClick={() => setIsWalletOpen(true)}
              className="text-xs text-[hsl(var(--muted-foreground))] hover:text-[hsl(var(--primary))] font-medium flex items-center justify-center gap-1.5 mx-auto py-1"
            >
              <Wallet className="w-3.5 h-3.5" />
              {t("mining.connectEVMWallet", "Connect Web3 EVM Wallet (MetaMask)")}
            </button>
          </div>
        </div>

        <NodeWalletBottomSheet
          isOpen={isWalletOpen}
          onClose={() => setIsWalletOpen(false)}
          onWalletActivated={() => handleActivate()}
        />
      </div>
    );
  }

  // Dashboard state (if enabled)
  const stats = miningStatus?.stats || (miningStatus as any) || {};
  const dailyEmission = miningStatus?.dailyEmission ?? stats?.daily_emission ?? stats?.dailyEmission ?? 547945;
  const yourEpochReward = miningStatus?.yourEpochReward ?? stats?.your_epoch_reward ?? stats?.yourEpochReward ?? 0.0;
  const epochTotalRebates = miningStatus?.epochTotalRebates ?? stats?.epoch_total_rebates ?? stats?.epochTotalRebates ?? 0.0;

  const handleDeactivate = () => {
    setIsDeactivating(true);
    api.deactivateMining()
      .then((res) => {
        if (res && res.data) {
          setMiningStatus(res.data);
        } else {
          setMiningStatus(res);
        }
      })
      .catch((err) => console.error("Deactivation failed", err))
      .finally(() => setIsDeactivating(false));
  };

  const welcomeProgress = Math.min((epochTotalRebates / 5.0) * 100, 100);
  const inviteLink = `${window.location.origin}/register?ref=${miningStatus?.nodeReferralCode || ""}`;

  return (
    <div className="p-4 space-y-6">
      {/* Node Header & Action Bar */}
      <div className="flex items-center justify-between gap-2 pb-2 border-b border-[hsl(var(--border))]">
        <div className="flex items-center gap-2">
          <span className="h-2 w-2 rounded-full bg-emerald-500 animate-pulse" />
          <span className="text-xs font-mono text-[hsl(var(--muted-foreground))]">
            {miningStatus?.nodeName || "Node"}
          </span>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => setIsWalletOpen(true)}
            className="text-xs font-semibold px-3 py-1.5 rounded-full border border-[hsl(var(--primary))]/30 bg-[hsl(var(--primary))]/10 text-[hsl(var(--primary))] transition flex items-center gap-1.5"
          >
            <Wallet className="w-3.5 h-3.5" />
            <span>{t("mining.nodeWallet", "EVM Wallet")}</span>
          </button>
          <button
            onClick={handleDeactivate}
            disabled={isDeactivating}
            className="text-xs font-semibold px-3 py-1.5 rounded-full border border-[hsl(var(--border))] text-[hsl(var(--muted-foreground))] hover:bg-red-500/10 hover:text-red-500 hover:border-red-500/30 transition flex items-center gap-1.5 disabled:opacity-50"
          >
            {isDeactivating ? <Loader2 className="w-3 h-3 animate-spin" /> : null}
            {t("mining.disableMining", "Disable Mining")}
          </button>
        </div>
      </div>

      {/* Overview Stats */}
      <div className="grid grid-cols-2 gap-3">
        {/* Balance Card */}
        <div className="rounded-2xl border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-4 flex flex-col justify-between h-[110px] relative overflow-hidden">
          <Coins className="w-6 h-6 text-amber-500 absolute -right-2 -bottom-2 w-16 h-16 opacity-5" />
          <span className="text-[10px] font-bold text-[hsl(var(--muted-foreground))] uppercase tracking-wider">
            {t("mining.totalMined", "Total Mined")}
          </span>
          <div className="text-lg font-bold truncate">
            {miningStatus?.totalMined?.toFixed(2) || "0.00"} <span className="text-xs text-[hsl(var(--muted-foreground))]">$DEPTH</span>
          </div>
        </div>

        {/* Expected Reward Card */}
        <div className="rounded-2xl border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-4 flex flex-col justify-between h-[110px]">
          <span className="text-[10px] font-bold text-[hsl(var(--muted-foreground))] uppercase tracking-wider">
            {t("mining.todayEstReward", "Est. Daily Reward")}
          </span>
          <div className="text-lg font-bold truncate text-[hsl(var(--primary))]">
            ~{yourEpochReward >= 1000 ? Math.round(yourEpochReward).toLocaleString("en-US").replace(/,/g, " ") : yourEpochReward.toFixed(2)} <span className="text-xs text-[hsl(var(--muted-foreground))]">$DEPTH</span>
          </div>
        </div>

        {/* Rebates Card */}
        <div className="rounded-2xl border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-4 flex flex-col justify-between h-[110px]">
          <span className="text-[10px] font-bold text-[hsl(var(--muted-foreground))] uppercase tracking-wider">
            {t("mining.todayRebates", "Today's Rebates")}
          </span>
          <div className="text-lg font-bold truncate">
            ${epochTotalRebates.toFixed(2)}
          </div>
        </div>

        {/* Emission Card */}
        <div className="rounded-2xl border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-4 flex flex-col justify-between h-[110px]">
          <span className="text-[10px] font-bold text-[hsl(var(--muted-foreground))] uppercase tracking-wider">
            {t("mining.dailyEmission", "Daily Emission")}
          </span>
          <div className="text-lg font-bold truncate">
            {dailyEmission.toLocaleString()}
          </div>
        </div>
      </div>

      {/* Node Sharing Policy info */}
      {(miningStatus?.userRewardSharePercent !== undefined || stats?.userRatio !== undefined) && (
        <div className="rounded-2xl border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-4 space-y-2">
          <div className="flex justify-between items-center text-xs">
            <span className="text-[hsl(var(--muted-foreground))]">{t("mining.nodeSharePercentage", "Node Share Percentage:")}</span>
            <span className="font-bold text-[hsl(var(--primary))]">{miningStatus?.userRewardSharePercent ?? 0}%</span>
          </div>
          {stats?.userRatio !== undefined && (
            <div className="flex justify-between items-center text-xs">
              <span className="text-[hsl(var(--muted-foreground))]">{t("mining.yourVolumeShare", "Your Volume Share:")}</span>
              <span className="font-bold text-[hsl(var(--foreground))]">{(stats.userRatio * 100).toFixed(2)}%</span>
            </div>
          )}
          {miningStatus?.userTradeVolume !== undefined && (
            <div className="flex justify-between items-center text-xs">
              <span className="text-[hsl(var(--muted-foreground))]">{t("mining.yourTotalVolume", "Your Total Volume:")}</span>
              <span className="font-bold text-[hsl(var(--foreground))]">{miningStatus.userTradeVolume.toFixed(2)} USDT</span>
            </div>
          )}
        </div>
      )}

      {/* Supported Exchanges Card */}
      {((stats?.eligibleExchanges || stats?.eligible_exchanges || []).length > 0) && (
        <div className="rounded-2xl border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-4 space-y-3">
          <div className="flex items-center gap-2">
            <Globe className="w-5 h-5 text-[hsl(var(--primary))]" />
            <h3 className="text-sm font-semibold">{t("mining.supportedExchanges", "Supported Exchanges")}</h3>
          </div>
          <div className="space-y-1.5 pt-1">
            {(stats?.eligibleExchanges || stats?.eligible_exchanges || []).map((ex: string) => {
              const rates = stats?.rebateRates || stats?.rebate_rates || {};
              const rate = rates[ex] ?? 0.60;
              const isOkx = ex.toLowerCase().includes("okx");
              const isBybit = ex.toLowerCase().includes("bybit");
              return (
                <div key={ex} className="flex flex-col gap-1 bg-[hsl(var(--background))] border border-[hsl(var(--border))] px-3 py-2 rounded-xl text-xs">
                  <div className="flex items-center justify-between">
                    <span className="font-mono font-bold uppercase">{ex.replace("_", " ")}</span>
                    <span className="text-[10px] font-bold text-[hsl(var(--primary))] bg-[hsl(var(--primary))]/10 border border-[hsl(var(--primary))]/20 px-2 py-0.5 rounded-full flex items-center gap-1">
                      {(rate * 100).toFixed(0)}% Rebate
                      {(isOkx || isBybit) && <Info className="w-3 h-3 text-[hsl(var(--primary))]" />}
                    </span>
                  </div>
                  {(isOkx || isBybit) && (
                    <p className="text-[10px] text-muted-foreground leading-tight pt-0.5">
                      {isOkx
                        ? t("mining.okxRebateTip", "Base rate (30%). Stacks with affiliate link (+7.5%) up to 5x rewards.")
                        : t("mining.bybitRebateTip", "Base rate (40%). Stacks with affiliate link for maximum mining yield.")}
                    </p>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Welcome Bonus Card */}
      <div className="rounded-2xl border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-4 space-y-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Coins className="w-5 h-5 text-yellow-500" />
            <h3 className="text-sm font-semibold">{t("mining.welcomeBonus", "Welcome Bonus")}</h3>
          </div>
          {miningStatus?.hasWelcomeBonus && (
            <span className="text-[9px] font-bold uppercase tracking-wider bg-yellow-500/10 text-yellow-600 dark:text-yellow-400 border border-yellow-500/20 px-2 py-0.5 rounded-full">
              {t("mining.welcomeBonusClaimedBadge", "Claimed")}
            </span>
          )}
        </div>
        <p className="text-xs text-[hsl(var(--muted-foreground))] leading-normal">
          {t("mining.welcomeBonusDesc", "Generate at least $5.0 of cumulative rebate to claim your 1000 $DEPTH welcome bonus.")}
        </p>

        {miningStatus?.hasWelcomeBonus ? (
          <div className="bg-yellow-500/5 border border-yellow-500/20 rounded-xl p-3 flex items-center gap-3">
            <ShieldCheck className="w-6 h-6 text-yellow-500 shrink-0" />
            <div className="text-xs">
              <span className="font-bold text-yellow-500 block">{t("mining.welcomeBonusClaimed", "Welcome Bonus Claimed!")}</span>
              <span className="text-[hsl(var(--muted-foreground))] mt-0.5 block">{t("mining.welcomeBonusClaimedDesc", "1000 $DEPTH credited to balance.")}</span>
            </div>
          </div>
        ) : (
          <div className="space-y-2 pt-1">
            <div className="flex justify-between text-[10px] font-bold text-[hsl(var(--muted-foreground))]">
              <span>{t("mining.welcomeBonusProgress", { current: epochTotalRebates.toFixed(2), target: "5.00" })}</span>
              <span>{Math.round(welcomeProgress)}%</span>
            </div>
            <div className="h-1.5 w-full bg-[hsl(var(--secondary))] rounded-full overflow-hidden">
              <div 
                className="h-full bg-gradient-to-r from-yellow-500 to-amber-500 rounded-full" 
                style={{ width: `${welcomeProgress}%` }}
              />
            </div>
          </div>
        )}
      </div>

      {/* Referral Program Card */}
      <div className="rounded-2xl border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-4 space-y-4">
        <div className="flex items-center gap-2">
          <Share2 className="w-5 h-5 text-[hsl(var(--primary))]" />
          <h3 className="text-sm font-semibold">{t("mining.referralLinkCardTitle", "Referral Link")}</h3>
        </div>
        <p className="text-xs text-[hsl(var(--muted-foreground))] leading-normal">
          {t("mining.referralProgramDesc", "Invite friends to run nodes and earn a +10% daily boost plus matching welcome rewards!")}
        </p>

        <div className="space-y-3">
          <div className="space-y-1">
            <span className="text-[10px] font-bold text-[hsl(var(--muted-foreground))] uppercase tracking-wider block">
              {t("mining.yourReferralCode", "Your Referral Code")}
            </span>
            <div className="flex items-center justify-between rounded-lg bg-[hsl(var(--background))] border border-[hsl(var(--border))] p-2 pl-3">
              <span className="font-mono text-sm font-bold tracking-wider">
                {miningStatus?.nodeReferralCode || "Loading..."}
              </span>
              <button
                onClick={() => copyToClipboard(miningStatus?.nodeReferralCode || "", false)}
                className="p-2 hover:bg-[hsl(var(--secondary))] rounded-lg transition"
              >
                {copiedCode ? <Check className="w-4 h-4 text-emerald-500" /> : <Copy className="w-4 h-4" />}
              </button>
            </div>
          </div>

          <div className="space-y-1">
            <span className="text-[10px] font-bold text-[hsl(var(--muted-foreground))] uppercase tracking-wider block">
              {t("mining.referralLink", "Referral Link")}
            </span>
            <div className="flex items-center justify-between rounded-lg bg-[hsl(var(--background))] border border-[hsl(var(--border))] p-2 pl-3">
              <span className="font-mono text-xs text-[hsl(var(--muted-foreground))] truncate max-w-[200px]">
                {inviteLink}
              </span>
              <button
                onClick={() => copyToClipboard(inviteLink, true)}
                className="p-2 hover:bg-[hsl(var(--secondary))] rounded-lg transition"
              >
                {copiedLink ? <Check className="w-4 h-4 text-emerald-500" /> : <Copy className="w-4 h-4" />}
              </button>
            </div>
          </div>

          {miningStatus?.nodeReferralCode && (
            <div className="space-y-1">
              <span className="text-[10px] font-bold text-[hsl(var(--muted-foreground))] uppercase tracking-wider block">
                {t("mining.nodeDeployCommand", "Node One-Line Deploy Command")}
              </span>
              <div className="flex items-center justify-between gap-2 rounded-lg bg-[hsl(var(--background))] border border-[hsl(var(--border))] p-2 pl-3 overflow-hidden max-w-full">
                <span className="font-mono text-[11px] text-emerald-500 truncate min-w-0 flex-1">
                  {`curl -sL https://raw.githubusercontent.com/DepthSight-Pro/DepthSight/main/deploy.sh | NODE_REFERRER_CODE=${miningStatus.nodeReferralCode} sudo bash`}
                </span>
                <button
                  onClick={() => {
                    const cmd = `curl -sL https://raw.githubusercontent.com/DepthSight-Pro/DepthSight/main/deploy.sh | NODE_REFERRER_CODE=${miningStatus.nodeReferralCode} sudo bash`;
                    navigator.clipboard.writeText(cmd);
                    setCopiedLink(true);
                    setTimeout(() => setCopiedLink(false), 2000);
                  }}
                  className="p-2 hover:bg-[hsl(var(--secondary))] rounded-lg transition shrink-0"
                >
                  {copiedLink ? <Check className="w-4 h-4 text-emerald-500" /> : <Copy className="w-4 h-4" />}
                </button>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Staking Card */}
      <div className="rounded-2xl border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-4 relative overflow-hidden opacity-80">
        <Lock className="w-16 h-16 absolute -right-2 -bottom-2 text-[hsl(var(--primary))] opacity-5" />
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Lock className="w-5 h-5 text-[hsl(var(--muted-foreground))]" />
            <h3 className="text-sm font-semibold text-[hsl(var(--muted-foreground))]">{t("mining.stakingBoost", "Staking Boost")}</h3>
          </div>
          <span className="text-[8px] font-bold uppercase tracking-wider bg-[hsl(var(--secondary))] px-2 py-0.5 rounded-full text-[hsl(var(--muted-foreground))]">
            {t("mining.comingSoon", "Coming Soon")}
          </span>
        </div>
        <p className="text-xs text-[hsl(var(--muted-foreground))] mt-2 leading-relaxed">
          {t("mining.stakingBoostDetail", "Lock $DEPTH for 30, 90 or 360 days to unlock up to 2.0x multiplier on all daily trade mining emission rewards.")}
        </p>
      </div>

      <NodeWalletBottomSheet
        isOpen={isWalletOpen}
        onClose={() => setIsWalletOpen(false)}
        onWalletActivated={() => handleActivate()}
      />
    </div>
  );
};

export default MiningScreen;
