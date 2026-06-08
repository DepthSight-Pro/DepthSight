// src/pages/Positions.tsx

import {
	AlertTriangle,
	Briefcase,
	LineChart,
	Loader2,
	Pencil,
	PlusCircle,
	Siren,
} from "lucide-react";
import type React from "react";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

// --- UI & Layout Components ---
import { PageLayout } from "@/components/layout/PageLayout";
import { EditSlTpModal } from "@/components/positions/EditSlTpModal";
import { PositionChartModal } from "@/components/positions/PositionChartModal";
import { ConfirmationModal } from "@/components/shared/ConfirmationModal";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
	Card,
	CardContent,
	CardDescription,
	CardHeader,
	CardTitle,
} from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import {
	Table,
	TableBody,
	TableCell,
	TableHead,
	TableHeader,
	TableRow,
} from "@/components/ui/table";
import { useAuth } from "@/context/AuthContext";
import { usePortfolioMode } from "@/context/PortfolioModeContext";
import { useApiErrorHandler } from "@/hooks/useApiErrorHandler";
// --- API & Types ---
import {
	useClosePosition,
	useEmergencyStop,
	usePositions,
	useUpdatePositionSlTp,
} from "@/lib/api";
import { useAccountStore } from "@/stores/accountStore";
import type { PositionData } from "@/types/api";

// --- Sub-components ---
const StatCard = ({
	label,
	value,
	prefix = "",
	suffix = "",
	isLoading = false,
	pnlValue,
}: {
	label: string;
	value: string | number;
	isLoading: boolean;
	prefix?: string;
	suffix?: string;
	pnlValue?: number;
}) => {
	const pnlColorClass =
		pnlValue !== undefined
			? pnlValue >= 0
				? "text-profit"
				: "text-loss"
			: "text-foreground";
	return (
		<Card>
			<CardHeader className="pb-2">
				<CardTitle className="text-sm font-normal text-muted-foreground">
					{label}
				</CardTitle>
			</CardHeader>
			<CardContent>
				{isLoading ? (
					<Skeleton className="h-7 w-24" />
				) : (
					<div className={`text-2xl font-bold mono ${pnlColorClass}`}>
						{prefix}
						{value}
						{suffix}
					</div>
				)}
			</CardContent>
		</Card>
	);
};

