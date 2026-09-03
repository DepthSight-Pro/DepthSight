// src/pages/MiningHub.tsx

import React, { useState, useEffect } from "react";
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
  Filter,
  RefreshCw,
  X,
  ChevronLeft,
  ChevronRight,
  ExternalLink,
  AlertCircle,
  Search,
  ArrowUpRight,
  Sparkles,
  Wallet,
  Info,
  KeyRound,
  UserCheck,
  User,
  Award
} from "lucide-react";
import { AppLoader } from "@/components/shared/AppLoader";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { Progress } from "@/components/ui/progress";
import { useToast } from "@/components/ui/use-toast";
import { useGetMiningStatus, useActivateMining, useDeactivateMining, useGetMiningReferrals, useGetMiningTrades } from "@/lib/api";
import { NodeWalletModal } from "@/components/mining/NodeWalletModal";
import { Footer } from "@/components/layout/Footer";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import { 
  Select, 
  SelectContent, 
  SelectItem, 
  SelectTrigger, 
  SelectValue 
} from "@/components/ui/select";


const StatCard = ({
  title,
  value,
  subtitle,
  icon: Icon,
  isLoading
}: {
  title: string;
  value: string | number;
  subtitle?: string;
  icon: React.ElementType;
  isLoading: boolean;
}) => (
  <Card className="relative overflow-hidden border bg-card/60 backdrop-blur-md shadow-lg transition-all hover:shadow-primary/5 hover:border-primary/20">
    <div className="absolute top-0 right-0 p-4 opacity-10">
      <Icon className="h-20 w-20 text-primary" />
    </div>
    <CardHeader className="flex flex-row items-center justify-between pb-2 space-y-0">
      <CardTitle className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
        {title}
      </CardTitle>
      <Icon className="h-4 w-4 text-primary" />
    </CardHeader>
    <CardContent>
      {isLoading ? (
        <Skeleton className="h-8 w-24" />
      ) : (
        <div className="text-2xl font-black tracking-tight">{value}</div>
      )}
      {subtitle && <p className="text-xs text-muted-foreground mt-1">{subtitle}</p>}
    </CardContent>
  </Card>
);

