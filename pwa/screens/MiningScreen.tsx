// pwa/screens/MiningScreen.tsx

import React, { useState, useEffect, useMemo, useRef } from "react";
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
  Info,
  X,
} from "lucide-react";
import { api } from "../services/api";
import { Logo } from "../components/ui/logo";
import { NodeWalletBottomSheet } from "../components/NodeWalletBottomSheet";
import { PromoBannerPwa } from "../components/mining/PromoBannerPwa";
import { PromoCampaignModal } from "../components/mining/PromoCampaignModal";
import { ExchangeBadge } from "../components/ExchangeBadge";


interface MiningStatus {
  nodeUuid?: string;
  node_uuid?: string;
  nodeName?: string;
  node_name?: string;
  referrerReferralCode?: string;
  referrer_referral_code?: string;
  stats?: Record<string, unknown>;
  nodeReferralCode?: string;
  node_referral_code?: string;
  serverTotalMined?: number;
  server_total_mined?: number;
  totalMined?: number;
  total_mined?: number;
  totalDistributed?: number;
  total_distributed?: number;
  userCumulativeRebate?: number;
  user_cumulative_rebate?: number;
  dailyEmission?: number;
  daily_emission?: number;
  yourEpochReward?: number;
  your_epoch_reward?: number;
  epochTotalRebates?: number;
  epoch_total_rebates?: number;
  userRewardSharePercent?: number;
  user_reward_share_percent?: number;
  userTradeVolume?: number;
  user_trade_volume?: number;
  isMiningEnabled?: boolean;
  is_mining_enabled?: boolean;
  isGlobalMiningEnabled?: boolean;
  is_global_mining_enabled?: boolean;
  hasWelcomeBonus?: boolean;
  has_welcome_bonus?: boolean;
  [key: string]: unknown;
}

/** Coerces an unknown API value to a finite number. */
const num = (v: unknown, fallback = 0): number => {
  const n = typeof v === "string" && v.trim() !== "" ? Number(v) : v;
  return typeof n === "number" && Number.isFinite(n) ? n : fallback;
};

/** Normalizes API responses that may or may not be wrapped in `{ data }`. */
const toMiningStatus = (res: unknown): MiningStatus | null => {
  if (!res || typeof res !== "object") return null;
  const obj = res as { data?: unknown };
  const payload =
    obj.data && typeof obj.data === "object" ? obj.data : res;
  return payload as MiningStatus;
};

interface PromoStatus {
  [key: string]: unknown;
}