// --- Main Page Component ---
export default function Positions() {
	const { t } = useTranslation(["positions", "common"]);
	const { mode } = usePortfolioMode();
	const { user } = useAuth();
	const isPaperMode = mode === "paper";
	const isAdmin = user?.role === "admin";

	// Global account filter
	const { selectedApiKeyId, selectedMarketType } = useAccountStore();

	const [showConfirm, setShowConfirm] = useState(false);
	const [editingPosition, setEditingPosition] = useState<PositionData | null>(
		null,
	);
	const [viewingPositionId, setViewingPositionId] = useState<string | null>(
		null,
	);
	const [closingSymbol, setClosingSymbol] = useState<string | null>(null);

	// Local state for fake positions (only for testing)
	const [testPositions, setTestPositions] = useState<PositionData[]>([]);

	// --- Data Fetching & Mutations ---
	// Pass apiKeyId only in live mode (paper mode doesn't have multiple accounts)
	const {
		data: serverPositions = [],
		isLoading,
		isError,
		error,
	} = usePositions({
		refetchInterval: 5000,
		mode,
		apiKeyId: mode === "live" ? selectedApiKeyId : undefined,
		marketType: mode === "live" ? selectedMarketType : undefined,
	});

	// Merge server and test positions
	const positions = useMemo(() => {
		return [...testPositions, ...serverPositions];
	}, [serverPositions, testPositions]);
	useApiErrorHandler(error, "Positions");

	// Derived state for viewing position to ensure it's always up to date
	const viewingPosition = useMemo(() => {
		if (!viewingPositionId) return null;
		return positions.find((p) => p.id === viewingPositionId) || null;
	}, [positions, viewingPositionId]);

	const { mutate: emergencyStop, isPending: isStoppingAll } =
		useEmergencyStop();
	const { mutate: updateSlTp, isPending: isUpdatingSlTp } =
		useUpdatePositionSlTp();

	const { mutate: closePosition } = useClosePosition();

	// --- Memoized Calculations ---
	const summary = useMemo(() => {
		if (!positions || positions.length === 0)
			return {
				openPositions: 0,
				unrealizedPnL: 0,
				totalExposure: 0,
				marginUsed: 0,
			};
		const pnl = positions.reduce((acc, pos) => acc + pos.pnl, 0);
		const totalExposure = positions.reduce((acc, pos) => {
			const size = Number(pos.size) || 0;
			const price = Number(pos.mark_price || pos.entry_price) || 0;
			return acc + Math.abs(size * price);
		}, 0);
		return {
			openPositions: positions.length,
			unrealizedPnL: pnl,
			totalExposure,
			marginUsed: totalExposure,
		};
	}, [positions]);

	// --- Handlers ---
	const handleEmergencyStopConfirm = () => {
		emergencyStop(undefined, {
			onSettled: () => setShowConfirm(false),
		});
	};

	const handleEditSlTpSubmit = (data: {
		stop_loss?: number | null;
		take_profit?: number | null;
	}) => {
		if (editingPosition) {
			// If it's a test position, just update local state
			if (editingPosition.id.startsWith("test-")) {
				setTestPositions((prev) =>
					prev.map((p) =>
						p.id === editingPosition.id
							? {
									...p,
									stop_loss: data.stop_loss || 0,
									take_profit: data.take_profit || 0,
								}
							: p,
					),
				);
				setEditingPosition(null);
				return;
			}

			updateSlTp(
				{
					positionId: editingPosition.id,
					stop_loss: data.stop_loss,
					take_profit: data.take_profit,
				},
				{
					onSuccess: () => setEditingPosition(null),
				},
			);
		}
	};

	const handleChartSave = (data: {
		stop_loss: number | null;
		take_profit: number | null;
	}) => {
		if (!viewingPositionId) return;

		const id = viewingPositionId;

		// Test Position Logic
		if (id.startsWith("test-")) {
			setTestPositions((prev) =>
				prev.map((p) =>
					p.id === id
						? {
								...p,
								stop_loss: data.stop_loss || 0,
								take_profit: data.take_profit || 0,
							}
						: p,
				),
			);
			return;
		}

		// Real Position Logic
		updateSlTp(
			{
				positionId: id,
				stop_loss: data.stop_loss,
				take_profit: data.take_profit,
			},
			{
				// No need to manually update viewingPosition state as it is derived from 'positions' which will update on next fetch
				// However, to make it instant for UI, we might depend on optimistic updates from React Query if configured,
				// or just wait for the refetch. For now, let's trigger a refetch or rely on the interval.
			},
		);
	};

	const handleClosePosition = (
		symbol: string,
		e: React.MouseEvent,
		id?: string,
	) => {
		e.stopPropagation();

		// Test position logic
		if (id?.startsWith("test-")) {
			setTestPositions((prev) => prev.filter((p) => p.id !== id));
			return;
		}

		// Use `t` for confirmation text localization
		const confirmationText = t("confirmClosePosition", {
			symbol: symbol,
			ns: "positions",
		});
		const isConfirmed = window.confirm(confirmationText);

		if (isConfirmed) {
			// 1. Set the "loading" state for a specific button
			setClosingSymbol(symbol);
			// 2. Call the mutation, passing callbacks here
			closePosition(symbol, {
				onSettled: () => {
					// 3. Reset the "loading" state after the request is completed
					setClosingSymbol(null);
				},
			});
		}
	};

	const handleAddTestPosition = () => {
		const newPos: PositionData = {
			id: `test-${Date.now()}`,
			symbol: "BTCUSDT",
			direction: "LONG",
			size: 0.5,
			entry_price: 88000,
			mark_price: 87689,
			pnl: 750,
			pnl_percent: 1.58,
			stop_loss: 86000,
			take_profit: 90000,
			strategy: "Test Strategy",
			entry_time: new Date().toISOString(),
		};
		setTestPositions((prev) => [...prev, newPos]);
	};

	const headerActions = (
		<div className="flex items-center gap-2">
			{isAdmin && isPaperMode && (
				<Button
					variant="outline"
					size="sm"
					onClick={handleAddTestPosition}
					className="border-dashed"
				>
					<PlusCircle className="w-4 h-4 mr-2" />
					Test Pos
				</Button>
			)}
			<Button
				variant="destructive"
				size="sm"
				onClick={() => setShowConfirm(true)}
				disabled={isStoppingAll || !!closingSymbol || isPaperMode}
			>
				{isStoppingAll ? (
					<Loader2 className="w-4 h-4 mr-2 animate-spin" />
				) : (
					<Siren className="w-4 h-4 mr-2" />
				)}
				{isStoppingAll ? t("emergencyButtonLoading") : t("emergencyButton")}
			</Button>
		</div>
	);

	return (
		<PageLayout
			title={t("pageTitle")}
			icon={Briefcase}
			headerActions={headerActions}
		>
			<div className="grid grid-cols-2 lg:grid-cols-4 gap-6 mb-6">
				<StatCard
					label={t("openPositions")}
					value={summary.openPositions}
					isLoading={isLoading}
				/>
				<StatCard
					label={t("totalExposure")}
					value={summary.totalExposure.toLocaleString("en-US", {
						maximumFractionDigits: 0,
					})}
					prefix="$"
					isLoading={isLoading}
				/>
				<StatCard
					label={t("unrealizedPnl")}
					value={(summary.unrealizedPnL ?? 0).toFixed(2)}
					prefix={(summary.unrealizedPnL ?? 0) >= 0 ? "+$" : "$"}
					pnlValue={summary.unrealizedPnL}
					isLoading={isLoading}
				/>
				<StatCard
					label={t("marginUsed")}
					value={summary.marginUsed.toLocaleString("en-US", {
						maximumFractionDigits: 0,
					})}
					prefix="$"
					isLoading={isLoading}
				/>
			</div>

			<Card>
				<CardHeader>
					<CardTitle>{t("activePositionsTitle")}</CardTitle>
					<CardDescription>{t("activePositionsDescription")}</CardDescription>
				</CardHeader>
				<CardContent>
					{isError && (
						<Alert variant="destructive" className="mb-4">
							<AlertTriangle className="h-4 w-4" />
							<AlertTitle>{t("errorLoading")}</AlertTitle>
							<AlertDescription>
								{error instanceof Error
									? error.message
									: t("common:errors.unknownError")}
							</AlertDescription>
						</Alert>
					)}

					<Table>
						<TableHeader>
							<TableRow>
								<TableHead>{t("colSymbol")}</TableHead>
								<TableHead>{t("colStrategy")}</TableHead>
								<TableHead>{t("colSide")}</TableHead>
								<TableHead className="text-right">{t("colSize")}</TableHead>
								<TableHead className="text-right">
									{t("colEntryPrice")}
								</TableHead>
								<TableHead className="text-right">
									{t("colMarkPrice")}
								</TableHead>
								<TableHead className="text-right">{t("colSlPrice")}</TableHead>
								<TableHead className="text-right">{t("colTpPrice")}</TableHead>
								<TableHead className="text-right">{t("colPnlUsd")}</TableHead>
								<TableHead className="text-right">
									{t("colPnlPercent")}
								</TableHead>
								<TableHead className="text-center">
									{t("common:actions")}
								</TableHead>
							</TableRow>
						</TableHeader>
						<TableBody>
							{isLoading ? (
								[...Array(3)].map((_, i) => (
									<TableRow key={i}>
										<TableCell colSpan={11}>
											<Skeleton className="h-8 w-full" />
										</TableCell>
									</TableRow>
								))
							) : Array.isArray(positions) &&
								positions.length === 0 &&
								!isError ? (
								<TableRow>
									<TableCell
										colSpan={11}
										className="h-24 text-center text-muted-foreground"
									>
										{t("noActivePositions")}
									</TableCell>
								</TableRow>
							) : (
								Array.isArray(positions) &&
								positions.map((pos) => (
									<TableRow
										key={pos.id}
										className="cursor-pointer hover:bg-muted/50 transition-colors"
										onClick={() => setViewingPositionId(pos.id)}
									>
										<TableCell className="font-medium mono">
											{pos.symbol}
										</TableCell>
										<TableCell className="text-muted-foreground">
											{pos.strategy}
										</TableCell>
										<TableCell>
											<Badge
												variant={
													pos.direction === "LONG" ? "default" : "destructive"
												}
											>
												{pos.direction}
											</Badge>
										</TableCell>
										<TableCell className="mono text-right">
											{pos.size}
										</TableCell>
										<TableCell className="mono text-right">
											${pos.entry_price?.toFixed(6) ?? "N/A"}
										</TableCell>
										<TableCell className="mono text-right">
											${pos.mark_price?.toFixed(6) ?? "N/A"}
										</TableCell>
										<TableCell className="mono text-right">
											{pos.stop_loss
												? `$${pos.stop_loss.toFixed(6)}`
												: t("common:na")}
										</TableCell>
										<TableCell className="mono text-right">
											{pos.take_profit
												? `$${pos.take_profit.toFixed(6)}`
												: t("common:na")}
										</TableCell>
										<TableCell
											className={`mono font-medium text-right ${pos.pnl >= 0 ? "text-profit" : "text-loss"}`}
										>
											{pos.pnl >= 0 ? "+" : ""}${pos.pnl?.toFixed(2) ?? "0.00"}
										</TableCell>
										<TableCell
											className={`mono font-medium text-right ${pos.pnl_percent >= 0 ? "text-profit" : "text-loss"}`}
										>
											{pos.pnl_percent?.toFixed(2) ?? "0.00"}%
										</TableCell>
										<TableCell className="text-center">
											<div className="flex items-center justify-center gap-2">
												<Button
													variant="ghost"
													size="icon"
													className="h-8 w-8 text-muted-foreground hover:text-primary"
													onClick={(e) => {
														e.stopPropagation();
														setViewingPositionId(pos.id);
													}}
												>
													<LineChart size={16} />
												</Button>
												<Button
													variant="ghost"
													size="icon"
													className="h-8 w-8"
													onClick={(e) => {
														e.stopPropagation();
														setEditingPosition(pos);
													}}
													disabled={
														!!closingSymbol ||
														isStoppingAll ||
														(isPaperMode && !pos.id.startsWith("test-"))
													}
												>
													<Pencil size={16} />
												</Button>
												<Button
													variant="destructive"
													size="sm"
													className="px-2 h-8 w-[60px]" // Set a fixed width for the button
													onClick={(e) =>
														handleClosePosition(pos.symbol, e, pos.id)
													}
													disabled={
														isStoppingAll ||
														!!closingSymbol ||
														(isPaperMode && !pos.id.startsWith("test-"))
													}
												>
													{closingSymbol === pos.symbol ? (
														<Loader2 className="w-4 h-4 animate-spin" />
													) : (
														t("common:close")
													)}
												</Button>
											</div>
										</TableCell>
									</TableRow>
								))
							)}
						</TableBody>
					</Table>
				</CardContent>
			</Card>

			<ConfirmationModal
				open={showConfirm}
				onOpenChange={setShowConfirm}
				title={t("emergencyStopConfirmTitle")}
				description={t("emergencyStopConfirmDesc")}
				onConfirm={handleEmergencyStopConfirm}
				loading={isStoppingAll}
			/>

			{editingPosition && (
				<EditSlTpModal
					isOpen={!!editingPosition}
					onClose={() => setEditingPosition(null)}
					position={editingPosition}
					onSubmit={handleEditSlTpSubmit}
					isLoading={isUpdatingSlTp}
				/>
			)}

			{viewingPosition && (
				<PositionChartModal
					position={viewingPosition}
					isOpen={!!viewingPosition}
					onClose={() => setViewingPositionId(null)}
					onSave={handleChartSave}
					isSaving={isUpdatingSlTp}
				/>
			)}
		</PageLayout>
	);
}
