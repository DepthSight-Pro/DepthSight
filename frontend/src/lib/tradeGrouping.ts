// src/lib/tradeGrouping.ts

import type { TradeData } from "@/types/api";

export interface GroupedPosition {
	position_id: string;
	symbol: string;
	strategy_config_id: string | null;
	entry_trade: TradeData | null;
	exit_trades: TradeData[];
	total_pnl: number;
	total_commission: number;
	total_quantity: number;
	entry_price: number;
	avg_exit_price: number;
	status: "OPEN" | "CLOSED";
	timestamp_entry: number;
	timestamp_close?: number;
}

/**
 * Groups trades into positions based on position_entry_id.
 * Trades with the same position_entry_id are considered parts of the same position.
 * For old trades without position_entry_id, each trade is considered a separate position.
 */
export function groupTradesByPosition(trades: TradeData[]): GroupedPosition[] {
	const positions = new Map<string, GroupedPosition>();

	trades.forEach((trade) => {
		// Use position_entry_id for grouping, or trade_uuid for old trades
		const positionId = trade.position_entry_id || trade.trade_uuid;

		if (!positions.has(positionId)) {
			positions.set(positionId, {
				position_id: positionId,
				symbol: trade.symbol,
				strategy_config_id: trade.strategy_config_id || null,
				entry_trade: null,
				exit_trades: [],
				total_pnl: 0,
				total_commission: 0,
				total_quantity: 0,
				entry_price: 0,
				avg_exit_price: 0,
				status: "OPEN",
				timestamp_entry: trade.timestamp_close,
			});
		}

		const position = positions.get(positionId)!;

		// Update position data
		position.total_pnl += trade.pnl || 0;
		position.total_commission += trade.commission || 0;
		position.total_quantity += trade.quantity || 0;

		// Classify the trade
		if (
			trade.exit_type === "ENTRY" ||
			(!trade.exit_type && Math.abs(trade.pnl || 0) < 0.01)
		) {
			// This is an entry into a position
			position.entry_trade = trade;
			position.entry_price = trade.entry_price || 0;
			position.timestamp_entry = trade.timestamp_close;
		} else {
			// This is an exit from a position (partial or full)
			position.exit_trades.push(trade);

			// Calculate the average exit price
			const totalExitValue = position.exit_trades.reduce(
				(sum, t) => sum + (t.exit_price || 0) * (t.quantity || 0),
				0,
			);
			const totalExitQty = position.exit_trades.reduce(
				(sum, t) => sum + (t.quantity || 0),
				0,
			);
			position.avg_exit_price =
				totalExitQty > 0 ? totalExitValue / totalExitQty : 0;

			// If this is the final exit, mark the position as closed
			if (trade.is_final_exit) {
				position.status = "CLOSED";
				position.timestamp_close = trade.timestamp_close;
			}
		}
	});

	// Sort by entry time (newest first)
	return Array.from(positions.values()).sort(
		(a, b) => b.timestamp_entry - a.timestamp_entry,
	);
}

/**
 * Calculates statistics for grouped positions
 */
export function calculatePositionStats(groupedPositions: GroupedPosition[]) {
	const totalPositions = groupedPositions.length;
	const closedPositions = groupedPositions.filter((p) => p.status === "CLOSED");
	const openPositions = groupedPositions.filter((p) => p.status === "OPEN");

	const totalPnl = groupedPositions.reduce(
		(sum, pos) => sum + pos.total_pnl,
		0,
	);
	const totalCommission = groupedPositions.reduce(
		(sum, pos) => sum + pos.total_commission,
		0,
	);

	const profitablePositions = groupedPositions.filter(
		(pos) => pos.total_pnl > 0,
	);
	const winRate =
		totalPositions > 0
			? (profitablePositions.length / totalPositions) * 100
			: 0;

	const avgPnlPerPosition = totalPositions > 0 ? totalPnl / totalPositions : 0;
	const avgCommissionPerPosition =
		totalPositions > 0 ? totalCommission / totalPositions : 0;

	// Average holding duration for closed positions
	const avgHoldingTimeMs =
		closedPositions.length > 0
			? closedPositions.reduce((sum, pos) => {
					if (pos.timestamp_close) {
						return sum + (pos.timestamp_close - pos.timestamp_entry);
					}
					return sum;
				}, 0) / closedPositions.length
			: 0;

	// Average profit factor
	const grossProfit = profitablePositions.reduce(
		(sum, pos) => sum + pos.total_pnl,
		0,
	);
	const grossLoss = Math.abs(
		groupedPositions
			.filter((pos) => pos.total_pnl < 0)
			.reduce((sum, pos) => sum + pos.total_pnl, 0),
	);
	const profitFactor =
		grossLoss > 0 ? grossProfit / grossLoss : grossProfit > 0 ? 999 : 0;

	return {
		totalPositions,
		closedPositions: closedPositions.length,
		openPositions: openPositions.length,
		totalPnl,
		totalCommission,
		netPnl: totalPnl - totalCommission,
		winRate,
		profitablePositions: profitablePositions.length,
		losingPositions: totalPositions - profitablePositions.length,
		avgPnlPerPosition,
		avgCommissionPerPosition,
		avgHoldingTimeMs,
		avgHoldingTimeHours: avgHoldingTimeMs / (1000 * 60 * 60),
		grossProfit,
		grossLoss,
		profitFactor,
	};
}