const MiningScreen: React.FC = () => {
  const { t } = useTranslation("pwa-common");
  const [loading, setLoading] = useState(true);
  const [miningStatus, setMiningStatus] = useState<MiningStatus | null>(null);
  const [promoStatus, setPromoStatus] = useState<PromoStatus | null>(null);
  const [referrerCode, setReferrerCode] = useState("");
  const [isActivating, setIsActivating] = useState(false);
  const [isDeactivating, setIsDeactivating] = useState(false);
  const [copiedCode, setCopiedCode] = useState(false);
  const [copiedLink, setCopiedLink] = useState(false);
  const [isPromoModalOpen, setIsPromoModalOpen] = useState(false);
  const [selectedExchangeDetail, setSelectedExchangeDetail] = useState<{
    baseKey: string;
    label: string;
    spotRate?: number;
    futuresRate?: number;
    generalRate?: number;
    maxRate: number;
    multiplier: number;
    isBoosted: boolean;
  } | null>(null);

  const fetchStatus = () => {
    setLoading(true);
    api.getMiningStatus()
      .catch((err) => {
        console.error("Failed to load mining status", err);
        return null;
      })
      .then((miningRes) => {
        const mData = toMiningStatus(miningRes);
        if (mData) {
          setMiningStatus(mData);
        }
        const nodeUuid = mData?.nodeUuid || mData?.node_uuid;
        return api.getPromoStatus(nodeUuid).catch(() => null);
      })
      .then((promoRes) => {
        if (promoRes && promoRes.data) {
          setPromoStatus(promoRes.data);
        } else if (promoRes) {
          setPromoStatus(promoRes);
        }
      })
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    fetchStatus();
  }, []);

  const referrerCodeRef = useRef<string>("");
  const referrerCodeFromStorage = useRef<string>("");

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const urlRef = params.get("ref") || params.get("ref_code") || params.get("referrer_code");
    const localRef = localStorage.getItem("ref_code") || localStorage.getItem("referrer_code") || localStorage.getItem("ref");
    const apiRef = miningStatus?.referrerReferralCode || miningStatus?.referrer_referral_code || "";
    const foundCode = urlRef || localRef || apiRef || "";

    referrerCodeFromStorage.current = foundCode;

    if (foundCode && referrerCodeRef.current === "") {
      setReferrerCode(foundCode);
      referrerCodeRef.current = foundCode;
    }
  }, [miningStatus]);

  const stats = useMemo(() => (miningStatus?.stats as Record<string, unknown>) || {}, [miningStatus]);

  const groupedExchanges = useMemo(() => {
    const rawList: string[] =
      (stats?.eligibleExchanges as string[] | undefined) ||
      (stats?.eligible_exchanges as string[] | undefined) ||
      [];
    if (!rawList.length) return [];

    const rates: Record<string, number> =
      (stats?.rebateRates as Record<string, number> | undefined) ||
      (stats?.rebate_rates as Record<string, number> | undefined) ||
      {};
    const multipliers: Record<string, number> =
      (stats?.exchangeMultipliers as Record<string, number> | undefined) ||
      (stats?.exchange_multipliers as Record<string, number> | undefined) ||
      {};

    const map = new Map<string, {
      baseKey: string;
      label: string;
      spotRate?: number;
      futuresRate?: number;
      generalRate?: number;
      maxRate: number;
      multiplier: number;
      isBoosted: boolean;
    }>();

    for (const raw of rawList) {
      const norm = String(raw).trim().toLowerCase().replace(/_(futures|spot|usdtm|swap|linear|usdm)$/, "");
      const rate = rates[raw] ?? rates[norm] ?? 0.30;
      const mult = multipliers[raw] ?? multipliers[norm] ?? (norm.includes("bitget") ? 2.0 : 1.0);

      const existing = map.get(norm) || {
        baseKey: norm,
        label: norm.toUpperCase(),
        maxRate: 0,
        multiplier: 1.0,
        isBoosted: false,
      };

      const rawLower = raw.toLowerCase();
      if (rawLower.includes("spot")) {
        existing.spotRate = rate;
      } else if (rawLower.includes("futures") || rawLower.includes("swap") || rawLower.includes("linear") || rawLower.includes("usdtm")) {
        existing.futuresRate = rate;
      } else {
        existing.generalRate = rate;
      }

      if (rate > existing.maxRate) existing.maxRate = rate;
      if (mult > existing.multiplier) existing.multiplier = mult;
      if (existing.multiplier > 1.0) existing.isBoosted = true;

      map.set(norm, existing);
    }

    for (const item of map.values()) {
      if (item.futuresRate === undefined) item.futuresRate = item.generalRate ?? item.maxRate;
      if (item.spotRate === undefined) item.spotRate = item.generalRate ?? item.maxRate;
    }

    return Array.from(map.values());
  }, [stats]);

  const [isWalletOpen, setIsWalletOpen] = useState(false);

  const handleActivate = () => {
    setIsActivating(true);
    api.activateMining(referrerCode.trim() || undefined)
      .then((res) => {
        const next = toMiningStatus(res);
        if (next) {
          setMiningStatus(next);
        }
      })
      .catch((err) => {
        const msg = (err as Error)?.message ?? String(err);
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
  const dailyEmission = num(
    miningStatus?.dailyEmission ?? stats?.daily_emission ?? stats?.dailyEmission,
    547945,
  );
  const yourEpochReward = num(
    miningStatus?.yourEpochReward ?? stats?.your_epoch_reward ?? stats?.yourEpochReward,
  );
  const epochTotalRebates = num(
    miningStatus?.epochTotalRebates ?? stats?.epoch_total_rebates ?? stats?.epochTotalRebates,
  );
  const totalDistributed = num(
    miningStatus?.totalDistributed ??
      stats?.totalDistributed ??
      stats?.serverTotalMined ??
      miningStatus?.serverTotalMined,
  );

  const handleDeactivate = () => {
    setIsDeactivating(true);
    api.deactivateMining()
      .then((res) => {
        const next = toMiningStatus(res);
        if (next) {
          setMiningStatus(next);
        }
      })
      .catch((err) => console.error("Deactivation failed", err))
      .finally(() => setIsDeactivating(false));
  };

  const welcomeTarget = 1.0;
  const userCumulativeRebate = num(
    miningStatus?.userCumulativeRebate ??
      stats?.your_cumulative_rebates ??
      stats?.yourCumulativeRebates ??
      stats?.user_cumulative_rebate ??
      stats?.userCumulativeRebate ??
      stats?.cumulativeRebates ??
      epochTotalRebates,
  );
  const welcomeProgress = Math.min((userCumulativeRebate / welcomeTarget) * 100, 100);
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

      {/* Active Partner Exchange Multiplier Promo Banner */}
      {promoStatus?.hasActiveCampaign && (
        <PromoBannerPwa
          promoStatus={promoStatus}
          onOpenQuests={() => setIsPromoModalOpen(true)}
        />
      )}

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

        {/* Total Distributed Card */}
        <div className="col-span-2 rounded-2xl border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-3.5 flex items-center justify-between">
          <div>
            <span className="text-[10px] font-bold text-[hsl(var(--muted-foreground))] uppercase tracking-wider block">
              {t("mining.totalDistributed", "Total Distributed")}
            </span>
            <span className="text-[11px] text-[hsl(var(--muted-foreground))]">
              {t("mining.totalDistributedSubtitle", "Distributed across all epochs")}
            </span>
          </div>
          <div className="text-base font-bold text-[hsl(var(--foreground))]">
            {totalDistributed >= 1000 ? Math.round(totalDistributed).toLocaleString("en-US").replace(/,/g, " ") : totalDistributed.toFixed(2)} <span className="text-xs text-[hsl(var(--muted-foreground))]">$DEPTH</span>
          </div>
        </div>
      </div>

      {/* Node Sharing Policy & Supported Exchanges */}
      {((miningStatus?.userRewardSharePercent !== undefined || stats?.userRatio !== undefined) || groupedExchanges.length > 0) && (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3 items-stretch">
          {/* Node Sharing Policy */}
          {(miningStatus?.userRewardSharePercent !== undefined || stats?.userRatio !== undefined) && (
            <div className="rounded-2xl border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-4 flex flex-col justify-between h-full space-y-3">
              <div>
                <div className="flex items-center gap-2 mb-2">
                  <ShieldCheck className="w-4 h-4 text-[hsl(var(--primary))]" />
                  <h3 className="text-xs font-bold uppercase tracking-wider text-[hsl(var(--muted-foreground))]">
                    {t("mining.nodeSharingPolicy", "Node Sharing Policy")}
                  </h3>
                </div>
                <div className="space-y-2">
                  <div className="flex justify-between items-center text-xs bg-[hsl(var(--background))] p-2.5 rounded-xl border border-[hsl(var(--border))]">
                    <span className="text-[hsl(var(--muted-foreground))]">{t("mining.nodeSharePercentage", "Node Share Percentage:")}</span>
                    <span className="font-bold text-[hsl(var(--primary))] font-mono">{miningStatus?.userRewardSharePercent ?? 0}%</span>
                  </div>
                  {stats?.userRatio !== undefined && (
                    <div className="flex justify-between items-center text-xs bg-[hsl(var(--background))] p-2.5 rounded-xl border border-[hsl(var(--border))]">
                      <span className="text-[hsl(var(--muted-foreground))]">{t("mining.yourVolumeShare", "Your Volume Share (Today):")}</span>
                      <span className="font-bold text-[hsl(var(--foreground))] font-mono">{(num(stats?.userRatio) * 100).toFixed(2)}%</span>
                    </div>
                  )}
                  {miningStatus?.userTradeVolume !== undefined && (
                    <div className="flex justify-between items-center text-xs bg-[hsl(var(--background))] p-2.5 rounded-xl border border-[hsl(var(--border))]">
                      <span className="text-[hsl(var(--muted-foreground))]">{t("mining.yourTotalVolume", "Your Total Volume:")}</span>
                      <span className="font-bold text-[hsl(var(--foreground))] font-mono">{miningStatus.userTradeVolume.toFixed(2)} USDT</span>
                    </div>
                  )}
                </div>
              </div>
              <div className="pt-2 border-t border-[hsl(var(--border))] flex items-start gap-2 text-[11px] text-[hsl(var(--muted-foreground))]">
                <p className="leading-snug">
                  {t("mining.nodeSharingPolicyDesc", "Rewards are distributed in real-time according to verified trade volume share and active node policy.")}
                </p>
              </div>
            </div>
          )}

          {/* Supported Exchanges Card */}
          {groupedExchanges.length > 0 && (
            <div className="rounded-2xl border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-4 flex flex-col justify-between h-full space-y-3">
              <div>
                <div className="flex items-center gap-2">
                  <Globe className="w-4 h-4 text-[hsl(var(--primary))]" />
                  <h3 className="text-xs font-bold uppercase tracking-wider text-[hsl(var(--muted-foreground))]">
                    {t("mining.supportedExchanges", "Supported Exchanges & Rebates")}
                  </h3>
                </div>
                <p className="text-[11px] text-[hsl(var(--muted-foreground))] mt-1 mb-3 leading-snug">
                  {t("mining.supportedExchangesDesc", "Trade mining rewards are calculated for live trades executed on the following exchanges:")}
                </p>

                <div className="flex flex-wrap gap-2 pt-0.5">
                  {groupedExchanges.map((exItem) => (
                    <button
                      key={exItem.baseKey}
                      type="button"
                      onClick={() => setSelectedExchangeDetail(exItem)}
                      className={`group flex items-center gap-2 border px-3 py-2 rounded-xl text-xs transition-all active:scale-95 text-left cursor-pointer ${
                        exItem.isBoosted
                          ? "border-amber-500/50 bg-amber-500/10 hover:border-amber-500/70 shadow-sm"
                          : "border-[hsl(var(--border))] bg-[hsl(var(--background))] hover:border-[hsl(var(--primary))]/40"
                      }`}
                    >
                      <ExchangeBadge exchange={exItem.baseKey} size="xs" />
                      <span className="font-mono font-bold uppercase tracking-wide text-[hsl(var(--foreground))] text-xs">
                        {exItem.label}
                      </span>
                      {exItem.isBoosted && (
                        <span className="bg-amber-500/20 text-amber-600 dark:text-amber-400 border border-amber-500/30 text-[10px] font-mono font-extrabold flex items-center gap-1 rounded-md px-1.5 py-0.5 animate-pulse">
                          🔥 {exItem.multiplier}x
                        </span>
                      )}
                      <Info className="w-3.5 h-3.5 text-[hsl(var(--muted-foreground))] ml-0.5 group-hover:text-[hsl(var(--primary))] transition-colors" />
                    </button>
                  ))}
                </div>
              </div>

              <div className="pt-2 border-t border-[hsl(var(--border))] flex items-start gap-2 text-[11px] text-[hsl(var(--muted-foreground))] bg-[hsl(var(--background))]/50 p-2.5 rounded-xl">
                <ShieldCheck className="w-3.5 h-3.5 text-[hsl(var(--primary))] shrink-0 mt-0.5" />
                <p className="leading-snug">
                  {t("mining.supportedExchangesRebateNote", "Rewards are directly tied to the fee rebate generated: the higher the exchange rebate rate, the higher your $DEPTH reward accordingly. The Central Hub securely verifies every trade directly via the exchanges' broker APIs.")}
                </p>
              </div>
            </div>
          )}
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
          {t("mining.welcomeBonusDesc", "Generate at least $1.0 of cumulative rebate to claim your 1000 $DEPTH welcome bonus.")}
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
              <span>{t("mining.welcomeBonusProgress", { current: userCumulativeRebate.toFixed(2), target: welcomeTarget.toFixed(2) })}</span>
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

      <PromoCampaignModal
        isOpen={isPromoModalOpen}
        onClose={() => setIsPromoModalOpen(false)}
        promoStatus={promoStatus}
        onRefresh={fetchStatus}
        nodeUuid={miningStatus?.nodeUuid || miningStatus?.node_uuid}
      />

      {/* Exchange Rebate Detail Modal */}
      {selectedExchangeDetail && (
        <div 
          className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm animate-in fade-in duration-200"
          onClick={() => setSelectedExchangeDetail(null)}
        >
          <div 
            className="w-full max-w-sm rounded-2xl border border-[hsl(var(--border))] bg-[hsl(var(--card))] text-[hsl(var(--card-foreground))] p-5 shadow-2xl space-y-4 animate-in zoom-in-95 duration-200"
            onClick={(e) => e.stopPropagation()}
          >
            {/* Header */}
            <div className="flex items-center justify-between pb-3 border-b border-[hsl(var(--border))]">
              <div className="flex items-center gap-2.5">
                <ExchangeBadge exchange={selectedExchangeDetail.baseKey} size="sm" />
                <span className="font-mono font-bold uppercase text-base tracking-wide">
                  {selectedExchangeDetail.label}
                </span>
                {selectedExchangeDetail.isBoosted && (
                  <span className="bg-amber-500/20 text-amber-600 dark:text-amber-400 border border-amber-500/30 text-[10px] font-mono font-extrabold rounded-md px-1.5 py-0.5">
                    🔥 {selectedExchangeDetail.multiplier}x BOOST
                  </span>
                )}
              </div>
              <button
                type="button"
                onClick={() => setSelectedExchangeDetail(null)}
                className="p-1 rounded-full text-[hsl(var(--muted-foreground))] hover:text-[hsl(var(--foreground))] hover:bg-[hsl(var(--secondary))] transition-colors"
                aria-label="Close"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            {/* Rebates rates */}
            <div className="grid grid-cols-2 gap-2 text-xs font-mono">
              <div className="p-3 rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--background))]">
                <div className="text-[10px] font-sans text-[hsl(var(--muted-foreground))] uppercase">
                  {t("mining.futuresRebate", "Futures Rebate")}
                </div>
                <div className="text-base font-bold text-[hsl(var(--primary))] mt-0.5">
                  {((selectedExchangeDetail.futuresRate ?? selectedExchangeDetail.maxRate) * 100).toFixed(0)}%
                </div>
              </div>
              <div className="p-3 rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--background))]">
                <div className="text-[10px] font-sans text-[hsl(var(--muted-foreground))] uppercase">
                  {t("mining.spotRebate", "Spot Rebate")}
                </div>
                <div className="text-base font-bold text-[hsl(var(--primary))] mt-0.5">
                  {((selectedExchangeDetail.spotRate ?? selectedExchangeDetail.maxRate) * 100).toFixed(0)}%
                </div>
              </div>
            </div>

            {/* Detail tooltip / description text */}
            <div className="p-3 rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--secondary))]/50 text-xs text-[hsl(var(--muted-foreground))] leading-relaxed">
              {selectedExchangeDetail.baseKey === "bitget"
                ? t("mining.bitgetRebateTip", "Base rate (35%) + 2.0x Mining Multiplier! Stacks under our affiliate link for 2x $DEPTH token yield.")
                : selectedExchangeDetail.baseKey === "okx"
                ? t("mining.okxRebateTip", "Base rate (30%). Stacks with affiliate link (+7.5%) up to 5x rewards.")
                : selectedExchangeDetail.baseKey === "bybit"
                ? t("mining.bybitRebateTip", "Base rate (50%), under third-party referral only 10%. Stacks under our link (+10%) for maximum yield.")
                : selectedExchangeDetail.isBoosted
                ? `${selectedExchangeDetail.multiplier}x Trade Mining Reward Multiplier active for ${selectedExchangeDetail.label}.`
                : t("mining.supportedExchangesRebateNote", "Rewards are directly tied to the fee rebate generated: the higher the exchange rebate rate, the higher your $DEPTH reward accordingly.")}
            </div>

            {/* Close Button */}
            <button
              type="button"
              onClick={() => setSelectedExchangeDetail(null)}
              className="w-full py-2.5 px-4 rounded-xl text-xs font-semibold bg-[hsl(var(--secondary))] hover:bg-[hsl(var(--secondary))]/80 text-[hsl(var(--foreground))] transition-colors"
            >
              {t("common.close", "Закрыть")}
            </button>
          </div>
        </div>
      )}
    </div>
  );
};

export default MiningScreen;
