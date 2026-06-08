// src/features/hft-dashboard/components/OracleScanner.tsx

import { Activity, Zap } from "lucide-react";
import type React from "react";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { ScrollArea } from "@/components/ui/scroll-area";
import { useHftStore } from "../hooks/useHftStore";

export const OracleScanner: React.FC = () => {
	const { oracleSymbols } = useHftStore();

	return (
		<Card className="h-full flex flex-col border-border/40 shadow-sm">
			<CardHeader className="py-2 px-3 border-b border-border/40 flex flex-row items-center justify-between space-y-0 shrink-0">
				<CardTitle className="text-xs font-bold uppercase tracking-wider text-muted-foreground flex items-center gap-2">
					<Zap size={14} className="text-amber-500" />
					Amnesia Pipeline
				</CardTitle>
				<div className="flex items-center gap-2 text-[10px] text-muted-foreground/50 uppercase font-bold">
					<span>Active</span>
					<div className="w-1.5 h-1.5 rounded-full bg-emerald-500"></div>
				</div>
			</CardHeader>
			<CardContent className="flex-1 p-0 overflow-hidden">
				<div className="grid grid-cols-5 px-4 py-2 text-xs font-semibold text-muted-foreground border-b border-border/40 uppercase tracking-wider bg-muted/5">
					<div>Asset</div>
					<div>Confidence</div>
					<div>Vol (NATR)</div>
					<div className="text-right">24H Vol</div>
					<div className="text-right">24h Chg</div>
				</div>
				<ScrollArea className="h-full">
					{oracleSymbols.length === 0 ? (
						<div className="flex flex-col items-center justify-center p-8 text-muted-foreground opacity-50 gap-2 h-40">
							<Activity className="w-8 h-8 opacity-20" />
							<span className="text-xs uppercase tracking-widest font-semibold">
								No High Confidence Flags
							</span>
						</div>
					) : (
						<div className="divide-y divide-border/20">
							{oracleSymbols.map((item, idx) => (
								<div
									key={idx}
									className="grid grid-cols-5 px-4 py-2.5 text-sm items-center hover:bg-card/50 transition-colors"
								>
									<div className="font-bold font-mono text-foreground">
										{item.symbol}
									</div>
									<div>
										<Badge
											variant="outline"
											className={`h-5 text-[11px] border-emerald-500/20 text-emerald-500 py-0 px-2`}
										>
											{((item.confidence || 0) * 100).toFixed(0)}%
										</Badge>
									</div>
									<div className="font-mono text-muted-foreground/80">
										{(item.volatility_natr || 0).toFixed(4)}
									</div>
									<div className="text-right font-mono text-muted-foreground">
										{formatCompactNumber(item.volume_24h || 0)}
									</div>
									<div
										className={`text-right font-mono font-bold ${(item.price_change_percent || 0) >= 0 ? "text-emerald-500" : "text-rose-500"}`}
									>
										{(item.price_change_percent || 0) > 0 ? "+" : ""}
										{(item.price_change_percent || 0).toFixed(2)}%
									</div>
								</div>
							))}
						</div>
					)}
				</ScrollArea>
			</CardContent>
		</Card>
	);
};

function formatCompactNumber(number: number) {
	return Intl.NumberFormat("en-US", {
		notation: "compact",
		maximumFractionDigits: 1,
	}).format(number);
}