const MiningHub: React.FC = () => {
  const { t } = useTranslation(["mining", "common"]);
  const { toast } = useToast();
  const [referrerCode, setReferrerCode] = useState("");
  const [copiedCode, setCopiedCode] = useState(false);
  const [copiedLink, setCopiedLink] = useState(false);

  const [activeSubTab, setActiveSubTab] = useState<"overview" | "referrals" | "trades">("overview");
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

  const isAlreadyLinked = Boolean(status?.referrerNodeUuid || (status as any)?.referrer_node_uuid);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const urlRef = params.get("ref") || params.get("ref_code") || params.get("referrer_code");
    const localRef = localStorage.getItem("ref_code") || localStorage.getItem("referrer_code") || localStorage.getItem("ref");
    const apiRef = status?.referrerReferralCode || (status as any)?.referrer_referral_code;
    const foundCode = urlRef || localRef || apiRef || "";

    if (foundCode && !referrerCode) {
      setReferrerCode(foundCode);
    }
  }, [status]);

  const [isWalletModalOpen, setIsWalletModalOpen] = useState(false);

  const handleActivate = () => {
    activateMining(
      { referrerCode: referrerCode.trim() || undefined },
      {
        onSuccess: (data) => {
          toast({
            title: t("common:success", "Success"),
            description: t("miningActivated", "Trade mining successfully activated! Your exchange UID has been resolved and linked automatically."),
          });
          refetch();
        },
        onError: (err: any) => {
          const errMsg = err?.message || err?.detail || "";
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
      onError: (err: any) => {
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
      <div className="container max-w-2xl mx-auto py-10 px-4 flex flex-col min-h-full">
        <div className="flex-1">
          <div className="text-center mb-8">
          <div className="inline-flex p-3 rounded-full bg-primary/10 text-primary mb-4 animate-bounce">
            <Coins className="h-10 w-10" />
          </div>
          <h1 className="text-3xl font-black tracking-tight">{t("activationTitle", "Activate Trade Mining")}</h1>
          <p className="text-muted-foreground mt-2">{t("subtitle", "Provide telemetry and earn $DEPTH tokens on every trade")}</p>
        </div>

        <Card className="border bg-card/40 backdrop-blur-lg shadow-xl">
          <CardHeader>
            <CardTitle className="text-lg flex items-center gap-2">
              <ShieldCheck className="h-5 w-5 text-emerald-500" />
              {t("common:privacy", "Privacy & Security")}
            </CardTitle>
            <CardDescription className="text-sm">
              {t("activationDescription", "By activating Trade Mining, you agree to share anonymous trading telemetry (positions, trade sizes, PnL) with the Central Hub to earn $DEPTH rewards. Your private API keys are never shared.")}
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-6">
            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <Label htmlFor="referrer_code" className="text-sm font-semibold">
                  {t("enterReferrerCode", "Enter Referrer Code (Optional)")}
                </Label>
                {(referrerCode || isAlreadyLinked) && (
                  <Badge variant="outline" className="bg-emerald-500/10 text-emerald-500 border-emerald-500/30 text-[11px] flex items-center gap-1 font-semibold">
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
                className="bg-background/50 border-primary/20 focus:border-primary font-mono text-sm"
              />
              {referrerCode && (
                <p className="text-[11px] text-emerald-500 font-medium">
                  ✓ {t("referrerCodeDetected", "Referral code detected from registration link.")}
                </p>
              )}
            </div>

            <div className="flex gap-2 p-3.5 rounded-lg bg-emerald-500/10 border border-emerald-500/20 text-emerald-500 text-xs leading-normal">
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
              className="w-full font-bold bg-gradient-to-r from-primary to-purple-600 hover:from-primary/95 hover:to-purple-600/95 shadow-md shadow-primary/20 py-6 text-base gap-2"
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

            <div className="pt-2 text-center">
              <Button
                variant="ghost"
                size="sm"
                onClick={() => setIsWalletModalOpen(true)}
                className="text-xs text-muted-foreground hover:text-primary gap-1.5"
              >
                <Wallet className="h-3.5 w-3.5" />
                {t("connectEVMWallet", "Connect Web3 EVM Wallet (MetaMask)")}
              </Button>
            </div>
          </CardContent>
        </Card>
        </div>

        <Footer className="mt-8 flex-shrink-0" />

        <NodeWalletModal
          isOpen={isWalletModalOpen}
          onClose={() => setIsWalletModalOpen(false)}
          onWalletActivated={() => handleActivate()}
        />
      </div>
    );
  }

  // Calculate welcome bonus progress
  const statusAny = status as any;
  const stats = status?.stats || statusAny || {};
  const dailyEmission = statusAny?.dailyEmission ?? stats?.daily_emission ?? stats?.dailyEmission ?? 547945;
  const yourEpochReward = statusAny?.yourEpochReward ?? stats?.your_epoch_reward ?? stats?.yourEpochReward ?? 0.0;
  const epochTotalRebates = statusAny?.epochTotalRebates ?? stats?.epoch_total_rebates ?? stats?.epochTotalRebates ?? 0.0;
  const totalDistributed = status?.totalDistributed ?? statusAny?.totalDistributed ?? stats?.totalDistributed ?? stats?.serverTotalMined ?? statusAny?.serverTotalMined ?? 0.0;

  const welcomeProgress = Math.min((epochTotalRebates / 1.0) * 100, 100);
  const inviteLink = `${window.location.origin}/register?ref=${status?.nodeReferralCode || ""}`;

  return (
    <div className="container mx-auto py-8 px-4 space-y-8 flex flex-col min-h-full">
      <div className="flex-1 space-y-8">
      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b pb-6">
        <div>
          <h1 className="text-3xl font-black tracking-tight flex items-center gap-3">
            {t("title", "Trade Mining & Referrals")}
            <Badge variant="outline" className="bg-emerald-500/10 text-emerald-500 border-emerald-500/30 font-bold uppercase tracking-wider text-[10px]">
              {t("connected", "Active")}
            </Badge>
          </h1>
          <p className="text-muted-foreground mt-1">{t("subtitle", "Provide telemetry and earn $DEPTH tokens on every trade")}</p>
        </div>
        <div className="flex items-center gap-2 self-start md:self-auto">
          <Button
            variant="outline"
            size="sm"
            onClick={() => setIsWalletModalOpen(true)}
            className="text-primary border-primary/30 bg-primary/5 hover:bg-primary/10 rounded-full text-xs font-semibold h-9 px-4 gap-1.5"
          >
            <KeyRound className="h-3.5 w-3.5" />
            <span>{t("nodeWallet", "Node Wallet")}</span>
          </Button>
          <Button
            variant="outline"
            size="sm"
            onClick={handleDeactivate}
            disabled={isDeactivating}
            className="text-muted-foreground border-border/50 hover:bg-destructive/10 hover:text-destructive hover:border-destructive/30 rounded-full text-xs font-semibold h-9 px-4"
          >
            {isDeactivating ? (
              <Loader2 className="h-3 w-3 animate-spin mr-2" />
            ) : null}
            {t("disableMining", "Disable Mining")}
          </Button>
          <div className="flex items-center gap-2 bg-muted/30 border border-border/50 px-4 h-9 rounded-full">
            <span className="h-2 w-2 rounded-full bg-emerald-500 animate-pulse" />
            <span className="text-xs text-muted-foreground font-mono">
              {status?.nodeName || "Node"}
            </span>
          </div>
        </div>
      </div>

      {/* Sub-Tabs Navigation */}
      <Tabs
        value={activeSubTab}
        onValueChange={(v) => setActiveSubTab(v as any)}
        className="w-full"
      >
        <div className="flex justify-between items-center border-b border-border/40 pb-2">
          <TabsList className="bg-muted/50 border border-border/20">
            <TabsTrigger
              value="overview"
              className="gap-2 text-xs md:text-sm font-semibold"
            >
              <Flame className="w-3.5 h-3.5" />
              {t("subtabOverview", "Overview & Pools")}
            </TabsTrigger>
            <TabsTrigger
              value="referrals"
              className="gap-2 text-xs md:text-sm font-semibold"
            >
              <Users className="w-3.5 h-3.5" />
              {t("subtabReferrals", "My Referrals Network")}
              {referralsData?.totalInvited !== undefined && (
                <Badge
                  variant="secondary"
                  className="ml-1 text-[10px] bg-primary/10 text-primary border-primary/20"
                >
                  {referralsData.totalInvited}
                </Badge>
              )}
            </TabsTrigger>
            <TabsTrigger
              value="trades"
              className="gap-2 text-xs md:text-sm font-semibold"
            >
              <Activity className="w-3.5 h-3.5" />
              {t("subtabTrades", "Trades & Telemetry")}
              {tradesData?.total !== undefined && (
                <Badge
                  variant="secondary"
                  className="ml-1 text-[10px] bg-primary/10 text-primary border-primary/20"
                >
                  {tradesData.total}
                </Badge>
              )}
            </TabsTrigger>
          </TabsList>
        </div>
      </Tabs>

      {activeSubTab === "referrals" ? (
        <div className="space-y-6">
          {/* Summary Stat Cards */}
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <StatCard
              title={t("totalInvited", "Total Invited Nodes")}
              value={`${referralsData?.totalInvited || 0}`}
              subtitle={t("totalInvitedSubtitle", "Nodes joined using your ref link")}
              icon={Users}
              isLoading={isLoadingReferrals}
            />
            <StatCard
              title={t("activeReferrals", "Active Trading Nodes")}
              value={`${referralsData?.activeReferrals || 0}`}
              subtitle={t("activeReferralsSubtitle", "Nodes active in last 10 mins")}
              icon={Flame}
              isLoading={isLoadingReferrals}
            />
            <StatCard
              title={t("totalReferralVolume", "Referrals Volume")}
              value={`$${referralsData?.totalReferralVolumeUsdt?.toFixed(2) || "0.00"}`}
              subtitle={t("totalReferralVolumeSubtitle", "Total USDT volume generated")}
              icon={Activity}
              isLoading={isLoadingReferrals}
            />
            <StatCard
              title={t("referralBonusEarned", "+10% Referral Earnings")}
              value={`${referralsData?.totalReferralRewardsDepth?.toFixed(2) || "0.00"} $DEPTH`}
              subtitle={t("referralBonusEarnedSubtitle", "Total 10% daily boost rewards")}
              icon={Sparkles}
              isLoading={isLoadingReferrals}
            />
          </div>

          {/* Referral List Table & Search */}
          <Card className="border bg-card/40 backdrop-blur-md shadow-lg p-6 space-y-4">
            <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
              <div>
                <h3 className="text-lg font-bold tracking-tight flex items-center gap-2">
                  <Users className="h-5 w-5 text-primary" />
                  {t("referralListTitle", "Invited Nodes & User Network")}
                </h3>
                <p className="text-xs text-muted-foreground mt-1">
                  {t("referralListDesc", "Track your referrals, trading volumes, and 10% bonus earnings in real-time.")}
                </p>
              </div>
              <div className="relative w-full sm:w-64">
                <Search className="h-4 w-4 absolute left-3 top-3 text-muted-foreground" />
                <Input
                  placeholder={t("searchReferralPlaceholder", "Search by Node ID or Name...")}
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  className="pl-9 bg-background/50 border-primary/20 text-xs"
                />
              </div>
            </div>

            {isLoadingReferrals ? (
              <div className="py-8 text-center text-sm text-muted-foreground">
                <Loader2 className="h-6 w-6 animate-spin mx-auto mb-2 text-primary" />
                {t("loadingReferrals", "Loading referrals network...")}
              </div>
            ) : !referralsData?.referrals || referralsData.referrals.length === 0 ? (
              <div className="py-12 text-center border border-dashed rounded-lg bg-background/20 space-y-3">
                <UserPlus className="h-10 w-10 text-muted-foreground/40 mx-auto" />
                <div className="font-bold text-sm text-muted-foreground">
                  {t("noReferralsYet", "No invited nodes or users yet")}
                </div>
                <p className="text-xs text-muted-foreground/70 max-w-sm mx-auto">
                  {t("noReferralsDesc", "Share your referral link or node deploy command to invite friends and earn 10% of their daily mining rewards forever!")}
                </p>
              </div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-left text-xs">
                  <thead>
                    <tr className="border-b border-border/50 text-muted-foreground uppercase tracking-wider font-semibold">
                      <th className="pb-3 px-2">{t("thNodeUser", "Node / User")}</th>
                      <th className="pb-3 px-2">{t("thStatus", "Status")}</th>
                      <th className="pb-3 px-2">{t("thJoinedDate", "Joined Date")}</th>
                      <th className="pb-3 px-2 text-right">{t("thVolumeUsdt", "Volume (USDT)")}</th>
                      <th className="pb-3 px-2 text-right">{t("thMinedDepth", "Mined ($DEPTH)")}</th>
                      <th className="pb-3 px-2 text-right">{t("thBonusEarned", "Your +10% Bonus")}</th>
                      <th className="pb-3 px-2 text-center">{t("thWelcomeBonus", "Welcome Bonus")}</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-border/30">
                    {referralsData.referrals
                      .filter((ref) =>
                        ref.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
                        ref.id.toLowerCase().includes(searchQuery.toLowerCase())
                      )
                      .map((ref) => (
                        <tr
                          key={ref.id}
                          onClick={() => handleUserClick(ref.id, ref.name)}
                          className="hover:bg-primary/10 transition-colors cursor-pointer group"
                          title="Click to view trades for this referral"
                        >
                          <td className="py-3 px-2 font-mono font-bold text-foreground group-hover:text-primary transition-colors flex items-center gap-1.5">
                            {ref.name}
                            <ArrowUpRight className="h-3 w-3 opacity-0 group-hover:opacity-100 transition-opacity text-primary" />
                          </td>
                          <td className="py-3 px-2">
                            {ref.status === "active" ? (
                              <Badge className="bg-emerald-500/10 text-emerald-500 border-emerald-500/20 text-[10px] font-bold">
                                {t("statusOnline", "Online")}
                              </Badge>
                            ) : (
                              <Badge variant="secondary" className="text-[10px] text-muted-foreground">
                                {t("statusIdle", "Idle")}
                              </Badge>
                            )}
                          </td>
                          <td className="py-3 px-2 text-muted-foreground">
                            {new Date(ref.createdAt).toLocaleDateString()}
                          </td>
                          <td className="py-3 px-2 text-right font-mono font-bold text-foreground">
                            ${ref.tradeVolumeUsdt.toFixed(2)}
                          </td>
                          <td className="py-3 px-2 text-right font-mono font-bold text-amber-500">
                            {ref.totalMinedDepth.toFixed(2)} $DEPTH
                          </td>
                          <td className="py-3 px-2 text-right font-mono font-bold text-emerald-400">
                            +{ref.referralBonusEarned.toFixed(2)} $DEPTH
                          </td>
                          <td className="py-3 px-2 text-center">
                            {ref.hasWelcomeBonus ? (
                              <Badge className="bg-yellow-500/10 text-yellow-500 border-yellow-500/20 text-[9px]">
                                {t("welcomeBonusClaimed", "Claimed")}
                              </Badge>
                            ) : (
                              <span className="text-muted-foreground/60 text-[11px]">Pending</span>
                            )}
                          </td>
                        </tr>
                      ))}
                  </tbody>
                </table>
              </div>
            )}
          </Card>
        </div>
      ) : activeSubTab === "trades" ? (
        <div className="space-y-6">
          <Card className="p-6 bg-card/60 backdrop-blur-sm border-border/50">
            <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-4 mb-6">
              <div>
                <h3 className="text-lg font-bold flex items-center gap-2">
                  <Activity className="h-5 w-5 text-primary" />
                  {t("tradesTitle", "Telemetry Trade Reports History")}
                </h3>
                <p className="text-xs text-muted-foreground mt-0.5">
                  {t("tradesDesc", "Inspect trade reports, exchange verification status, and daily mining rewards.")}
                </p>
              </div>

              {/* Scope Sub-tabs Pills: All / My Trades / Referral Trades */}
              <div className="flex items-center gap-1 p-1 bg-background/50 border border-border/60 rounded-lg w-fit">
                <button
                  onClick={() => {
                    setSelectedScopeFilter("all");
                    setSelectedUserIdFilter(undefined);
                    setSelectedUsernameFilter("");
                    setTradesPage(1);
                  }}
                  className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-semibold transition-all ${
                    selectedScopeFilter === "all" && selectedUserIdFilter === undefined
                      ? "bg-primary text-primary-foreground shadow-sm"
                      : "text-muted-foreground hover:text-foreground hover:bg-background/80"
                  }`}
                >
                  <Activity className="h-3.5 w-3.5" />
                  <span>{t("allTrades", "Все сделки")}</span>
                </button>
                <button
                  onClick={() => {
                    setSelectedScopeFilter("my");
                    setSelectedUserIdFilter(undefined);
                    setSelectedUsernameFilter("");
                    setTradesPage(1);
                  }}
                  className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-semibold transition-all ${
                    selectedScopeFilter === "my"
                      ? "bg-primary text-primary-foreground shadow-sm"
                      : "text-muted-foreground hover:text-foreground hover:bg-background/80"
                  }`}
                >
                  <UserCheck className="h-3.5 w-3.5" />
                  <span>{t("myTrades", "Мои сделки")}</span>
                </button>
                <button
                  onClick={() => {
                    setSelectedScopeFilter("referrals");
                    setSelectedUserIdFilter(undefined);
                    setSelectedUsernameFilter("");
                    setTradesPage(1);
                  }}
                  className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-semibold transition-all ${
                    selectedScopeFilter === "referrals"
                      ? "bg-primary text-primary-foreground shadow-sm"
                      : "text-muted-foreground hover:text-foreground hover:bg-background/80"
                  }`}
                >
                  <Users className="h-3.5 w-3.5" />
                  <span>{t("referralTrades", "Сделки рефералов")}</span>
                </button>
              </div>
            </div>

            {/* Filters Bar: Search, Status, Exchange */}
            <div className="flex flex-wrap items-center justify-between gap-3 mb-6 p-2.5 rounded-lg bg-background/30 border border-border/40">
              <div className="flex flex-wrap items-center gap-2 flex-1">
                {/* Search Input */}
                <div className="relative w-full sm:w-56">
                  <Search className="h-4 w-4 absolute left-3 top-2.5 text-muted-foreground" />
                  <Input
                    placeholder={t("filterUserPlaceholder", "Search symbol or order...")}
                    value={tradesSearch}
                    onChange={(e) => {
                      setTradesSearch(e.target.value);
                      setTradesPage(1);
                    }}
                    className="pl-9 h-9 bg-background/50 border-primary/20 text-xs"
                  />
                </div>

                {/* Status Filter */}
                <div className="flex items-center rounded-md border border-border/50 bg-background/40 p-0.5">
                  {["ALL", "PENDING", "VERIFIED", "REJECTED"].map((st) => (
                    <button
                      key={st}
                      onClick={() => {
                        setSelectedStatusFilter(st);
                        setTradesPage(1);
                      }}
                      className={`px-2.5 py-1 text-xs font-semibold rounded transition-colors ${
                        selectedStatusFilter === st
                          ? "bg-primary text-primary-foreground shadow-sm"
                          : "text-muted-foreground hover:text-foreground"
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
                    <SelectTrigger className="h-9 text-xs font-medium bg-background/50 border-border/60">
                      <SelectValue placeholder={t("allExchanges", "All Exchanges")} />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="all" className="text-xs font-medium">
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
                        <SelectItem key={ex} value={ex} className="text-xs uppercase font-medium">
                          {ex}
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
                className="h-9 px-2.5"
                title="Refresh trades"
              >
                <RefreshCw className={`h-3.5 w-3.5 ${isLoadingTrades ? "animate-spin" : ""}`} />
              </Button>
            </div>

            {/* User Filter Indicator Badge */}
            {selectedUserIdFilter !== undefined && (
              <div className="mb-4 flex items-center gap-2 bg-primary/10 border border-primary/30 rounded-lg px-3 py-1.5 text-xs text-primary font-medium w-fit">
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
                  className="ml-2 hover:bg-primary/20 p-0.5 rounded transition-colors text-primary"
                  title={t("clearUserFilter", "Clear Filter")}
                >
                  <X className="h-3.5 w-3.5" />
                </button>
              </div>
            )}

            {/* Trades Table */}
            {isLoadingTrades ? (
              <div className="py-12 text-center text-sm text-muted-foreground">
                <Loader2 className="h-6 w-6 animate-spin mx-auto mb-2 text-primary" />
                {t("common:loading", "Loading trades...")}
              </div>
            ) : !tradesData?.items || tradesData.items.length === 0 ? (
              <div className="py-12 text-center border border-dashed rounded-lg bg-background/20 space-y-3">
                <Activity className="h-10 w-10 text-muted-foreground/40 mx-auto" />
                <div className="font-bold text-sm text-muted-foreground">
                  {t("noTradesYet", "No telemetry trade reports yet")}
                </div>
                <p className="text-xs text-muted-foreground/70 max-w-sm mx-auto">
                  {t("noTradesDesc", "Trades will automatically appear here as trading bots execute orders.")}
                </p>
              </div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-left text-xs">
                  <thead>
                    <tr className="border-b border-border/50 text-muted-foreground uppercase tracking-wider font-semibold">
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
                  <tbody className="divide-y divide-border/30">
                    {tradesData.items.map((trd) => (
                      <tr key={trd.id} className="hover:bg-background/40 transition-colors">
                        <td className="py-3 px-2 font-mono font-bold text-foreground">
                          <div>
                            {trd.username ? (
                              <span
                                className="text-primary hover:underline cursor-pointer"
                                onClick={() => trd.userId && handleUserClick(trd.userId, trd.username)}
                              >
                                {trd.username}
                              </span>
                            ) : (
                              <span className="text-muted-foreground truncate max-w-[120px] inline-block" title={trd.nodeUuid}>
                                {trd.nodeUuid}
                              </span>
                            )}
                            <div className="mt-0.5">
                              {trd.isOwnTrade ? (
                                <Badge variant="outline" className="text-[10px] px-1.5 py-0 h-4 bg-primary/10 text-primary border-primary/30 font-medium">
                                  {t("ownTradeBadge", "Моя сделка")}
                                </Badge>
                              ) : (
                                <Badge variant="outline" className="text-[10px] px-1.5 py-0 h-4 bg-amber-500/10 text-amber-500 border-amber-500/30 font-medium inline-flex items-center gap-0.5">
                                  <Users className="h-2.5 w-2.5" />
                                  {t("referralTradeBadge", "Реферал")}
                                </Badge>
                              )}
                            </div>
                          </div>
                        </td>
                        <td className="py-3 px-2">
                          <span className="uppercase font-semibold text-foreground">{trd.exchangeId || "EXCHANGE"}</span>
                          <span className="text-muted-foreground text-[10px] block capitalize">{trd.marketType || "futures"}</span>
                        </td>
                        <td className="py-3 px-2 font-mono font-bold text-foreground">
                          {trd.symbol}
                        </td>
                        <td className="py-3 px-2">
                          <Badge
                            className={
                              trd.direction?.toLowerCase() === "buy" || trd.direction?.toLowerCase() === "long"
                                ? "bg-emerald-500/10 text-emerald-500 border-emerald-500/20 text-[10px] uppercase font-bold"
                                : "bg-rose-500/10 text-rose-500 border-rose-500/20 text-[10px] uppercase font-bold"
                            }
                          >
                            {trd.direction || "BUY"}
                          </Badge>
                        </td>
                        <td className="py-3 px-2 text-right font-mono font-bold text-foreground">
                          ${trd.tradeVolumeUsdt.toFixed(2)}
                        </td>
                        <td className="py-3 px-2 text-center">
                          {trd.verificationStatus === "VERIFIED" ? (
                            <Badge className="bg-emerald-500/10 text-emerald-500 border-emerald-500/20 text-[10px] font-bold inline-flex items-center gap-1">
                              <CheckCircle2 className="h-3 w-3" />
                              {t("statusVerified", "Verified")}
                            </Badge>
                          ) : trd.verificationStatus === "REJECTED" ? (
                            <Badge variant="destructive" className="text-[10px] font-bold inline-flex items-center gap-1" title={trd.verificationError || "Verification rejected"}>
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
                            <Badge variant="secondary" className="bg-yellow-500/10 text-yellow-500 border-yellow-500/20 text-[10px]" title={trd.verificationError}>
                              {t("statusPending", "Pending")}
                            </Badge>
                          )}
                        </td>
                        <td className="py-3 px-2 text-right font-mono font-bold text-amber-500">
                          +{trd.rewardTokens.toFixed(2)} $DEPTH
                        </td>
                        <td className="py-3 px-2 text-right text-muted-foreground font-mono text-[11px]">
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
              <div className="mt-6 flex items-center justify-between border-t border-border/40 pt-4 text-xs text-muted-foreground">
                <div>
                  Showing Page <strong className="text-foreground">{tradesData.page}</strong> of{" "}
                  <strong className="text-foreground">{tradesData.totalPages}</strong> (Total: {tradesData.total} trades)
                </div>
                <div className="flex items-center gap-2">
                  <Button
                    variant="outline"
                    size="sm"
                    disabled={tradesPage <= 1}
                    onClick={() => setTradesPage((p) => Math.max(1, p - 1))}
                    className="h-8 text-xs gap-1"
                  >
                    <ChevronLeft className="h-3.5 w-3.5" />
                    {t("pagePrev", "Previous")}
                  </Button>
                  <Button
                    variant="outline"
                    size="sm"
                    disabled={tradesPage >= tradesData.totalPages}
                    onClick={() => setTradesPage((p) => p + 1)}
                    className="h-8 text-xs gap-1"
                  >
                    {t("pageNext", "Next")}
                    <ChevronRight className="h-3.5 w-3.5" />
                  </Button>
                </div>
              </div>
            )}
          </Card>
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
          isLoading={isLoading}
        />
        <StatCard
          title={t("todayEstReward", "Today's Est. Reward")}
          value={`${yourEpochReward >= 1000 ? Math.round(yourEpochReward).toLocaleString("en-US").replace(/,/g, " ") : yourEpochReward.toFixed(2)} $DEPTH`}
          subtitle={t("todayEstRewardSubtitle", "Expected from current daily pool")}
          icon={Flame}
          isLoading={isLoading}
        />
        <StatCard
          title={t("todayRebates", "Today's Rebates")}
          value={`$${epochTotalRebates.toFixed(2)}`}
          subtitle={t("todayRebatesSubtitle", "USDT commission rebates today")}
          icon={Activity}
          isLoading={isLoading}
        />
        <StatCard
          title={t("dailyEmission", "Daily Emission Pool")}
          value={`${dailyEmission.toLocaleString()} $DEPTH`}
          subtitle={t("dailyEmissionSubtitle", "Shared daily emission pool")}
          icon={Sparkles}
          isLoading={isLoading}
        />
        <StatCard
          title={t("totalDistributed", "Total Distributed")}
          value={`${totalDistributed >= 1000 ? Math.round(totalDistributed).toLocaleString("en-US").replace(/,/g, " ") : totalDistributed.toFixed(2)} $DEPTH`}
          subtitle={t("totalDistributedSubtitle", "Distributed across all epochs")}
          icon={Award}
          isLoading={isLoading}
        />
      </div>

      {/* Node Sharing Policy info */}
      {(status?.userRewardSharePercent !== undefined || stats?.userRatio !== undefined) && (
        <Card className="border bg-card/40 backdrop-blur-md shadow-lg p-5">
          <h3 className="text-sm font-bold uppercase tracking-wider text-muted-foreground mb-4">
            {t("nodeSharingPolicy", "Node Sharing Policy")}
          </h3>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <div className="p-3 border rounded-lg bg-background/30">
              <span className="text-xs text-muted-foreground block">{t("nodeSharePercentage", "Node Share Percentage")}</span>
              <span className="text-lg font-black text-primary">{status?.userRewardSharePercent ?? 0}%</span>
            </div>
            {stats?.userRatio !== undefined && (
              <div className="p-3 border rounded-lg bg-background/30">
                <span className="text-xs text-muted-foreground block">{t("yourVolumeShare", "Your Volume Share (Today)")}</span>
                <span className="text-lg font-black">{(stats.userRatio * 100).toFixed(2)}%</span>
              </div>
            )}
            {status?.userTradeVolume !== undefined && (
              <div className="p-3 border rounded-lg bg-background/30">
                <span className="text-xs text-muted-foreground block">{t("yourTotalVolume", "Your Total Volume")}</span>
                <span className="text-lg font-black">{status.userTradeVolume.toFixed(2)} USDT</span>
              </div>
            )}
          </div>
        </Card>
      )}

      {/* Supported Exchanges & Rebate Rates Card */}
      {((stats?.eligibleExchanges || stats?.eligible_exchanges || []).length > 0) && (
        <Card className="border bg-card/40 backdrop-blur-md shadow-lg p-5 space-y-3">
          <div>
            <h3 className="text-sm font-bold uppercase tracking-wider text-muted-foreground flex items-center gap-2">
              <Globe className="h-4 w-4 text-primary" />
              {t("supportedExchanges", "Supported Mining Exchanges & Rebates")}
            </h3>
            <p className="text-xs text-muted-foreground mt-1">
              {t("supportedExchangesDesc", "Trade mining rewards are calculated for live trades executed on the following exchanges:")}
            </p>
          </div>
          <div className="flex flex-wrap gap-2 pt-1">
            {(stats?.eligibleExchanges || stats?.eligible_exchanges || []).map((ex: string) => {
              const rates = stats?.rebateRates || stats?.rebate_rates || {};
              const rate = rates[ex] ?? 0.60;
              const isOkx = ex.toLowerCase().includes("okx");
              const isBybit = ex.toLowerCase().includes("bybit");

              const tooltipText = isOkx
                ? t("rebateRateTooltipOkx", "Base broker rate (30%). When trading under our affiliate link, rebates stack (30% + 7.5% = 37.5%), earning up to 5x more tokens compared to third-party referrals.")
                : isBybit
                ? t("rebateRateTooltipBybit", "Base broker rate (40-50%). Trading under our affiliate link maximizes your effective rebate and token mining yield.")
                : t("rebateRateTooltipDefault", "Base broker rebate rate. Mining rewards are distributed proportionally to verified trading volume and fees.");

              return (
                <TooltipProvider key={ex} delayDuration={150}>
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <div className="flex items-center gap-2 bg-background/50 border border-primary/20 hover:border-primary/50 transition-colors px-3 py-1.5 rounded-lg text-xs cursor-help">
                        <span className="font-mono font-bold uppercase text-foreground">{ex.replace("_", " ")}</span>
                        <Badge variant="secondary" className="bg-primary/10 text-primary border-primary/20 text-[10px] font-mono font-bold flex items-center gap-1">
                          {(rate * 100).toFixed(0)}% Rebate
                          {(isOkx || isBybit) && <Info className="h-3 w-3 text-primary/70" />}
                        </Badge>
                      </div>
                    </TooltipTrigger>
                    <TooltipContent side="top" className="max-w-xs text-xs p-2.5 shadow-xl bg-popover text-popover-foreground border">
                      <p>{tooltipText}</p>
                    </TooltipContent>
                  </Tooltip>
                </TooltipProvider>
              );
            })}
          </div>
        </Card>
      )}

      {/* Interactive Cards */}
      <div className="grid gap-6 md:grid-cols-2">
        {/* Welcome Bonus Card */}
        <Card className="border bg-card/40 backdrop-blur-md shadow-lg">
          <CardHeader>
            <div className="flex items-center justify-between">
              <CardTitle className="text-lg flex items-center gap-2">
                <Coins className="h-5 w-5 text-yellow-500" />
                {t("welcomeBonus", "Welcome Bonus")}
              </CardTitle>
              {status?.hasWelcomeBonus && (
                <Badge className="bg-yellow-500/10 text-yellow-500 border-yellow-500/20 font-bold uppercase tracking-wider text-[10px]">
                  {t("welcomeBonusClaimed", "Claimed")}
                </Badge>
              )}
            </div>
            <CardDescription className="text-sm">
              {t("welcomeBonusDesc", "Generate at least $1.0 of cumulative rebate to claim your welcome bonus.")}
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            {status?.hasWelcomeBonus ? (
              <div className="bg-yellow-500/5 border border-yellow-500/20 rounded-lg p-4 flex items-center gap-3">
                <ShieldCheck className="h-6 w-6 text-yellow-500 shrink-0" />
                <div>
                  <h4 className="font-bold text-sm text-yellow-500">{t("welcomeBonusClaimed", "Welcome Bonus Claimed!")}</h4>
                  <p className="text-xs text-muted-foreground mt-0.5">
                    {t("welcomeBonusClaimedDesc", "1000 $DEPTH has been credited to your node balance.")}
                  </p>
                </div>
              </div>
            ) : (
              <div className="space-y-2">
                <div className="flex justify-between text-xs font-semibold text-muted-foreground">
                  <span>{t("welcomeBonusProgress", { current: epochTotalRebates.toFixed(2), target: "1.00" })}</span>
                  <span>{Math.round(welcomeProgress)}%</span>
                </div>
                <Progress value={welcomeProgress} className="h-2 bg-muted border border-border/50" />
              </div>
            )}
          </CardContent>
        </Card>

        {/* Referral Program Card */}
        <Card className="border bg-card/40 backdrop-blur-md shadow-lg">
          <CardHeader>
            <CardTitle className="text-lg flex items-center gap-2">
              <UserPlus className="h-5 w-5 text-primary" />
              {t("referralProgram", "Referral Program")}
            </CardTitle>
            <CardDescription className="text-sm">
              {t("referralProgramDesc", "Invite friends to run nodes and earn a +10% daily boost plus matching welcome rewards!")}
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-6">
            {/* Referral Code Copy */}
            <div className="grid gap-2">
              <Label className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">
                {t("yourReferralCode", "Your Referral Code")}
              </Label>
              <div className="flex items-center gap-2 bg-background/50 border border-primary/20 rounded-lg p-2 pl-4">
                <span className="font-mono font-bold text-sm tracking-wider flex-1 select-all">
                  {status?.nodeReferralCode || "Loading..."}
                </span>
                <Button
                  variant="ghost"
                  size="icon"
                  className="hover:bg-primary/10 hover:text-primary rounded-md"
                  onClick={() => copyToClipboard(status?.nodeReferralCode || "", false)}
                >
                  {copiedCode ? <Check className="h-4 w-4 text-emerald-500" /> : <Copy className="h-4 w-4" />}
                </Button>
              </div>
            </div>

            {/* Invite Link Copy */}
            <div className="grid gap-2">
              <Label className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">
                {t("inviteLink", "Invite Link")}
              </Label>
              <div className="flex items-center gap-2 bg-background/50 border border-primary/20 rounded-lg p-2 pl-4">
                <span className="font-mono text-xs truncate flex-1 text-muted-foreground">
                  {inviteLink}
                </span>
                <Button
                  variant="ghost"
                  size="icon"
                  className="hover:bg-primary/10 hover:text-primary rounded-md"
                  onClick={() => copyToClipboard(inviteLink, true)}
                >
                  {copiedLink ? <Check className="h-4 w-4 text-emerald-500" /> : <Share2 className="h-4 w-4" />}
                </Button>
              </div>
            </div>

            {/* Node Deploy Command Copy */}
            {status?.nodeReferralCode && (
              <div className="grid gap-2">
                <Label className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">
                  {t("nodeDeployCommand", "Node One-Line Deploy Command")}
                </Label>
                <div className="flex items-center gap-2 bg-background/50 border border-primary/20 rounded-lg p-2 pl-4 max-w-full overflow-hidden">
                  <span className="font-mono text-[11px] truncate min-w-0 flex-1 text-emerald-500 font-semibold select-all">
                    {`curl -sL https://raw.githubusercontent.com/DepthSight-Pro/DepthSight/main/deploy.sh | NODE_REFERRER_CODE=${status.nodeReferralCode} sudo bash`}
                  </span>
                  <Button
                    variant="ghost"
                    size="icon"
                    className="hover:bg-primary/10 hover:text-primary rounded-md shrink-0"
                    onClick={() => {
                      const cmd = `curl -sL https://raw.githubusercontent.com/DepthSight-Pro/DepthSight/main/deploy.sh | NODE_REFERRER_CODE=${status.nodeReferralCode} sudo bash`;
                      navigator.clipboard.writeText(cmd);
                      toast({ description: t("commandCopied", "Deploy command copied to clipboard!") });
                    }}
                  >
                    <Copy className="h-4 w-4" />
                  </Button>
                </div>
              </div>
            )}
          </CardContent>
        </Card>
      </div>

      {/* Staking Boost Card (Future Phase) */}
      <Card className="border bg-card/30 backdrop-blur-sm relative overflow-hidden">
        <div className="absolute top-0 right-0 p-6 opacity-10">
          <Lock className="h-24 w-24 text-primary" />
        </div>
        <CardHeader>
          <CardTitle className="text-lg flex items-center gap-2">
            <Lock className="h-5 w-5 text-primary" />
            {t("stakingBoost", "Staking Boost")}
            <Badge variant="secondary" className="text-[9px] font-bold uppercase tracking-wider bg-primary/10 text-primary border-primary/25">
              {t("comingSoon", "Coming Soon")}
            </Badge>
          </CardTitle>
          <CardDescription className="text-sm">
            {t("stakingBoostDesc", "Lock $DEPTH to multiply your mining earnings.")}
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="text-sm text-muted-foreground">
            {t("stakingBoostDetail", "Stake $DEPTH for 30, 90 or 360 days to unlock up to 2.0x multiplier on all daily trade mining emission awards.")}
          </div>
        </CardContent>
      </Card>
        </>
      )}
      </div>

      <Footer className="mt-8 flex-shrink-0" />

      <NodeWalletModal
        isOpen={isWalletModalOpen}
        onClose={() => setIsWalletModalOpen(false)}
        onWalletActivated={() => handleActivate()}
      />
    </div>
  );
};

export default MiningHub;
