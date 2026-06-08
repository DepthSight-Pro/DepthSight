// src/components/admin/analytics/FoundationStatsTable.tsx
import React from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import {
	Table,
	TableBody,
	TableCell,
	TableHead,
	TableHeader,
	TableRow,
} from "@/components/ui/table";
import type { FoundationStat } from "@/types/api";

interface Props {
	data: FoundationStat[];
	isLoading: boolean;
	title?: string;
}

const FoundationStatsTable: React.FC<Props> = ({
	data,
	isLoading,
	title = "Foundation Effectiveness",
}) => {
	// Debug logging
	React.useEffect(() => {
		console.log(`FoundationStatsTable [${title}]:`, {
			data,
			isLoading,
			dataLength: data?.length,
		});
	}, [data, isLoading, title]);

	return (
		<Card>
			<CardHeader>
				<CardTitle>{title}</CardTitle>
			</CardHeader>
			<CardContent>
				<Table>
					<TableHeader>
						<TableRow>
							<TableHead>Foundation ID</TableHead>
							<TableHead>Count</TableHead>
							<TableHead>Avg. Win Rate Contr.</TableHead>
							<TableHead>Profit Factor</TableHead>
						</TableRow>
					</TableHeader>
					<TableBody>
						{isLoading ? (
							[...Array(5)].map((_, i) => (
								<TableRow key={i}>
									<TableCell>
										<Skeleton className="h-4 w-24" />
									</TableCell>
									<TableCell>
										<Skeleton className="h-4 w-12" />
									</TableCell>
									<TableCell>
										<Skeleton className="h-4 w-20" />
									</TableCell>
									<TableCell>
										<Skeleton className="h-4 w-16" />
									</TableCell>
								</TableRow>
							))
						) : data && data.length > 0 ? (
							data.map((stat) => (
								<TableRow key={stat.foundationId}>
									<TableCell className="font-medium">
										{stat.foundationId || "(unknown)"}
									</TableCell>
									<TableCell>{stat.count}</TableCell>
									<TableCell>
										{stat.avgWinRateContribution?.toFixed(2) ?? "N/A"}
									</TableCell>
									<TableCell>
										{stat.profitFactor?.toFixed(2) ?? "N/A"}
									</TableCell>
								</TableRow>
							))
						) : (
							<TableRow>
								<TableCell
									colSpan={4}
									className="h-24 text-center text-muted-foreground"
								>
									No foundation analytics data available.
								</TableCell>
							</TableRow>
						)}
					</TableBody>
				</Table>
			</CardContent>
		</Card>
	);
};

export default FoundationStatsTable;
