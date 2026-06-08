// src/components/layout/AccountSelector.tsx

import { Key, Layers, Wallet } from "lucide-react";
import type React from "react";
import { useTranslation } from "react-i18next";
import {
	Select,
	SelectContent,
	SelectItem,
	SelectSeparator,
	SelectTrigger,
	SelectValue,
} from "@/components/ui/select";
import { cn } from "@/lib/utils";
import type { AccountBalance, ApiKey } from "@/types/api";

interface AccountSelectorProps {
	accounts: ApiKey[];
	balances?: Record<number, AccountBalance>;
	selectedAccountId: number | "all";
	onSelect: (accountId: number | "all") => void;
	className?: string;
	showBalances?: boolean;
}

export const AccountSelector: React.FC<AccountSelectorProps> = ({
	accounts,
	balances,
	selectedAccountId,
	onSelect,
	className,
	showBalances = true,
}) => {
	const { t } = useTranslation(["common"]);

	const getSelectedLabel = () => {
		if (selectedAccountId === "all") {
			return t("common:allAccounts");
		}
		const account = accounts.find((a) => a.id === selectedAccountId);
		return account?.name || t("common:selectAccount");
	};

	return (
		<Select
			value={String(selectedAccountId)}
			onValueChange={(v) => onSelect(v === "all" ? "all" : parseInt(v, 10))}
		>
			<SelectTrigger className={cn("w-[200px]", className)}>
				<div className="flex items-center gap-2">
					<Wallet className="h-4 w-4 text-muted-foreground" />
					<SelectValue>{getSelectedLabel()}</SelectValue>
				</div>
			</SelectTrigger>
			<SelectContent>
				<SelectItem value="all">
					<div className="flex items-center gap-2">
						<Layers className="h-4 w-4 text-primary" />
						<span className="font-medium">{t("common:allAccounts")}</span>
					</div>
				</SelectItem>
				<SelectSeparator />
				{accounts.map((acc) => {
					const balance = balances?.[acc.id];
					return (
						<SelectItem key={acc.id} value={String(acc.id)}>
							<div className="flex items-center justify-between w-full gap-4">
								<div className="flex items-center gap-2">
									<Key className="h-4 w-4 text-muted-foreground" />
									<span>{acc.name}</span>
								</div>
								{showBalances && balance && (
									<span className="text-xs text-muted-foreground ml-2">
										$
										{(balance.totalEquity ?? balance.balance).toLocaleString(
											undefined,
											{ minimumFractionDigits: 0, maximumFractionDigits: 0 },
										)}
									</span>
								)}
							</div>
						</SelectItem>
					);
				})}
			</SelectContent>
		</Select>
	);
};

export default AccountSelector;
