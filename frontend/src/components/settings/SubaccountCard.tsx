// src/components/settings/SubaccountCard.tsx

import {
	Key,
	Loader2,
	RefreshCcw,
	Trash2,
	TrendingDown,
	TrendingUp,
	Wallet,
} from "lucide-react";
import type React from "react";
import { useTranslation } from "react-i18next";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Switch } from "@/components/ui/switch";
import { cn } from "@/lib/utils";
import type { AccountBalance, ApiKey } from "@/types/api";

interface SubaccountCardProps {
	apiKey: ApiKey;
	balance?: AccountBalance;
	isToggling?: boolean;
	isTesting?: boolean;
	onToggleActive: (keyId: number, isActive: boolean) => void;
	onTest: (keyId: number) => void;
	onDelete: (keyId: number) => void;
}

const StatusBadge: React.FC<{ status?: string }> = ({ status }) => {
	const getVariant = () => {
		switch (status) {
			case "valid":
				return "default";
			case "invalid":
				return "destructive";
			case "testing":
				return "secondary";
			default:
				return "outline";
		}
	};

	return (
		<Badge variant={getVariant()} className="text-xs">
			{status || "untested"}
		</Badge>
	);
};

export const SubaccountCard: React.FC<SubaccountCardProps> = ({
	apiKey,
	balance,
	isToggling,
	isTesting,
	onToggleActive,
	onTest,
	onDelete,
}) => {
	const { t } = useTranslation(["settings", "common"]);

	return (
		<Card
			className={cn(
				"transition-all duration-300",
				apiKey.isActive
					? "border-primary/50 shadow-sm"
					: "opacity-60 border-muted",
			)}
		>
			<CardHeader className="flex flex-row items-center justify-between pb-2">
				<div className="flex items-center gap-3">
					<div
						className={cn(
							"p-2 rounded-lg",
							apiKey.isActive ? "bg-primary/10" : "bg-muted",
						)}
					>
						<Key
							className={cn(
								"h-5 w-5",
								apiKey.isActive ? "text-primary" : "text-muted-foreground",
							)}
						/>
					</div>
					<div>
						<CardTitle className="text-lg font-semibold">
							{apiKey.name}
						</CardTitle>
						<p className="text-xs text-muted-foreground font-mono">
							{apiKey.keyPrefix}...
						</p>
					</div>
				</div>
				<div className="flex items-center gap-2">
					{isToggling && (
						<Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
					)}
					<Switch
						checked={apiKey.isActive}
						onCheckedChange={(checked) => onToggleActive(apiKey.id, checked)}
						disabled={isToggling}
						aria-label={
							apiKey.isActive ? "Deactivate account" : "Activate account"
						}
					/>
				</div>
			</CardHeader>

			<CardContent className="space-y-4">
				{/* Balance Section */}
				{apiKey.isActive && balance && (
					<div className="grid grid-cols-2 gap-4 p-3 bg-secondary/30 rounded-lg">
						<div>
							<div className="flex items-center gap-1 text-xs text-muted-foreground mb-1">
								<Wallet className="h-3 w-3" />
								{t("settings:balance")}
							</div>
							<p className="text-lg font-bold">
								$
								{balance.balance.toLocaleString(undefined, {
									minimumFractionDigits: 2,
									maximumFractionDigits: 2,
								})}
							</p>
						</div>
						<div>
							<div className="flex items-center gap-1 text-xs text-muted-foreground mb-1">
								{balance.unrealizedPnl >= 0 ? (
									<TrendingUp className="h-3 w-3 text-green-500" />
								) : (
									<TrendingDown className="h-3 w-3 text-red-500" />
								)}
								{t("settings:unrealizedPnl")}
							</div>
							<p
								className={cn(
									"text-lg font-bold",
									balance.unrealizedPnl >= 0
										? "text-green-500"
										: "text-red-500",
								)}
							>
								{balance.unrealizedPnl >= 0 ? "+" : ""}$
								{balance.unrealizedPnl.toLocaleString(undefined, {
									minimumFractionDigits: 2,
									maximumFractionDigits: 2,
								})}
							</p>
						</div>
					</div>
				)}

				{/* Inactive state message */}
				{!apiKey.isActive && (
					<div className="p-3 bg-muted/50 rounded-lg text-center">
						<p className="text-sm text-muted-foreground">
							{t("settings:accountDeactivatedMessage")}
						</p>
					</div>
				)}

				{/* Actions */}
				<div className="flex justify-between items-center pt-2 border-t">
					<StatusBadge status={apiKey.status} />
					<div className="flex gap-2">
						<Button
							variant="outline"
							size="sm"
							onClick={() => onTest(apiKey.id)}
							disabled={isTesting}
						>
							{isTesting ? (
								<Loader2 className="h-4 w-4 mr-1 animate-spin" />
							) : (
								<RefreshCcw className="h-4 w-4 mr-1" />
							)}
							{t("settings:testKey")}
						</Button>
						<Button
							variant="ghost"
							size="icon"
							className="text-destructive hover:text-destructive hover:bg-destructive/10"
							onClick={() => onDelete(apiKey.id)}
						>
							<Trash2 className="h-4 w-4" />
						</Button>
					</div>
				</div>
			</CardContent>
		</Card>
	);
};

export default SubaccountCard;
