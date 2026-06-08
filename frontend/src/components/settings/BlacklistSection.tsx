// src/components/settings/BlacklistSection.tsx

import { formatDistanceToNow } from "date-fns";
import {
	Ban,
	Clock,
	Infinity as InfinityIcon,
	Loader2,
	Plus,
	Trash2,
	Zap,
} from "lucide-react";
import type React from "react";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Badge } from "@/components/ui/badge";
// UI Components
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
	Select,
	SelectContent,
	SelectItem,
	SelectTrigger,
	SelectValue,
} from "@/components/ui/select";
import { Separator } from "@/components/ui/separator";
import { Switch } from "@/components/ui/switch";

// API Hooks
import {
	useAddToBlacklist,
	useBlacklist,
	useRemoveFromBlacklist,
	useUpdateBlacklistRules,
} from "@/lib/api";
import type {
	AutoBlacklistDuration,
	AutoBlacklistRule,
	AutoBlacklistWithinPeriod,
	BlacklistedCoin,
} from "@/types/api";

export const BlacklistSection: React.FC = () => {
	const { t } = useTranslation(["settings"]);
	const { data: blacklist, isLoading } = useBlacklist();
	const { mutate: addToBlacklist, isPending: isAdding } = useAddToBlacklist();
	const { mutate: removeFromBlacklist, isPending: isRemoving } =
		useRemoveFromBlacklist();
	const { mutate: updateRules, isPending: isUpdatingRules } =
		useUpdateBlacklistRules();

	const [newSymbol, setNewSymbol] = useState("");
	const [duration, setDuration] = useState<
		"5m" | "15m" | "end_of_day" | "permanent" | "custom"
	>("permanent");
	const [reason, setReason] = useState("");
	const [removingSymbol, setRemovingSymbol] = useState<string | null>(null);

	// Auto-rules state
	const [newRuleStops, setNewRuleStops] = useState<number>(3);
	const [newRuleWithinPeriod, setNewRuleWithinPeriod] =
		useState<AutoBlacklistWithinPeriod>(null);
	const [newRuleDuration, setNewRuleDuration] =
		useState<AutoBlacklistDuration>("end_of_day");

	const handleAddToBlacklist = () => {
		const symbol = newSymbol.toUpperCase().trim();
		if (!symbol) return;

		let payloadDuration: "end_of_day" | "permanent" | "custom";
		let payloadUntil: string | undefined;

		if (duration === "5m") {
			payloadDuration = "custom";
			const d = new Date();
			d.setMinutes(d.getMinutes() + 5);
			payloadUntil = d.toISOString();
		} else if (duration === "15m") {
			payloadDuration = "custom";
			const d = new Date();
			d.setMinutes(d.getMinutes() + 15);
			payloadUntil = d.toISOString();
		} else {
			// "custom" logic not fully implemented in UI but passed through if selected directly
			// For now mapping direct values
			payloadDuration = duration as "end_of_day" | "permanent" | "custom";
		}

		addToBlacklist(
			{
				symbol,
				duration: payloadDuration,
				customUntil: payloadUntil,
				reason: reason.trim() || undefined,
			},
			{
				onSuccess: () => {
					setNewSymbol("");
					setReason("");
					setDuration("permanent");
				},
			},
		);
	};

	const handleRemoveFromBlacklist = (symbol: string) => {
		setRemovingSymbol(symbol);
		removeFromBlacklist(symbol, {
			onSettled: () => setRemovingSymbol(null),
		});
	};

	const handleAddRule = () => {
		const currentRules = blacklist?.autoRules || [];
		const newRule: AutoBlacklistRule = {
			id: crypto.randomUUID(),
			enabled: true,
			consecutiveStops: newRuleStops,
			withinPeriod: newRuleWithinPeriod,
			duration: newRuleDuration,
		};
		updateRules([...currentRules, newRule]);
		setNewRuleStops(3);
		setNewRuleWithinPeriod(null);
		setNewRuleDuration("end_of_day");
	};

	const handleToggleRule = (ruleId: string) => {
		const currentRules = blacklist?.autoRules || [];
		const updatedRules = currentRules.map((rule) =>
			rule.id === ruleId ? { ...rule, enabled: !rule.enabled } : rule,
		);
		updateRules(updatedRules);
	};

	const handleDeleteRule = (ruleId: string) => {
		const currentRules = blacklist?.autoRules || [];
		const updatedRules = currentRules.filter((rule) => rule.id !== ruleId);
		updateRules(updatedRules);
	};

	const getDurationLabel = (duration: AutoBlacklistDuration): string => {
		const labels: Record<AutoBlacklistDuration, string> = {
			"1h": t("risk.blacklist.autoRules.durations.1h"),
			"4h": t("risk.blacklist.autoRules.durations.4h"),
			"8h": t("risk.blacklist.autoRules.durations.8h"),
			end_of_day: t("risk.blacklist.autoRules.durations.end_of_day"),
			permanent: t("risk.blacklist.autoRules.durations.permanent"),
		};
		return labels[duration] || duration;
	};

	const getWithinPeriodLabel = (period: AutoBlacklistWithinPeriod): string => {
		if (!period) return t("risk.blacklist.autoRules.withinPeriods.any");
		const labels: Record<string, string> = {
			"15m": t("risk.blacklist.autoRules.withinPeriods.15m"),
			"30m": t("risk.blacklist.autoRules.withinPeriods.30m"),
			"1h": t("risk.blacklist.autoRules.withinPeriods.1h"),
			"2h": t("risk.blacklist.autoRules.withinPeriods.2h"),
			"4h": t("risk.blacklist.autoRules.withinPeriods.4h"),
			"8h": t("risk.blacklist.autoRules.withinPeriods.8h"),
			"24h": t("risk.blacklist.autoRules.withinPeriods.24h"),
		};
		return labels[period] || period;
	};

	const getExpirationText = (coin: BlacklistedCoin): React.ReactNode => {
		if (!coin.until) {
			return (
				<Badge variant="secondary" className="gap-1">
					<InfinityIcon className="w-3 h-3" />
					{t("risk.blacklist.permanentLabel")}
				</Badge>
			);
		}

		const untilDate = new Date(coin.until);
		const now = new Date();

		if (untilDate <= now) {
			return <Badge variant="outline">{t("risk.blacklist.expired")}</Badge>;
		}

		return (
			<Badge variant="outline" className="gap-1">
				<Clock className="w-3 h-3" />
				{t("risk.blacklist.expiresIn", {
					time: formatDistanceToNow(untilDate, { addSuffix: false }),
				})}
			</Badge>
		);
	};

	if (isLoading) {
		return (
			<div className="flex items-center justify-center p-8">
				<Loader2 className="w-6 h-6 animate-spin" />
			</div>
		);
	}

	const coins = blacklist?.coins || [];
	const autoRules = blacklist?.autoRules || [];

	return (
		<div className="space-y-6">
			<div>
				<h3 className="text-lg font-semibold flex items-center gap-2">
					<Ban className="w-5 h-5" />
					{t("risk.blacklist.title")}
				</h3>
				<p className="text-sm text-muted-foreground mt-1">
					{t("risk.blacklist.description")}
				</p>
			</div>

			{/* Auto-Rules Section */}
			<div className="grid gap-4 p-4 border rounded-lg bg-card border-primary/20">
				<div className="flex items-center gap-2">
					<Zap className="w-4 h-4 text-primary" />
					<h4 className="font-medium">{t("risk.blacklist.autoRules.title")}</h4>
				</div>
				<p className="text-sm text-muted-foreground">
					{t("risk.blacklist.autoRules.description")}
				</p>

				{/* Add Rule Form */}
				<div className="flex flex-wrap items-end gap-3">
					<div className="space-y-2">
						<Label>{t("risk.blacklist.autoRules.consecutiveStops")}</Label>
						<Input
							type="number"
							min={1}
							max={20}
							value={newRuleStops}
							onChange={(e) =>
								setNewRuleStops(Math.max(1, parseInt(e.target.value, 10) || 1))
							}
							className="w-20"
						/>
					</div>
					<div className="space-y-2">
						<Label>{t("risk.blacklist.autoRules.withinPeriod")}</Label>
						<Select
							value={newRuleWithinPeriod || "any"}
							onValueChange={(v) =>
								setNewRuleWithinPeriod(
									v === "any" ? null : (v as AutoBlacklistWithinPeriod),
								)
							}
						>
							<SelectTrigger className="w-32">
								<SelectValue />
							</SelectTrigger>
							<SelectContent>
								<SelectItem value="any">
									{t("risk.blacklist.autoRules.withinPeriods.any")}
								</SelectItem>
								<SelectItem value="15m">
									{t("risk.blacklist.autoRules.withinPeriods.15m")}
								</SelectItem>
								<SelectItem value="30m">
									{t("risk.blacklist.autoRules.withinPeriods.30m")}
								</SelectItem>
								<SelectItem value="1h">
									{t("risk.blacklist.autoRules.withinPeriods.1h")}
								</SelectItem>
								<SelectItem value="2h">
									{t("risk.blacklist.autoRules.withinPeriods.2h")}
								</SelectItem>
								<SelectItem value="4h">
									{t("risk.blacklist.autoRules.withinPeriods.4h")}
								</SelectItem>
								<SelectItem value="8h">
									{t("risk.blacklist.autoRules.withinPeriods.8h")}
								</SelectItem>
								<SelectItem value="24h">
									{t("risk.blacklist.autoRules.withinPeriods.24h")}
								</SelectItem>
							</SelectContent>
						</Select>
					</div>
					<div className="space-y-2">
						<Label>{t("risk.blacklist.autoRules.duration")}</Label>
						<Select
							value={newRuleDuration}
							onValueChange={(v) =>
								setNewRuleDuration(v as AutoBlacklistDuration)
							}
						>
							<SelectTrigger className="w-40">
								<SelectValue />
							</SelectTrigger>
							<SelectContent>
								<SelectItem value="1h">
									{t("risk.blacklist.autoRules.durations.1h")}
								</SelectItem>
								<SelectItem value="4h">
									{t("risk.blacklist.autoRules.durations.4h")}
								</SelectItem>
								<SelectItem value="8h">
									{t("risk.blacklist.autoRules.durations.8h")}
								</SelectItem>
								<SelectItem value="end_of_day">
									{t("risk.blacklist.autoRules.durations.end_of_day")}
								</SelectItem>
								<SelectItem value="permanent">
									{t("risk.blacklist.autoRules.durations.permanent")}
								</SelectItem>
							</SelectContent>
						</Select>
					</div>
					<Button onClick={handleAddRule} disabled={isUpdatingRules} size="sm">
						{isUpdatingRules ? (
							<Loader2 className="w-4 h-4 mr-2 animate-spin" />
						) : (
							<Plus className="w-4 h-4 mr-2" />
						)}
						{t("risk.blacklist.autoRules.addRule")}
					</Button>
				</div>

				{/* Rules List */}
				{autoRules.length === 0 ? (
					<p className="text-sm text-muted-foreground text-center py-4">
						{t("risk.blacklist.autoRules.noRules")}
					</p>
				) : (
					<div className="space-y-2">
						{autoRules.map((rule) => (
							<div
								key={rule.id}
								className={`flex items-center justify-between p-3 border rounded-lg transition-colors ${
									rule.enabled ? "bg-card" : "bg-muted/50 opacity-60"
								}`}
							>
								<div className="flex items-center gap-4">
									<Switch
										checked={rule.enabled}
										onCheckedChange={() => handleToggleRule(rule.id)}
										disabled={isUpdatingRules}
									/>
									<span className="text-sm">
										<strong>{rule.consecutiveStops}</strong>{" "}
										{t(
											"risk.blacklist.autoRules.consecutiveStops",
										).toLowerCase()}{" "}
										<span className="text-muted-foreground">
											{t("risk.blacklist.autoRules.withinLabel")}
										</span>{" "}
										<Badge variant="secondary" className="text-xs">
											{getWithinPeriodLabel(rule.withinPeriod || null)}
										</Badge>
									</span>
									<span className="text-muted-foreground">→</span>
									<Badge variant="outline">
										{getDurationLabel(rule.duration)}
									</Badge>
								</div>
								<Button
									variant="ghost"
									size="icon"
									className="text-destructive hover:text-destructive hover:bg-destructive/10"
									onClick={() => handleDeleteRule(rule.id)}
									disabled={isUpdatingRules}
								>
									<Trash2 className="w-4 h-4" />
								</Button>
							</div>
						))}
					</div>
				)}
			</div>

			<Separator />

			{/* Manual Add Form */}
			<div className="grid gap-4 p-4 border rounded-lg bg-card">
				<h4 className="font-medium">{t("risk.blacklist.addFormTitle")}</h4>
				<div className="grid sm:grid-cols-3 gap-4">
					<div className="space-y-2">
						<Label htmlFor="blacklist-symbol">
							{t("risk.blacklist.symbolLabel")}
						</Label>
						<Input
							id="blacklist-symbol"
							placeholder={t("risk.blacklist.symbolPlaceholder")}
							value={newSymbol}
							onChange={(e) => setNewSymbol(e.target.value.toUpperCase())}
							onKeyDown={(e) => e.key === "Enter" && handleAddToBlacklist()}
						/>
					</div>
					<div className="space-y-2">
						<Label htmlFor="blacklist-duration">
							{t("risk.blacklist.durationLabel")}
						</Label>
						<Select
							value={duration}
							onValueChange={(v) => setDuration(v as typeof duration)}
						>
							<SelectTrigger>
								<SelectValue />
							</SelectTrigger>
							<SelectContent>
								<SelectItem value="5m">{t("risk.blacklist.5m")}</SelectItem>
								<SelectItem value="15m">{t("risk.blacklist.15m")}</SelectItem>
								<SelectItem value="end_of_day">
									{t("risk.blacklist.untilEndOfDay")}
								</SelectItem>
								<SelectItem value="permanent">
									{t("risk.blacklist.permanent")}
								</SelectItem>
							</SelectContent>
						</Select>
					</div>
					<div className="space-y-2">
						<Label htmlFor="blacklist-reason">
							{t("risk.blacklist.reasonLabel")}
						</Label>
						<Input
							id="blacklist-reason"
							placeholder={t("risk.blacklist.reasonPlaceholder")}
							value={reason}
							onChange={(e) => setReason(e.target.value)}
						/>
					</div>
				</div>
				<div>
					<Button
						onClick={handleAddToBlacklist}
						disabled={!newSymbol.trim() || isAdding}
					>
						{isAdding ? (
							<Loader2 className="w-4 h-4 mr-2 animate-spin" />
						) : (
							<Plus className="w-4 h-4 mr-2" />
						)}
						{t("risk.blacklist.addButton")}
					</Button>
				</div>
			</div>

			<Separator />

			{/* Current Blacklist */}
			<div className="space-y-3">
				{coins.length === 0 ? (
					<div className="text-center py-8 text-muted-foreground">
						<Ban className="w-8 h-8 mx-auto mb-2 opacity-50" />
						<p>{t("risk.blacklist.noCoins")}</p>
					</div>
				) : (
					<div className="space-y-2">
						{coins.map((coin) => (
							<div
								key={coin.symbol}
								className="flex items-center justify-between p-3 border rounded-lg bg-card hover:bg-accent/50 transition-colors"
							>
								<div className="flex items-center gap-4">
									<span className="font-mono font-semibold">{coin.symbol}</span>
									{getExpirationText(coin)}
									{coin.reason && (
										<span className="text-sm text-muted-foreground italic">
											"{coin.reason}"
										</span>
									)}
								</div>
								<Button
									variant="ghost"
									size="sm"
									className="text-destructive hover:text-destructive hover:bg-destructive/10"
									onClick={() => handleRemoveFromBlacklist(coin.symbol)}
									disabled={isRemoving && removingSymbol === coin.symbol}
								>
									{isRemoving && removingSymbol === coin.symbol ? (
										<Loader2 className="w-4 h-4 animate-spin" />
									) : (
										<Trash2 className="w-4 h-4" />
									)}
									<span className="ml-1 hidden sm:inline">
										{t("risk.blacklist.remove")}
									</span>
								</Button>
							</div>
						))}
					</div>
				)}
			</div>
		</div>
	);
};
