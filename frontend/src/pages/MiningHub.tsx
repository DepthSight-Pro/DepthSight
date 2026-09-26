// src/pages/MiningHub.tsx

import React, { useState, useMemo } from "react";
import { useTranslation } from "react-i18next";
import { Navigate } from "react-router-dom";
import { 
  Coins, 
  Copy, 
  Check, 
  Flame, 
  Activity, 
  Share2, 
  UserPlus, 
  ShieldCheck, 
  Lock, 
  Loader2,
  Globe,
  CheckCircle2,
  Users,
  RefreshCw,
  X,
  ChevronLeft,
  ChevronRight,
  AlertCircle,
  Search,
  ArrowUpRight,
  Sparkles,
  Wallet,
  Info,
  KeyRound,
  UserCheck,
  Award
} from "lucide-react";
import { AppLoader } from "@/components/shared/AppLoader";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { Progress } from "@/components/ui/progress";
import { useToast } from "@/components/ui/use-toast";
import { useGetMiningStatus, useActivateMining, useDeactivateMining, useGetMiningReferrals, useGetMiningTrades, useGetPromoStatus, type LocalMiningStatusResponse } from "@/lib/api";
import { NodeWalletModal } from "@/components/mining/NodeWalletModal";
import { PromoBanner } from "@/components/mining/PromoBanner";
import { PromoQuestsTab } from "@/components/mining/PromoQuestsTab";
import { MiningRateCard } from "@/components/mining/MiningRateCard";
import { Footer } from "@/components/layout/Footer";
import { ExchangeBadge } from "@/components/layout/AccountSelector";
import { exchangeLabels, normalizeExchangeKey } from "@/lib/exchanges";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import { 
  Select, 
  SelectContent, 
  SelectItem, 
  SelectTrigger, 
  SelectValue 
} from "@/components/ui/select";
import { SidebarTrigger, useSidebar } from "@/components/ui/sidebar";


const StatCard = ({
  title,
  value,
  subtitle,
  icon: Icon,
  isLoading,
  accent = "#00d4ff",
}: {
  title: string;
  value: string | number;
  subtitle?: string;
  icon: React.ElementType;
  isLoading: boolean;
  accent?: string;
}) => (
  <div className="glass relative rounded-2xl p-4 overflow-hidden group hover:border-white/10 transition-all duration-300 animate-fade-up">
    {/* Ambient corner glow */}
    <div
      className="pointer-events-none absolute -top-14 -right-14 h-36 w-36 rounded-full blur-3xl opacity-20 group-hover:opacity-35 transition-opacity duration-300"
      style={{ background: accent }}
    />
    <div
      className="pointer-events-none absolute -bottom-14 -left-14 h-28 w-28 rounded-full blur-3xl opacity-10"
      style={{ background: accent }}
    />

    <div className="flex items-start justify-between relative z-10">
      <span className="text-[11px] font-medium uppercase tracking-[0.12em] text-white/40">
        {title}
      </span>
      <div
        className="flex h-7 w-7 items-center justify-center rounded-lg border border-white/5 bg-white/[0.03] transition-colors group-hover:border-white/10 shadow-sm"
        style={{ color: accent }}
      >
        <Icon className="h-3.5 w-3.5" />
      </div>
    </div>

    <div className="mt-2.5 relative z-10">
      {isLoading ? (
        <Skeleton className="h-8 w-28 bg-white/5 rounded-lg" />
      ) : (
        <div className="text-[22px] leading-tight font-semibold text-white font-mono tracking-tight">
          {value}
        </div>
      )}
      {subtitle && (
        <p className="text-[11px] text-white/40 mt-1 truncate">{subtitle}</p>
      )}
    </div>
  </div>
);

// Stable empty stats object so `stats` never allocates a fresh `{}` per render
// (a fresh literal in the groupedExchanges useMemo deps changed every render).
const EMPTY_STATS = {} as NonNullable<LocalMiningStatusResponse["stats"]>;

const MiningHub: React.FC = () => {
  const { t } = useTranslation(["mining", "common"]);
  const { isMobile } = useSidebar();
  const { toast } = useToast();
  const [referrerCode, setReferrerCode] = useState(() => {
    const params = new URLSearchParams(window.location.search);
    return (
      params.get("ref") ||
      params.get("ref_code") ||
      params.get("referrer_code") ||
      localStorage.getItem("ref_code") ||
      localStorage.getItem("referrer_code") ||
      localStorage.getItem("ref") ||
      ""
    );
  });
  const [apiRefApplied, setApiRefApplied] = useState(false);
  const [copiedCode, setCopiedCode] = useState(false);
  const [copiedLink, setCopiedLink] = useState(false);

  const [activeSubTab, setActiveSubTab] = useState<"overview" | "referrals" | "trades" | "quests">("overview");
  const [searchQuery, setSearchQuery] = useState("");

  // Trades Sub-tab states
  const [tradesPage, setTradesPage] = useState(1);
  const [selectedScopeFilter, setSelectedScopeFilter] = useState<"all" | "my" | "referrals">("all");
  const [selectedUserIdFilter, setSelectedUserIdFilter] = useState<number | undefined>(undefined);
  const [selectedUsernameFilter, setSelectedUsernameFilter] = useState<string>("");
  const [selectedStatusFilter, setSelectedStatusFilter] = useState<string>("ALL");
  const [selectedExchangeFilter, setSelectedExchangeFilter] = useState<string>("all");
  const [tradesSearch, setTradesSearch] = useState<string>("");

  const { data: status, isLoading, refetch } = useGetMiningStatus();
  const { data: promoStatus } = useGetPromoStatus({
    nodeUuid: status?.nodeUuid || status?.node_uuid,
  });
  const { mutate: activateMining, isPending: isActivating } = useActivateMining();
  const { mutate: deactivateMining, isPending: isDeactivating } = useDeactivateMining();
  const { data: referralsData, isLoading: isLoadingReferrals } = useGetMiningReferrals(activeSubTab === "referrals");
  const { data: tradesData, isLoading: isLoadingTrades, refetch: refetchTrades } = useGetMiningTrades(
    {
      page: tradesPage,
      limit: 15,
      userId: selectedUserIdFilter,
      status: selectedStatusFilter,
      exchange: selectedExchangeFilter,
      search: tradesSearch,
      scope: selectedScopeFilter,
    },
    activeSubTab === "trades"
  );

  const isAlreadyLinked = Boolean(status?.referrerNodeUuid || status?.referrer_node_uuid);

  // Prefill the node's stored referrer code once the status query resolves —
  // adjusted during render (guarded) instead of a setState-in-effect. URL and
  // localStorage codes were already captured by the lazy useState initializer.
  const apiReferrerCode =
    status?.referrerReferralCode || status?.referrer_referral_code || "";
  if (!apiRefApplied && status) {
    setApiRefApplied(true);
    if (apiReferrerCode && !referrerCode) {
      setReferrerCode(apiReferrerCode);
    }
  }

  const stats = status?.stats ?? EMPTY_STATS;

  const groupedExchanges = useMemo(() => {
    const rawList: string[] = stats?.eligibleExchanges || stats?.eligible_exchanges || [];
    if (!rawList.length) return [];

    const rates: Record<string, number> = stats?.rebateRates || stats?.rebate_rates || {};
    const multipliers: Record<string, number> = stats?.exchangeMultipliers || stats?.exchange_multipliers || {};

    const map = new Map<string, {
      baseKey: string;
      label: string;
      spotRate?: number;
      futuresRate?: number;
      generalRate?: number;
      maxRate: number;
      multiplier: number;
      isBoosted: boolean;
      rawKeys: string[];
    }>();

    for (const raw of rawList) {
      const norm = normalizeExchangeKey(raw) || raw.split("_")[0].toLowerCase();
      const rate = rates[raw] ?? rates[norm] ?? 0.30;
      const isBitgetPromo = Boolean(promoStatus?.hasActiveCampaign && norm === (promoStatus?.exchangeId?.toLowerCase() || "bitget"));
      const mult = multipliers[raw] ?? multipliers[norm] ?? (isBitgetPromo ? (promoStatus?.rebateMultiplier || 2.0) : 1.0);

      const existing = map.get(norm) || {
        baseKey: norm,
        label: exchangeLabels[norm] || norm.toUpperCase(),
        maxRate: 0,
        multiplier: 1.0,
        isBoosted: false,
        rawKeys: [],
      };

      existing.rawKeys.push(raw);
      const rawLower = raw.toLowerCase();
      if (rawLower.includes("spot")) {
        existing.spotRate = rate;
      } else if (rawLower.includes("futures") || rawLower.includes("swap") || rawLower.includes("linear") || rawLower.includes("usdtm")) {
        existing.futuresRate = rate;
      } else {
        existing.generalRate = rate;
      }

      if (rate > existing.maxRate) {
        existing.maxRate = rate;
      }
      if (mult > existing.multiplier) {
        existing.multiplier = mult;
      }
      if (existing.multiplier > 1.0) {
        existing.isBoosted = true;
      }

      map.set(norm, existing);
    }

    for (const item of map.values()) {
      if (item.futuresRate === undefined) {
        item.futuresRate = item.generalRate ?? item.maxRate;
      }
      if (item.spotRate === undefined) {
        item.spotRate = item.generalRate ?? item.maxRate;
      }
    }

    return Array.from(map.values());
  }, [stats, promoStatus]);

  const [isWalletModalOpen, setIsWalletModalOpen] = useState(false);

  const handleActivate = () => {
    const code = referrerCode.trim() || undefined;
    activateMining(
      { referrerCode: code, referrer_code: code },
      {
        onSuccess: () => {
          toast({
            title: t("common:success", "Success"),
            description: t("miningActivated", "Trade mining successfully activated! Your exchange UID has been resolved and linked automatically."),
          });
          refetch();
        },
        onError: (err: Error) => {
          const errMsg =
            err.message || (err as Error & { detail?: string }).detail || "";
          if (errMsg.includes("WALLET_REQUIRED") || errMsg.includes("wallet")) {
            setIsWalletModalOpen(true);
            return;
          }
          toast({
            variant: "destructive",
            title: t("common:error", "Error"),
            description: errMsg || t("common:errors.somethingWentWrong"),
          });
        }
      }
    );
  };

  const handleDeactivate = () => {
    deactivateMining(undefined, {
      onSuccess: () => {
        toast({
          title: t("common:success", "Success"),
          description: t("miningDeactivated", "Trade mining successfully disabled. Telemetry will not be sent."),
        });
        refetch();
      },
      onError: (err: Error) => {
        toast({
          variant: "destructive",
          title: t("common:error", "Error"),
          description: err?.message || t("common:errors.somethingWentWrong"),
        });
      }
    });
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
    toast({
      description: t("linkCopied", "Link copied to clipboard!"),
    });
  };

  const handleUserClick = (userIdStr?: string | number, username?: string) => {
    let uid: number | undefined;
    if (typeof userIdStr === "number") {
      uid = userIdStr;
    } else if (typeof userIdStr === "string") {
      const parsed = parseInt(userIdStr, 10);
      if (!isNaN(parsed)) uid = parsed;
    }

    if (uid !== undefined) {
      setSelectedUserIdFilter(uid);
      setSelectedUsernameFilter(username || `User #${uid}`);
      setTradesPage(1);
      setActiveSubTab("trades");
    }
  };

  if (isLoading) {
    return (
      <div className="flex h-[80vh] items-center justify-center">
        <AppLoader fullLogo size="xl" text={t("common:loading", "Loading...")} />
      </div>
    );
  }

  if (status?.isGlobalMiningEnabled === false) {
    return <Navigate to="/" replace />;
  }

  const isMiningActive = status?.isMiningEnabled;

  // Render Activation Screen
  if (!isMiningActive) {
    return (
      <div className="min-h-full flex-1 flex flex-col justify-between">
        <div className="flex-1 container max-w-2xl mx-auto py-10 px-4">
          {isMobile && (
            <div className="mb-4 flex items-center">
              <SidebarTrigger className="h-8 w-8 text-white/70 hover:text-white border border-white/10 bg-white/5 hover:bg-white/10 rounded-lg shrink-0" />
            </div>
          )}
          <div className="text-center mb-8">
          <div className="inline-flex p-3 rounded-full bg-primary/10 text-primary mb-4 animate-bounce">
            <Coins className="h-10 w-10" />
          </div>
          <h1 className="text-3xl font-black tracking-tight">{t("activationTitle", "Activate Trade Mining")}</h1>
          <p className="text-muted-foreground mt-2">{t("subtitle", "Provide telemetry and earn $DEPTH tokens on every trade")}</p>
        </div>

        <div className="glass relative rounded-2xl border border-white/10 shadow-2xl p-6 sm:p-8 overflow-hidden animate-fade-up">
          <div className="pointer-events-none absolute -top-16 -right-16 h-48 w-48 rounded-full bg-cyan/15 blur-3xl" />
          <div className="pointer-events-none absolute -bottom-16 -left-16 h-48 w-48 rounded-full bg-azure/10 blur-3xl" />

          <div className="relative z-10 space-y-6">
            <div className="flex items-start gap-3.5 pb-4 border-b border-white/5">
              <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-emerald-500/10 border border-emerald-500/20 text-emerald-400 shrink-0">
                <ShieldCheck className="h-5 w-5" />
              </div>
              <div>
                <h3 className="text-base font-bold text-white">{t("common:privacy", "Privacy & Security")}</h3>
                <p className="text-xs text-white/50 mt-1 leading-relaxed">
                  {t("activationDescription", "By activating Trade Mining, you agree to share anonymous trading telemetry (positions, trade sizes, PnL) with the Central Hub to earn $DEPTH rewards. Your private API keys are never shared.")}
                </p>
              </div>
            </div>

            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <Label htmlFor="referrer_code" className="text-xs font-semibold text-white/80">
                  {t("enterReferrerCode", "Enter Referrer Code (Optional)")}
                </Label>
                {(referrerCode || isAlreadyLinked) && (
                  <Badge variant="outline" className="bg-emerald-500/10 text-emerald-400 border-emerald-500/30 text-[11px] flex items-center gap-1 font-semibold">
                    <CheckCircle2 className="h-3 w-3" />
                    {t("refCodeApplied", "Code Auto-Applied")}
                  </Badge>
                )}
              </div>
              <Input
                id="referrer_code"
                placeholder={t("enterReferrerCodePlaceholder", "e.g., DSN-REF-XXXX-YYYY")}
                value={referrerCode}
                onChange={(e) => setReferrerCode(e.target.value)}
                disabled={isAlreadyLinked}
                className="rounded-xl bg-white/[0.04] border-white/10 text-white placeholder:text-white/30 focus:border-cyan/50 focus:ring-1 focus:ring-cyan/30 font-mono text-sm h-10 transition-colors"
              />
              {referrerCode && (
                <p className="text-[11px] text-emerald-400 font-medium">
                  ✓ {t("referrerCodeDetected", "Referral code detected from registration link.")}
                </p>
              )}
            </div>

            <div className="flex gap-2.5 p-3.5 rounded-xl bg-emerald-500/10 border border-emerald-500/20 text-emerald-400 text-xs leading-normal">
              <CheckCircle2 className="h-4 w-4 shrink-0 mt-0.5" />
              <span>
                {t(
                  "uidLinkedNotice",
                  "Your exchange UID will be resolved and linked automatically using your active API keys when you start mining."
                )}
              </span>
            </div>

            <Button
              onClick={handleActivate}
              disabled={isActivating}
              className="w-full font-bold rounded-xl bg-gradient-to-r from-azure to-cyan text-white shadow-[0_0_25px_-3px_rgba(0,212,255,0.5)] hover:shadow-[0_0_30px_-2px_rgba(0,212,255,0.7)] py-6 text-base gap-2 transition-all"
            >
              {isActivating ? (
                <>
                  <Loader2 className="h-4 w-4 animate-spin" />
                  {t("activating", "Activating...")}
                </>
              ) : (
                <>
                  <Flame className="h-5 w-5 fill-current" />
                  {t("activateButton", "Activate & Start Mining")}
                </>
              )}
            </Button>

            <div className="pt-1 text-center">
              <Button
                variant="ghost"
                size="sm"
                onClick={() => setIsWalletModalOpen(true)}
                className="text-xs text-white/50 hover:text-cyan rounded-lg gap-1.5 transition-colors"
              >
                <Wallet className="h-3.5 w-3.5" />
                {t("connectEVMWallet", "Connect Web3 EVM Wallet (MetaMask)")}
              </Button>
            </div>
          </div>
        </div>
        </div>

        <Footer className="mt-auto flex-shrink-0" />

        <NodeWalletModal
          isOpen={isWalletModalOpen}
          onClose={() => setIsWalletModalOpen(false)}
          onWalletActivated={() => handleActivate()}
        />
      </div>
    );
  }

  // Calculate welcome bonus progress
  const dailyEmission = stats?.daily_emission ?? stats?.dailyEmission ?? 547945;
  const yourEpochReward = stats?.your_epoch_reward ?? stats?.yourEpochReward ?? 0.0;
  const epochTotalRebates = stats?.epoch_total_rebates ?? stats?.epochTotalRebates ?? 0.0;
  const userCumulativeRebate = status?.userCumulativeRebate ?? stats?.your_cumulative_rebates ?? stats?.yourCumulativeRebates ?? stats?.user_cumulative_rebate ?? stats?.userCumulativeRebate ?? stats?.cumulativeRebates ?? epochTotalRebates;
  const totalDistributed = status?.totalDistributed ?? stats?.totalDistributed ?? stats?.serverTotalMined ?? 0.0;

  const welcomeTarget = 1.0;
  const welcomeProgress = Math.min((userCumulativeRebate / welcomeTarget) * 100, 100);
  const inviteLink = `${window.location.origin}/register?ref=${status?.nodeReferralCode || ""}`;

  return (
    <div className="min-h-full flex-1 flex flex-col justify-between">
      <div className="flex-1 container mx-auto py-8 px-4 space-y-8">
        {/* Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-white/5 pb-6">
        <div>
          <div className="flex items-center gap-3">
            {isMobile && (
              <SidebarTrigger className="h-8 w-8 text-white/70 hover:text-white border border-white/10 bg-white/5 hover:bg-white/10 rounded-lg shrink-0" />
            )}
            <h1 className="text-2xl sm:text-3xl font-black tracking-tight flex items-center gap-3 text-white">
              {t("title", "Trade Mining & Referrals")}
              <span className="inline-flex items-center gap-1.5 rounded-full border border-emerald-500/20 bg-emerald-500/10 px-2.5 py-0.5 text-[10px] font-bold uppercase tracking-wider text-emerald-400">
                <span className="h-1.5 w-1.5 rounded-full bg-emerald-400 animate-pulse" />
                {t("connected", "Active")}
              </span>
            </h1>
          </div>
          <p className="text-xs sm:text-sm text-white/50 mt-1">
            {t("subtitle", "Provide telemetry and earn $DEPTH tokens on every trade")}
          </p>
        </div>
        <div className="flex items-center gap-2.5 self-start md:self-auto flex-wrap">
          <Button
            variant="outline"
            size="sm"
            onClick={() => setIsWalletModalOpen(true)}
            className="rounded-xl border-cyan/30 bg-cyan/5 text-cyan hover:bg-cyan/10 hover:text-cyan hover:border-cyan/50 text-xs font-semibold h-9 px-3.5 gap-1.5 transition-all shadow-sm"
          >
            <KeyRound className="h-3.5 w-3.5" />
            <span>{t("nodeWallet", "Node Wallet")}</span>
          </Button>
          <Button
            variant="outline"
            size="sm"
            onClick={handleDeactivate}
            disabled={isDeactivating}
            className="rounded-xl border-white/10 bg-white/[0.03] text-white/60 hover:bg-rose-500/10 hover:text-rose-400 hover:border-rose-500/30 text-xs font-semibold h-9 px-3.5 transition-colors"
          >
            {isDeactivating ? (
              <Loader2 className="h-3 w-3 animate-spin mr-1.5" />
            ) : null}
            {t("disableMining", "Disable Mining")}
          </Button>
          <div className="flex items-center gap-2 border border-white/10 bg-white/[0.03] px-3.5 h-9 rounded-xl">
            <span className="h-2 w-2 rounded-full bg-emerald-400 animate-pulse" />
            <span className="text-xs text-white/60 font-mono font-medium">
              {status?.nodeName || "Node"}
            </span>
          </div>
        </div>
      </div>

      {promoStatus?.hasActiveCampaign && (
        <PromoBanner
          promoStatus={promoStatus}
          onOpenQuests={() => setActiveSubTab("quests")}
        />
      )}

      {/* Sub-Tabs Navigation */}
      <Tabs
        value={activeSubTab}
        onValueChange={(v) =>
          setActiveSubTab(v as "overview" | "referrals" | "trades" | "quests")
        }
        className="w-full"
      >
        <div className="flex items-center overflow-x-auto pb-1 max-w-full touch-pan-x [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
          <TabsList className="inline-flex h-auto w-auto items-center justify-start rounded-xl bg-white/[0.04] border border-white/5 p-1 gap-1 shadow-inner backdrop-blur-md">
            <TabsTrigger
              value="overview"
              className="group relative flex items-center gap-2 rounded-lg px-3.5 py-2 text-xs sm:text-sm font-medium transition-all text-white/50 hover:text-white/80 hover:bg-white/[0.03] data-[state=active]:bg-white/[0.08] data-[state=active]:text-white data-[state=active]:shadow-[inset_0_1px_0_rgba(255,255,255,0.08)] data-[state=active]:border data-[state=active]:border-white/10 whitespace-nowrap"
            >
              <Flame className="w-4 h-4 text-cyan/60 group-hover:text-cyan group-data-[state=active]:text-cyan group-data-[state=active]:drop-shadow-[0_0_8px_rgba(0,212,255,0.85)] transition-all shrink-0" />
              <span>{t("subtabOverview", "Overview & Pools")}</span>
            </TabsTrigger>
            <TabsTrigger
              value="referrals"
              className="group relative flex items-center gap-2 rounded-lg px-3.5 py-2 text-xs sm:text-sm font-medium transition-all text-white/50 hover:text-white/80 hover:bg-white/[0.03] data-[state=active]:bg-white/[0.08] data-[state=active]:text-white data-[state=active]:shadow-[inset_0_1px_0_rgba(255,255,255,0.08)] data-[state=active]:border data-[state=active]:border-white/10 whitespace-nowrap"
            >
              <Users className="w-4 h-4 text-cyan/60 group-hover:text-cyan group-data-[state=active]:text-cyan group-data-[state=active]:drop-shadow-[0_0_8px_rgba(0,212,255,0.85)] transition-all shrink-0" />
              <span>{t("subtabReferrals", "My Referrals Network")}</span>
              {referralsData?.totalInvited !== undefined && (
                <span className="ml-1 px-1.5 py-0.5 rounded-md text-[10px] font-bold bg-cyan/10 text-cyan border border-cyan/20">
                  {referralsData.totalInvited}
                </span>
              )}
            </TabsTrigger>
            <TabsTrigger
              value="trades"
              className="group relative flex items-center gap-2 rounded-lg px-3.5 py-2 text-xs sm:text-sm font-medium transition-all text-white/50 hover:text-white/80 hover:bg-white/[0.03] data-[state=active]:bg-white/[0.08] data-[state=active]:text-white data-[state=active]:shadow-[inset_0_1px_0_rgba(255,255,255,0.08)] data-[state=active]:border data-[state=active]:border-white/10 whitespace-nowrap"
            >
              <Activity className="w-4 h-4 text-cyan/60 group-hover:text-cyan group-data-[state=active]:text-cyan group-data-[state=active]:drop-shadow-[0_0_8px_rgba(0,212,255,0.85)] transition-all shrink-0" />
              <span>{t("subtabTrades", "Trades & Telemetry")}</span>
              {tradesData?.total !== undefined && (
                <span className="ml-1 px-1.5 py-0.5 rounded-md text-[10px] font-bold bg-cyan/10 text-cyan border border-cyan/20">
                  {tradesData.total}
                </span>
              )}
            </TabsTrigger>
            {promoStatus?.hasActiveCampaign && (
              <TabsTrigger
                value="quests"
                className="group relative flex items-center gap-2 rounded-lg px-3.5 py-2 text-xs sm:text-sm font-medium transition-all text-white/50 hover:text-white/80 hover:bg-white/[0.03] data-[state=active]:bg-white/[0.08] data-[state=active]:text-white data-[state=active]:shadow-[inset_0_1px_0_rgba(255,255,255,0.08)] data-[state=active]:border data-[state=active]:border-white/10 whitespace-nowrap"
              >
                <span className="text-sm">🎁</span>
                <span>{t("subtabQuests", "Quests")}</span>
                <span className="text-xs animate-pulse">🔥</span>
              </TabsTrigger>
            )}
          </TabsList>
        </div>
      </Tabs>

      {activeSubTab === "quests" && promoStatus?.hasActiveCampaign ? (
        <PromoQuestsTab promoStatus={promoStatus} />
      ) : activeSubTab === "referrals" ? (
        <div className="space-y-6">
          {/* Summary Stat Cards */}
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <StatCard
              title={t("totalInvited", "Total Invited Nodes")}
              value={`${referralsData?.totalInvited || 0}`}
              subtitle={t("totalInvitedSubtitle", "Nodes joined using your ref link")}
              icon={Users}
              isLoading={isLoadingReferrals}
              accent="#0066ff"
            />
            <StatCard
              title={t("activeReferrals", "Active Trading Nodes")}
              value={`${referralsData?.activeReferrals || 0}`}
              subtitle={t("activeReferralsSubtitle", "Nodes active in last 10 mins")}
              icon={Flame}
              isLoading={isLoadingReferrals}
              accent="#ff5c00"
            />
            <StatCard
              title={t("totalReferralVolume", "Referrals Volume")}
              value={`$${referralsData?.totalReferralVolumeUsdt?.toFixed(2) || "0.00"}`}
              subtitle={t("totalReferralVolumeSubtitle", "Total USDT volume generated")}
              icon={Activity}
              isLoading={isLoadingReferrals}
              accent="#00d4ff"
            />
            <StatCard
              title={t("referralBonusEarned", "+10% Referral Earnings")}
              value={`${referralsData?.totalReferralRewardsDepth?.toFixed(2) || "0.00"} $DEPTH`}
              subtitle={t("referralBonusEarnedSubtitle", "Total 10% daily boost rewards")}
              icon={Sparkles}
              isLoading={isLoadingReferrals}
              accent="#10e0a0"
            />
          </div>

          {/* Referral List Table & Search */}
          <div className="glass relative rounded-2xl border border-white/10 shadow-xl p-6 space-y-4 animate-fade-up overflow-hidden">
            <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
              <div>
                <h3 className="text-base font-bold tracking-tight text-white flex items-center gap-2">
                  <Users className="h-4 w-4 text-cyan" />
                  {t("referralListTitle", "Invited Nodes & User Network")}
                </h3>
                <p className="text-xs text-white/50 mt-0.5">
                  {t("referralListDesc", "Track your referrals, trading volumes, and 10% bonus earnings in real-time.")}
                </p>
              </div>
              <div className="relative w-full sm:w-64">
                <Search className="h-4 w-4 absolute left-3 top-3 text-white/40" />
                <Input
                  placeholder={t("searchReferralPlaceholder", "Search by Node ID or Name...")}
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  className="pl-9 h-10 rounded-xl bg-white/[0.04] border-white/10 text-white placeholder:text-white/30 text-xs focus:border-cyan/50 focus:ring-1 focus:ring-cyan/30 transition-colors"
                />
              </div>
            </div>

            {isLoadingReferrals ? (
              <div className="py-8 text-center text-sm text-white/50">
                <Loader2 className="h-6 w-6 animate-spin mx-auto mb-2 text-cyan" />
                {t("loadingReferrals", "Loading referrals network...")}
              </div>
            ) : !referralsData?.referrals || referralsData.referrals.length === 0 ? (
              <div className="py-12 text-center border border-dashed border-white/10 rounded-xl bg-white/[0.02] space-y-3">
                <UserPlus className="h-10 w-10 text-white/20 mx-auto" />
                <div className="font-semibold text-sm text-white/60">
                  {t("noReferralsYet", "No invited nodes or users yet")}
                </div>
                <p className="text-xs text-white/40 max-w-sm mx-auto">
                  {t("noReferralsDesc", "Share your referral link or node deploy command to invite friends and earn 10% of their daily mining rewards forever!")}
                </p>
              </div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-left text-xs">
                  <thead>
                    <tr className="border-b border-white/10 text-white/40 uppercase tracking-wider text-[11px] font-medium">
                      <th className="pb-3 px-2">{t("thNodeUser", "Node / User")}</th>
                      <th className="pb-3 px-2">{t("thStatus", "Status")}</th>
                      <th className="pb-3 px-2">{t("thJoinedDate", "Joined Date")}</th>
                      <th className="pb-3 px-2 text-right">{t("thVolumeUsdt", "Volume (USDT)")}</th>
                      <th className="pb-3 px-2 text-right">{t("thMinedDepth", "Mined ($DEPTH)")}</th>
                      <th className="pb-3 px-2 text-right">{t("thBonusEarned", "Your +10% Bonus")}</th>
                      <th className="pb-3 px-2 text-center">{t("thWelcomeBonus", "Welcome Bonus")}</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-white/5">
                    {referralsData.referrals
                      .filter((ref) =>
                        ref.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
                        ref.id.toLowerCase().includes(searchQuery.toLowerCase())
                      )
                      .map((ref) => (
                        <tr
                          key={ref.id}
                          onClick={() => handleUserClick(ref.id, ref.name)}
                          className="hover:bg-white/[0.03] transition-colors cursor-pointer group"
                          title="Click to view trades for this referral"
                        >
                          <td className="py-3 px-2 font-mono font-bold text-white group-hover:text-cyan transition-colors flex items-center gap-1.5">
                            {ref.name}
                            <ArrowUpRight className="h-3 w-3 opacity-0 group-hover:opacity-100 transition-opacity text-cyan" />
                          </td>
                          <td className="py-3 px-2">
                            {ref.status === "active" ? (
                              <Badge className="bg-emerald-500/10 text-emerald-400 border-emerald-500/20 text-[10px] font-bold">
                                {t("statusOnline", "Online")}
                              </Badge>
                            ) : (
                              <Badge variant="secondary" className="text-[10px] bg-white/[0.04] text-white/50 border-white/5">
                                {t("statusIdle", "Idle")}
                              </Badge>
                            )}
                          </td>
                          <td className="py-3 px-2 text-white/50">
                            {new Date(ref.createdAt).toLocaleDateString()}
                          </td>
                          <td className="py-3 px-2 text-right font-mono font-bold text-white">
                            ${ref.tradeVolumeUsdt.toFixed(2)}
                          </td>
                          <td className="py-3 px-2 text-right font-mono font-bold text-amber-400">
                            {ref.totalMinedDepth.toFixed(2)} $DEPTH
                          </td>
                          <td className="py-3 px-2 text-right font-mono font-bold text-emerald-400">
                            +{ref.referralBonusEarned.toFixed(2)} $DEPTH
                          </td>
                          <td className="py-3 px-2 text-center">
                            {ref.hasWelcomeBonus ? (
                              <Badge className="bg-yellow-500/10 text-yellow-400 border-yellow-500/20 text-[9px]">
                                {t("welcomeBonusClaimed", "Claimed")}
                              </Badge>
                            ) : (
                              <span className="text-white/30 text-[11px]">Pending</span>
                            )}
                          </td>
                        </tr>
                      ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </div>
      ) : activeSubTab === "trades" ? (
        <div className="space-y-6">
          <div className="glass relative rounded-2xl border border-white/10 p-6 shadow-xl space-y-6 animate-fade-up overflow-hidden">
            <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-4 mb-2">
              <div>
                <h3 className="text-base font-bold text-white flex items-center gap-2">
                  <Activity className="h-4 w-4 text-cyan" />
                  {t("tradesTitle", "Telemetry Trade Reports History")}
                </h3>
                <p className="text-xs text-white/50 mt-0.5">
                  {t("tradesDesc", "Inspect trade reports, exchange verification status, and daily mining rewards.")}
                </p>
              </div>

              {/* Scope Sub-tabs Pills: All / My Trades / Referral Trades */}
              <div className="inline-flex rounded-xl bg-white/[0.04] border border-white/5 p-1 gap-1 shadow-inner backdrop-blur-md">
                <button
                  onClick={() => {
                    setSelectedScopeFilter("all");
                    setSelectedUserIdFilter(undefined);
                    setSelectedUsernameFilter("");
                    setTradesPage(1);
                  }}
                  className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-all ${
                    selectedScopeFilter === "all" && selectedUserIdFilter === undefined
                      ? "bg-white/[0.08] text-white shadow-[inset_0_1px_0_rgba(255,255,255,0.08)] border border-white/10"
                      : "text-white/50 hover:text-white/80 hover:bg-white/[0.03]"
                  }`}
                >
                  <Activity className="h-3.5 w-3.5 text-cyan" />
                  <span>{t("allTrades", "Все сделки")}</span>
                </button>
                <button
                  onClick={() => {
                    setSelectedScopeFilter("my");
                    setSelectedUserIdFilter(undefined);
                    setSelectedUsernameFilter("");
                    setTradesPage(1);
                  }}
                  className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-all ${
                    selectedScopeFilter === "my"
                      ? "bg-white/[0.08] text-white shadow-[inset_0_1px_0_rgba(255,255,255,0.08)] border border-white/10"
                      : "text-white/50 hover:text-white/80 hover:bg-white/[0.03]"
                  }`}
                >
                  <UserCheck className="h-3.5 w-3.5 text-cyan" />
                  <span>{t("myTrades", "Мои сделки")}</span>
                </button>
                <button
                  onClick={() => {
                    setSelectedScopeFilter("referrals");
                    setSelectedUserIdFilter(undefined);
                    setSelectedUsernameFilter("");
                    setTradesPage(1);
                  }}
                  className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-all ${
                    selectedScopeFilter === "referrals"
                      ? "bg-white/[0.08] text-white shadow-[inset_0_1px_0_rgba(255,255,255,0.08)] border border-white/10"
                      : "text-white/50 hover:text-white/80 hover:bg-white/[0.03]"
                  }`}
                >
                  <Users className="h-3.5 w-3.5 text-cyan" />
                  <span>{t("referralTrades", "Сделки рефералов")}</span>
                </button>
              </div>
            </div>

            {/* Filters Bar: Search, Status, Exchange */}
            <div className="flex flex-wrap items-center justify-between gap-3 p-2.5 rounded-xl bg-white/[0.02] border border-white/5">
              <div className="flex flex-wrap items-center gap-2 flex-1">
                {/* Search Input */}
                <div className="relative w-full sm:w-56">
                  <Search className="h-4 w-4 absolute left-3 top-2.5 text-white/40" />
                  <Input
                    placeholder={t("filterUserPlaceholder", "Search symbol or order...")}
                    value={tradesSearch}
                    onChange={(e) => {
                      setTradesSearch(e.target.value);
                      setTradesPage(1);
                    }}
                    className="pl-9 h-9 rounded-xl bg-white/[0.04] border-white/10 text-white placeholder:text-white/30 text-xs focus:border-cyan/50 focus:ring-1 focus:ring-cyan/30 transition-colors"
                  />
                </div>

                {/* Status Filter */}
                <div className="inline-flex items-center rounded-xl border border-white/5 bg-white/[0.04] p-1 gap-1">
                  {["ALL", "PENDING", "VERIFIED", "REJECTED"].map((st) => (
                    <button
                      key={st}
                      onClick={() => {
                        setSelectedStatusFilter(st);
                        setTradesPage(1);
                      }}
                      className={`px-2.5 py-1 text-xs font-medium rounded-lg transition-colors ${
                        selectedStatusFilter === st
                          ? "bg-white/[0.08] text-white shadow-[inset_0_1px_0_rgba(255,255,255,0.08)] border border-white/10"
                          : "text-white/50 hover:text-white/80 hover:bg-white/[0.03]"
                      }`}
                    >
                      {st === "ALL"
                        ? t("allStatuses", "All Statuses")
                        : st === "PENDING"
                        ? t("statusPending", "Pending")
                        : st === "VERIFIED"
                        ? t("statusVerified", "Verified")
                        : t("statusRejected", "Rejected")}
                    </button>
                  ))}
                </div>

                {/* Exchange Filter Select */}
                <div className="w-[150px]">
                  <Select
                    value={selectedExchangeFilter}
                    onValueChange={(val) => {
                      setSelectedExchangeFilter(val);
                      setTradesPage(1);
                    }}
                  >
                    <SelectTrigger className="h-9 rounded-xl text-xs font-medium bg-white/[0.04] border-white/10 text-white focus:border-cyan/50">
                      <SelectValue placeholder={t("allExchanges", "All Exchanges")} />
                    </SelectTrigger>
                    <SelectContent className="rounded-xl bg-obsidian/95 border border-white/10 text-white backdrop-blur-2xl shadow-2xl p-1">
                      <SelectItem value="all" className="rounded-lg py-1.5 px-2.5 text-xs font-medium text-white/90 focus:bg-white/[0.08] focus:text-white cursor-pointer transition-colors">
                        {t("allExchanges", "All Exchanges")}
                      </SelectItem>
                      {Array.from(
                        new Set([
                          "okx",
                          "weex",
                          "bybit",
                          ...(stats?.eligibleExchanges || stats?.eligible_exchanges || []).map((e: string) =>
                            e.split("_")[0].toLowerCase()
                          ),
                        ])
                      ).map((ex) => (
                        <SelectItem key={ex} value={ex} className="rounded-lg py-1.5 px-2.5 text-xs uppercase font-medium text-white/90 focus:bg-white/[0.08] focus:text-white cursor-pointer transition-colors">
                          <div className="flex items-center gap-2">
                            <ExchangeBadge exchange={ex} size="xs" />
                            <span>{ex}</span>
                          </div>
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
              </div>

              <Button
                variant="outline"
                size="sm"
                onClick={() => refetchTrades()}
                className="h-9 w-9 rounded-xl border-white/10 bg-white/[0.04] text-white/70 hover:bg-white/[0.08] hover:text-white transition-colors p-0"
                title="Refresh trades"
              >
                <RefreshCw className={`h-3.5 w-3.5 ${isLoadingTrades ? "animate-spin" : ""}`} />
              </Button>
            </div>

            {/* User Filter Indicator Badge */}
            {selectedUserIdFilter !== undefined && (
              <div className="mb-4 flex items-center gap-2 bg-cyan/10 border border-cyan/30 rounded-xl px-3 py-1.5 text-xs text-cyan font-medium w-fit">
                <Users className="h-3.5 w-3.5" />
                <span>
                  {t("showingUserTradesOnly", "Showing trades for user:")}{" "}
                  <strong className="font-bold">{selectedUsernameFilter || `#${selectedUserIdFilter}`}</strong>
                </span>
                <button
                  onClick={() => {
                    setSelectedUserIdFilter(undefined);
                    setSelectedUsernameFilter("");
                    setTradesPage(1);
                  }}
                  className="ml-2 hover:bg-cyan/20 p-0.5 rounded transition-colors text-cyan"
                  title={t("clearUserFilter", "Clear Filter")}
                >
                  <X className="h-3.5 w-3.5" />
                </button>
              </div>
            )}

            {/* Trades Table */}
            {isLoadingTrades ? (
              <div className="py-12 text-center text-sm text-white/50">
                <Loader2 className="h-6 w-6 animate-spin mx-auto mb-2 text-cyan" />
                {t("common:loading", "Loading trades...")}
              </div>
            ) : !tradesData?.items || tradesData.items.length === 0 ? (
              <div className="py-12 text-center border border-dashed border-white/10 rounded-xl bg-white/[0.02] space-y-3">
                <Activity className="h-10 w-10 text-white/20 mx-auto" />
                <div className="font-semibold text-sm text-white/60">
                  {t("noTradesYet", "No telemetry trade reports yet")}
                </div>
                <p className="text-xs text-white/40 max-w-sm mx-auto">
                  {t("noTradesDesc", "Trades will automatically appear here as trading bots execute orders.")}
                </p>
              </div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-left text-xs">
                  <thead>
                    <tr className="border-b border-white/10 text-white/40 uppercase tracking-wider text-[11px] font-medium">
                      <th className="pb-3 px-2">{t("thNodeUser", "Node / User")}</th>
                      <th className="pb-3 px-2">{t("thExchangeMarket", "Exchange / Market")}</th>
                      <th className="pb-3 px-2">Symbol</th>
                      <th className="pb-3 px-2">{t("thDirection", "Direction")}</th>
                      <th className="pb-3 px-2 text-right">{t("thVolumeUsdt", "Volume (USDT)")}</th>
                      <th className="pb-3 px-2 text-center">{t("thVerificationStatus", "Verification")}</th>
                      <th className="pb-3 px-2 text-right">{t("thReward", "$DEPTH Reward")}</th>
                      <th className="pb-3 px-2 text-right">{t("thJoinedDate", "Date")}</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-white/5">
                    {tradesData.items.map((trd) => (
                      <tr key={trd.id} className="hover:bg-white/[0.02] transition-colors">
                        <td className="py-3 px-2 font-mono font-bold text-white">
                          <div>
                            {trd.username ? (
                              <span
                                className="text-cyan hover:underline cursor-pointer"
                                onClick={() => trd.userId && handleUserClick(trd.userId, trd.username)}
                              >
                                {trd.username}
                              </span>
                            ) : (
                              <span className="text-white/50 truncate max-w-[120px] inline-block" title={trd.nodeUuid}>
                                {trd.nodeUuid}
                              </span>
                            )}
                            <div className="mt-0.5">
                              {trd.isOwnTrade ? (
                                <Badge variant="outline" className="text-[10px] px-1.5 py-0 h-4 bg-cyan/10 text-cyan border-cyan/30 font-medium">
                                  {t("ownTradeBadge", "Моя сделка")}
                                </Badge>
                              ) : (
                                <Badge variant="outline" className="text-[10px] px-1.5 py-0 h-4 bg-amber-500/10 text-amber-400 border-amber-500/30 font-medium inline-flex items-center gap-0.5">
                                  <Users className="h-2.5 w-2.5" />
                                  {t("referralTradeBadge", "Реферал")}
                                </Badge>
                              )}
                            </div>
                          </div>
                        </td>
                        <td className="py-3 px-2">
                          <div className="flex items-center gap-2.5">
                            <ExchangeBadge exchange={trd.exchangeId} size="sm" className="shadow-sm border-white/10" />
                            <div>
                              <span className="uppercase font-semibold text-white/90 block leading-tight">{trd.exchangeId || "EXCHANGE"}</span>
                              <span className="text-white/40 text-[10px] block capitalize leading-tight">{trd.marketType || "futures"}</span>
                            </div>
                          </div>
                        </td>
                        <td className="py-3 px-2 font-mono font-bold text-white">
                          {trd.symbol}
                        </td>
                        <td className="py-3 px-2">
                          <Badge
                            className={
                              trd.direction?.toLowerCase() === "buy" || trd.direction?.toLowerCase() === "long"
                                ? "bg-emerald-500/10 text-emerald-400 border-emerald-500/20 text-[10px] uppercase font-bold"
                                : "bg-rose-500/10 text-rose-400 border-rose-500/20 text-[10px] uppercase font-bold"
                            }
                          >
                            {trd.direction || "BUY"}
                          </Badge>
                        </td>
                        <td className="py-3 px-2 text-right font-mono font-bold text-white">
                          ${trd.tradeVolumeUsdt.toFixed(2)}
                        </td>
                        <td className="py-3 px-2 text-center">
                          {trd.verificationStatus === "VERIFIED" ? (
                            <Badge className="bg-emerald-500/10 text-emerald-400 border-emerald-500/20 text-[10px] font-bold inline-flex items-center gap-1">
                              <CheckCircle2 className="h-3 w-3" />
                              {t("statusVerified", "Verified")}
                            </Badge>
                          ) : trd.verificationStatus === "REJECTED" ? (
                            <Badge variant="destructive" className="text-[10px] font-bold inline-flex items-center gap-1 bg-rose-500/10 text-rose-400 border-rose-500/30" title={trd.verificationError || "Verification rejected"}>
                              <AlertCircle className="h-3 w-3" />
                              {t("statusRejected", "Rejected")}
                            </Badge>
                          ) : trd.isMiningEligible === false ? (
                            <Badge
                              variant="destructive"
                              className="bg-rose-500/10 text-rose-400 border-rose-500/30 text-[10px] font-bold inline-flex items-center gap-1 cursor-help"
                              title={trd.verificationError || t("reasonNotEligibleDefault", "Failed quality gate (min hold time / min price movement)")}
                            >
                              <AlertCircle className="h-3 w-3 shrink-0" />
                              {t("statusNotEligible", "Not Eligible")}
                            </Badge>
                          ) : (
                            <Badge variant="secondary" className="bg-amber-500/10 text-amber-400 border-amber-500/20 text-[10px]" title={trd.verificationError}>
                              {t("statusPending", "Pending")}
                            </Badge>
                          )}
                        </td>
                        <td className="py-3 px-2 text-right font-mono font-bold text-amber-400">
                          +{trd.rewardTokens.toFixed(2)} $DEPTH
                        </td>
                        <td className="py-3 px-2 text-right text-white/50 font-mono text-[11px]">
                          {new Date(trd.createdAt).toLocaleString()}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}

            {/* Pagination Bar */}
            {tradesData && tradesData.totalPages > 1 && (
              <div className="mt-6 flex items-center justify-between border-t border-white/5 pt-4 text-xs text-white/50">
                <div>
                  Showing Page <strong className="text-white">{tradesData.page}</strong> of{" "}
                  <strong className="text-white">{tradesData.totalPages}</strong> (Total: {tradesData.total} trades)
                </div>
                <div className="flex items-center gap-2">
                  <Button
                    variant="outline"
                    size="sm"
                    disabled={tradesPage <= 1}
                    onClick={() => setTradesPage((p) => Math.max(1, p - 1))}
                    className="h-8 rounded-xl border-white/10 bg-white/[0.04] text-white/70 hover:bg-white/[0.08] hover:text-white text-xs gap-1 transition-colors"
                  >
                    <ChevronLeft className="h-3.5 w-3.5" />
                    {t("pagePrev", "Previous")}
                  </Button>
                  <Button
                    variant="outline"
                    size="sm"
                    disabled={tradesPage >= tradesData.totalPages}
                    onClick={() => setTradesPage((p) => p + 1)}
                    className="h-8 rounded-xl border-white/10 bg-white/[0.04] text-white/70 hover:bg-white/[0.08] hover:text-white text-xs gap-1 transition-colors"
                  >
                    {t("pageNext", "Next")}
                    <ChevronRight className="h-3.5 w-3.5" />
                  </Button>
                </div>
              </div>
            )}
          </div>
        </div>
      ) : (
        <>
          {/* Grid Stats */}
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5">
            <StatCard
              title={t("totalMined", "Total Mined")}
              value={`${status?.totalMined?.toFixed(2) || "0.00"} $DEPTH`}
              subtitle={t("totalMinedSubtitle", "All-time accumulated earnings")}
              icon={Coins}
              accent="#00d4ff"
              isLoading={isLoading}
            />
            <StatCard
              title={t("todayEstReward", "Today's Est. Reward")}
              value={`${yourEpochReward >= 1000 ? Math.round(yourEpochReward).toLocaleString("en-US").replace(/,/g, " ") : yourEpochReward.toFixed(2)} $DEPTH`}
              subtitle={t("todayEstRewardSubtitle", "Expected from current daily pool")}
              icon={Flame}
              accent="#ff5c00"
              isLoading={isLoading}
            />
            <StatCard
              title={t("todayRebates", "Today's Rebates")}
              value={`$${epochTotalRebates.toFixed(2)}`}
              subtitle={t("todayRebatesSubtitle", "USDT commission rebates today")}
              icon={Activity}
              accent="#0066ff"
              isLoading={isLoading}
            />
            <StatCard
              title={t("dailyEmission", "Daily Emission Pool")}
              value={`${dailyEmission.toLocaleString()} $DEPTH`}
              subtitle={t("dailyEmissionSubtitle", "Shared daily emission pool")}
              icon={Sparkles}
              accent="#a855f7"
              isLoading={isLoading}
            />
            <StatCard
              title={t("totalDistributed", "Total Distributed")}
              value={`${totalDistributed >= 1000 ? Math.round(totalDistributed).toLocaleString("en-US").replace(/,/g, " ") : totalDistributed.toFixed(2)} $DEPTH`}
              subtitle={t("totalDistributedSubtitle", "Distributed across all epochs")}
              icon={Award}
              accent="#10e0a0"
              isLoading={isLoading}
            />
          </div>

          {/* Node Sharing Policy & Supported Exchanges (Side by side on lg screens) */}
          {((status?.userRewardSharePercent !== undefined || stats?.userRatio !== undefined) || groupedExchanges.length > 0) && (
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-5 items-stretch">
              {/* Left: Node Sharing Policy */}
              {(status?.userRewardSharePercent !== undefined || stats?.userRatio !== undefined) && (
                <div className="glass relative rounded-2xl border border-white/10 shadow-xl overflow-hidden p-5 flex flex-col justify-between h-full">
                  <div>
                    <div className="flex items-center gap-2 mb-3">
                      <ShieldCheck className="h-4 w-4 text-cyan-400" />
                      <h3 className="text-xs font-semibold uppercase tracking-wider text-white/70">
                        {t("nodeSharingPolicy", "Node Sharing Policy")}
                      </h3>
                    </div>
                    <div className="grid grid-cols-1 sm:grid-cols-3 gap-2.5">
                      <div className="p-3 rounded-xl border border-white/10 bg-white/[0.02] backdrop-blur-sm flex flex-col justify-between">
                        <span className="text-[11px] text-white/50 block font-medium mb-1 leading-tight">{t("nodeSharePercentage", "Node Share Percentage")}</span>
                        <span className="text-lg sm:text-xl font-mono font-bold text-cyan-400">{status?.userRewardSharePercent ?? 0}%</span>
                      </div>
                      {stats?.userRatio !== undefined && (
                        <div className="p-3 rounded-xl border border-white/10 bg-white/[0.02] backdrop-blur-sm flex flex-col justify-between">
                          <span className="text-[11px] text-white/50 block font-medium mb-1 leading-tight">{t("yourVolumeShare", "Your Volume Share (Today)")}</span>
                          <span className="text-lg sm:text-xl font-mono font-bold text-white">{(stats.userRatio * 100).toFixed(2)}%</span>
                        </div>
                      )}
                      {status?.userTradeVolume !== undefined && (
                        <div className="p-3 rounded-xl border border-white/10 bg-white/[0.02] backdrop-blur-sm flex flex-col justify-between">
                          <span className="text-[11px] text-white/50 block font-medium mb-1 leading-tight">{t("yourTotalVolume", "Your Total Volume")}</span>
                          <span className="text-lg sm:text-xl font-mono font-bold text-white">
                            {status.userTradeVolume.toFixed(2)} <span className="text-xs text-white/50 font-sans">USDT</span>
                          </span>
                        </div>
                      )}
                    </div>
                  </div>
                  <div className="mt-3.5 pt-3 border-t border-white/10 flex items-start gap-2 text-[11px] text-white/50 bg-white/[0.01] p-2.5 rounded-xl border border-white/5">
                    <Activity className="h-3.5 w-3.5 text-cyan-400 shrink-0 mt-0.5" />
                    <p className="leading-snug">
                      {t("nodeSharingPolicyDesc", "Rewards are distributed in real-time according to verified trade volume share and active node policy.")}
                    </p>
                  </div>
                </div>
              )}

              {/* Right: Supported Exchanges & Rebate Rates */}
              {groupedExchanges.length > 0 && (
                <div className="glass relative rounded-2xl border border-white/10 shadow-xl overflow-hidden p-5 flex flex-col justify-between h-full">
                  <div>
                    <div className="flex items-center gap-2 mb-1.5">
                      <Globe className="h-4 w-4 text-cyan-400" />
                      <h3 className="text-xs font-semibold uppercase tracking-wider text-white/70">
                        {t("supportedExchanges", "Supported Mining Exchanges & Rebates")}
                      </h3>
                    </div>
                    <p className="text-[11px] text-white/50 mb-3 leading-tight">
                      {t("supportedExchangesDesc", "Trade mining rewards are calculated for live trades executed on the following exchanges:")}
                    </p>
                    <div className="flex flex-wrap gap-2 pt-0.5">
                      {groupedExchanges.map((exItem) => {
                        const isBitget = exItem.baseKey === "bitget";
                        const isOkx = exItem.baseKey === "okx";
                        const isBybit = exItem.baseKey === "bybit";

                        const tooltipExtra = isBitget
                          ? t("rebateRateTooltipBitget", "Base broker rate (35%) + 2.0x Mining Multiplier! Trading on Bitget earns 2x $DEPTH token yield per USDT rebate.")
                          : isOkx
                          ? t("rebateRateTooltipOkx", "Base broker rate (30%). When trading under our affiliate link, rebates stack (30% + 7.5% = 37.5%), earning up to 5x more tokens compared to third-party referrals.")
                          : isBybit
                          ? t("rebateRateTooltipBybit", "Base broker rate (40-50%). Trading under our affiliate link maximizes your effective rebate and token mining yield.")
                          : exItem.isBoosted
                          ? `${exItem.multiplier}x Trade Mining Reward Multiplier active for ${exItem.label}.`
                          : t("rebateRateTooltipDefault", "Base broker rebate rate. Mining rewards are distributed proportionally to verified trading volume and fees.");

                        return (
                          <TooltipProvider key={exItem.baseKey} delayDuration={150}>
                            <Tooltip>
                              <TooltipTrigger asChild>
                                <div className={`group flex items-center gap-2 border ${exItem.isBoosted ? "border-amber-500/40 bg-amber-500/10 hover:border-amber-500/60 shadow-[0_0_12px_rgba(245,158,11,0.15)]" : "border-white/10 bg-white/[0.03] hover:border-cyan-500/40 hover:bg-white/[0.06]"} transition-all px-3 py-2 rounded-xl text-xs cursor-help backdrop-blur-md`}>
                                  <ExchangeBadge exchange={exItem.baseKey} size="xs" />
                                  <span className="font-mono font-bold uppercase text-white/90 text-xs tracking-wide">{exItem.label}</span>
                                  {exItem.isBoosted && (
                                    <Badge className="bg-amber-500/20 text-amber-300 border-amber-500/40 text-[10px] font-mono font-bold flex items-center gap-1 animate-pulse rounded-md px-1.5 py-0.5">
                                      🔥 {exItem.multiplier}x
                                    </Badge>
                                  )}
                                  <Info className="h-3 w-3 text-white/40 group-hover:text-cyan-400 transition-colors ml-0.5" />
                                </div>
                              </TooltipTrigger>
                              <TooltipContent side="top" className="max-w-xs text-xs p-3 shadow-2xl bg-[#0c121e] text-white/90 border border-white/15 rounded-xl backdrop-blur-xl space-y-2">
                                <div className="flex items-center justify-between border-b border-white/10 pb-1.5">
                                  <div className="flex items-center gap-2 font-bold text-white">
                                    <ExchangeBadge exchange={exItem.baseKey} size="xs" />
                                    <span>{exItem.label}</span>
                                  </div>
                                  {exItem.isBoosted && (
                                    <span className="text-[10px] text-amber-400 font-mono font-bold">
                                      🔥 {exItem.multiplier}x BOOST
                                    </span>
                                  )}
                                </div>
                                <div className="space-y-1 text-[11px] font-mono">
                                  <div className="flex items-center justify-between">
                                    <span className="text-white/60 font-sans">{t("futuresRebate", "Futures Rebate")}:</span>
                                    <span className="text-cyan-300 font-bold">{((exItem.futuresRate ?? exItem.maxRate) * 100).toFixed(0)}%</span>
                                  </div>
                                  <div className="flex items-center justify-between">
                                    <span className="text-white/60 font-sans">{t("spotRebate", "Spot Rebate")}:</span>
                                    <span className="text-cyan-300 font-bold">{((exItem.spotRate ?? exItem.maxRate) * 100).toFixed(0)}%</span>
                                  </div>
                                </div>
                                <p className="text-[10px] text-white/70 leading-relaxed pt-1.5 border-t border-white/5">
                                  {tooltipExtra}
                                </p>
                              </TooltipContent>
                            </Tooltip>
                          </TooltipProvider>
                        );
                      })}
                    </div>
                  </div>
                  <div className="mt-3.5 pt-3 border-t border-white/10 flex items-start gap-2 text-[11px] text-white/50 bg-white/[0.01] p-2.5 rounded-xl border border-white/5">
                    <ShieldCheck className="h-3.5 w-3.5 text-cyan-400 shrink-0 mt-0.5" />
                    <p className="leading-snug">
                      {t("supportedExchangesRebateNote", "Rewards are directly tied to the fee rebate generated: the higher the exchange rebate rate, the higher your $DEPTH reward accordingly. The Central Hub securely verifies every trade directly via the exchanges' broker APIs.")}
                    </p>
                  </div>
                </div>
              )}
            </div>
          )}

          {/* Interactive Cards */}
          <div className="grid gap-6 md:grid-cols-2">
            {/* Left Column: Welcome Bonus + Mining Rate */}
            <div className="flex flex-col gap-3.5 h-full">
              {/* Welcome Bonus Card */}
              <div className="glass relative rounded-2xl border border-white/10 shadow-xl overflow-hidden p-3.5 sm:p-4 shrink-0">
                <div className="absolute -top-16 -right-16 w-36 h-36 rounded-full bg-amber-500/10 blur-3xl pointer-events-none" />
                <div className="relative">
                  <div className="flex items-center justify-between mb-1">
                    <div className="flex items-center gap-2">
                      <div className="p-1.5 rounded-lg bg-amber-500/10 border border-amber-500/20 text-amber-400">
                        <Coins className="h-4 w-4" />
                      </div>
                      <h3 className="text-sm font-bold text-white tracking-wide">
                        {t("welcomeBonus", "Welcome Bonus")}
                      </h3>
                    </div>
                    {status?.hasWelcomeBonus && (
                      <Badge className="bg-amber-500/15 text-amber-300 border-amber-500/30 font-mono font-bold uppercase tracking-wider text-[9px] rounded-md px-2 py-0.5">
                        {t("welcomeBonusClaimed", "Claimed")}
                      </Badge>
                    )}
                  </div>
                  <p className="text-[11px] text-white/50 mb-2">
                    {t("welcomeBonusDesc", "Generate at least $1.0 of cumulative rebate to claim your welcome bonus.")}
                  </p>

                  {status?.hasWelcomeBonus ? (
                    <div className="bg-amber-500/10 border border-amber-500/20 rounded-xl p-2 sm:p-2.5 flex items-center gap-2.5">
                      <ShieldCheck className="h-4.5 w-4.5 text-amber-400 shrink-0" />
                      <div>
                        <h4 className="font-bold text-xs text-amber-300 leading-tight">
                          {t("welcomeBonusClaimed", "Welcome Bonus Claimed!")}
                        </h4>
                        <p className="text-[10px] text-white/60 mt-0.5">
                          {t("welcomeBonusClaimedDesc", "1000 $DEPTH has been credited to your node balance.")}
                        </p>
                      </div>
                    </div>
                  ) : (
                    <div className="space-y-1.5 bg-white/[0.02] border border-white/5 p-2.5 rounded-xl">
                      <div className="flex justify-between text-[10.5px] font-mono text-white/70">
                        <span>{t("welcomeBonusProgress", { current: userCumulativeRebate.toFixed(2), target: welcomeTarget.toFixed(2) })}</span>
                        <span className="text-amber-400 font-bold">{Math.round(welcomeProgress)}%</span>
                      </div>
                      <Progress value={welcomeProgress} className="h-1.5 bg-white/10 rounded-full overflow-hidden" />
                    </div>
                  )}
                </div>
              </div>

              {/* Mining Rate Card */}
              <MiningRateCard
                className="flex-1"
                userCumulativeRebate={userCumulativeRebate}
                totalDistributed={totalDistributed}
                hasWelcomeBonus={Boolean(status?.hasWelcomeBonus)}
                welcomeProgress={welcomeProgress}
                userRewardSharePercent={status?.userRewardSharePercent ?? 70}
                todayEstimatedReward={yourEpochReward}
                dailyHistory={
                  status?.dailyHistory ||
                  status?.daily_history ||
                  status?.stats?.dailyHistory ||
                  status?.stats?.daily_history
                }
              />
            </div>

            {/* Referral Program Card */}
            <div className="glass relative rounded-2xl border border-white/10 shadow-xl overflow-hidden p-6 space-y-5 h-full flex flex-col justify-between">
              <div className="absolute -top-16 -right-16 w-36 h-36 rounded-full bg-cyan-500/10 blur-3xl pointer-events-none" />
              <div className="relative">
                <div className="flex items-center gap-2.5 mb-2">
                  <div className="p-2 rounded-xl bg-cyan-500/10 border border-cyan-500/20 text-cyan-400">
                    <UserPlus className="h-5 w-5" />
                  </div>
                  <h3 className="text-base font-bold text-white tracking-wide">
                    {t("referralProgram", "Referral Program")}
                  </h3>
                </div>
                <p className="text-xs text-white/50 mb-5">
                  {t("referralProgramDesc", "Invite friends to run nodes and earn a +10% daily boost plus matching welcome rewards!")}
                </p>

                <div className="space-y-4">
                  {/* Referral Code Copy */}
                  <div className="space-y-1.5">
                    <Label className="text-[11px] font-semibold text-white/50 uppercase tracking-wider">
                      {t("yourReferralCode", "Your Referral Code")}
                    </Label>
                    <div className="flex items-center gap-2 bg-white/[0.03] border border-white/10 rounded-xl p-1.5 pl-4 focus-within:border-cyan-500/50 transition-colors">
                      <span className="font-mono font-bold text-sm tracking-wider flex-1 select-all text-cyan-300">
                        {status?.nodeReferralCode || "Loading..."}
                      </span>
                      <Button
                        variant="ghost"
                        size="icon"
                        className="h-8 w-8 hover:bg-white/10 hover:text-cyan-400 rounded-lg transition-colors"
                        onClick={() => copyToClipboard(status?.nodeReferralCode || "", false)}
                      >
                        {copiedCode ? <Check className="h-4 w-4 text-emerald-400" /> : <Copy className="h-4 w-4 text-white/70" />}
                      </Button>
                    </div>
                  </div>

                  {/* Invite Link Copy */}
                  <div className="space-y-1.5">
                    <Label className="text-[11px] font-semibold text-white/50 uppercase tracking-wider">
                      {t("inviteLink", "Invite Link")}
                    </Label>
                    <div className="flex items-center gap-2 bg-white/[0.03] border border-white/10 rounded-xl p-1.5 pl-4 focus-within:border-cyan-500/50 transition-colors">
                      <span className="font-mono text-xs truncate flex-1 text-white/70">
                        {inviteLink}
                      </span>
                      <Button
                        variant="ghost"
                        size="icon"
                        className="h-8 w-8 hover:bg-white/10 hover:text-cyan-400 rounded-lg transition-colors"
                        onClick={() => copyToClipboard(inviteLink, true)}
                      >
                        {copiedLink ? <Check className="h-4 w-4 text-emerald-400" /> : <Share2 className="h-4 w-4 text-white/70" />}
                      </Button>
                    </div>
                  </div>

                  {/* Node Deploy Command Copy */}
                  {status?.nodeReferralCode && (
                    <div className="space-y-1.5">
                      <Label className="text-[11px] font-semibold text-white/50 uppercase tracking-wider">
                        {t("nodeDeployCommand", "Node One-Line Deploy Command")}
                      </Label>
                      <div className="flex items-center gap-2 bg-white/[0.03] border border-white/10 rounded-xl p-1.5 pl-4 max-w-full overflow-hidden focus-within:border-cyan-500/50 transition-colors">
                        <span className="font-mono text-[11px] truncate min-w-0 flex-1 text-emerald-400 font-medium select-all">
                          {`curl -sL https://raw.githubusercontent.com/DepthSight-Pro/DepthSight/main/deploy.sh | NODE_REFERRER_CODE=${status.nodeReferralCode} sudo bash`}
                        </span>
                        <Button
                          variant="ghost"
                          size="icon"
                          className="h-8 w-8 hover:bg-white/10 hover:text-cyan-400 rounded-lg shrink-0 transition-colors"
                          onClick={() => {
                            const cmd = `curl -sL https://raw.githubusercontent.com/DepthSight-Pro/DepthSight/main/deploy.sh | NODE_REFERRER_CODE=${status.nodeReferralCode} sudo bash`;
                            navigator.clipboard.writeText(cmd);
                            toast({ description: t("commandCopied", "Deploy command copied to clipboard!") });
                          }}
                        >
                          <Copy className="h-4 w-4 text-white/70" />
                        </Button>
                      </div>
                    </div>
                  )}
                </div>
              </div>
            </div>
          </div>

          {/* Staking Boost Card (Future Phase) */}
          <div className="glass relative rounded-2xl border border-white/10 shadow-xl overflow-hidden p-6">
            <div className="absolute top-0 right-0 p-6 opacity-5 pointer-events-none">
              <Lock className="h-28 w-28 text-white" />
            </div>
            <div className="relative space-y-2">
              <div className="flex items-center gap-2.5">
                <div className="p-2 rounded-xl bg-white/[0.05] border border-white/10 text-white/70">
                  <Lock className="h-4 w-4" />
                </div>
                <h3 className="text-base font-bold text-white tracking-wide flex items-center gap-2.5">
                  {t("stakingBoost", "Staking Boost")}
                  <Badge variant="secondary" className="text-[10px] font-mono font-bold uppercase tracking-wider bg-white/[0.06] text-white/70 border-white/10 rounded-md">
                    {t("comingSoon", "Coming Soon")}
                  </Badge>
                </h3>
              </div>
              <p className="text-xs text-white/50">
                {t("stakingBoostDesc", "Lock $DEPTH to multiply your mining earnings.")}
              </p>
              <div className="text-xs text-white/60 pt-2 leading-relaxed max-w-2xl">
                {t("stakingBoostDetail", "Stake $DEPTH for 30, 90 or 360 days to unlock up to 2.0x multiplier on all daily trade mining emission awards.")}
              </div>
            </div>
          </div>
        </>
      )}
      </div>

      <Footer className="mt-auto flex-shrink-0" />

      <NodeWalletModal
        isOpen={isWalletModalOpen}
        onClose={() => setIsWalletModalOpen(false)}
        onWalletActivated={() => handleActivate()}
      />
    </div>
  );
};

export default MiningHub;
