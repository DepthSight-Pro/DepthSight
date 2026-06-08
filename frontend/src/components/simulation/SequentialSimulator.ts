// frontend/src/components/simulation/SequentialSimulator.ts

import type { SimulationConfig, SimulationResult, Trade } from "./types";

interface Position {
	id: string; // tradeId
	asset: string;
	strategy: string;
	entryTime: number;
	exitTime: number;
	entryPrice: number;
	exitPrice: number;
	pnlPct: number;
	positionSize: number; // In dollars
	riskAmount: number; // In dollars (what we are willing to lose)
	slotIndex?: number;
}

export class SequentialSimulator {
	private config: SimulationConfig;
	private capital: number;
	private peakCapital: number;
	private activePositions: Position[] = [];
	private closedTrades: Trade[] = [];
	private equityCurve: { time: number; value: number; drawdown: number }[] = [];
	private skippedTrades: number = 0;
	private availableSlots: boolean[];

	constructor(config: SimulationConfig) {
		this.config = config;
		this.capital = config.initialCapital;
		this.peakCapital = config.initialCapital;
		// Initialize slots
		this.availableSlots = new Array(config.maxConcurrentPositions).fill(true);

		// Initial equity point
		this.equityCurve.push({
			time: 0,
			value: this.capital,
			drawdown: 0,
		});
	}

	public simulate(trades: Trade[]): SimulationResult {
		// Re-initialize if config changed
		if (this.availableSlots.length !== this.config.maxConcurrentPositions) {
			this.availableSlots = new Array(this.config.maxConcurrentPositions).fill(
				true,
			);
		}

		// 1. Sort trades by entry time
		const sortedTrades = [...trades].sort((a, b) => a.entryTime - b.entryTime);

		if (sortedTrades.length > 0) {
			// Update first point time
			this.equityCurve[0].time = sortedTrades[0].entryTime - 1000;
		}

		// 2. Simulation Loop
		for (const trade of sortedTrades) {
			const currentTime = trade.entryTime;

			// A. Close finished positions
			this.closeFinishedPositions(currentTime);

			// B. Open new position if possible
			if (this.activePositions.length < this.config.maxConcurrentPositions) {
				if (this.capital > 0) {
					this.openPosition(trade);
				}
			} else {
				this.skippedTrades++;
			}
		}

		// 3. Close remaining positions
		this.closeFinishedPositions(Number.MAX_SAFE_INTEGER);

		// 4. Calculate final stats
		return this.calculateStatistics();
	}

	private closeFinishedPositions(currentTime: number) {
		const remaining: Position[] = [];

		for (const pos of this.activePositions) {
			if (pos.exitTime <= currentTime) {
				// Free up the slot
				if (
					pos.slotIndex !== undefined &&
					pos.slotIndex >= 0 &&
					pos.slotIndex < this.availableSlots.length
				) {
					this.availableSlots[pos.slotIndex] = true;
				}

				// Close Position
				const pnlAmount = pos.positionSize * pos.pnlPct;
				this.capital += pnlAmount;

				// Update Peak Capital
				if (this.capital > this.peakCapital) {
					this.peakCapital = this.capital;
				}

				// Calculate current drawdown
				const drawdown =
					this.peakCapital > 0
						? ((this.peakCapital - this.capital) / this.peakCapital) * 100
						: 0;

				// Record Trade
				this.closedTrades.push({
					id: pos.id,
					asset: pos.asset,
					strategy: pos.strategy,
					entryTime: pos.entryTime,
					exitTime: pos.exitTime,
					entryPrice: pos.entryPrice,
					exitPrice: pos.exitPrice,
					pnlPct: pos.pnlPct,
					pnlAmount: pnlAmount,
					status: "closed",
					reason: "signal",
					slotIndex: pos.slotIndex, // Pass slot index to trade result
				});

				// Record Equity Curve Point
				this.equityCurve.push({
					time: pos.exitTime,
					value: this.capital,
					drawdown: drawdown,
				});
			} else {
				remaining.push(pos);
			}
		}
		this.activePositions = remaining;
	}

	private openPosition(trade: Trade) {
		// --- Position Sizing Logic (Matches Python) ---

		// 1. Available Capital with Leverage
		// Note: Python script checks available capital globally.
		// available_capital_with_leverage = self.capital * self.config.leverage
		const availableCapitalWithLeverage = this.capital * this.config.leverage;

		// 2. Used Capital
		const usedCapital = this.activePositions.reduce(
			(sum, p) => sum + p.positionSize,
			0,
		);

		// 3. Free Capital
		const freeCapital = availableCapitalWithLeverage - usedCapital;

		// 4. Risk Calculation
		// base_risk_pct (e.g. 1%) of CURRENT capital
		const riskAmount = this.capital * (this.config.baseRiskPct / 100);

		// 5. Estimated Stop Loss (Default 6% if not dynamic)
		// Python: stop_loss_pct = self.config.estimated_stop_loss_pct (0.06)
		const estimatedStopLossPct = 0.06;

		// 6. Ideal Position Size = Risk / Distance to SL
		const idealPositionSize = riskAmount / estimatedStopLossPct;

		// 7. Real Position Size (capped by free capital)
		const positionSize = Math.min(idealPositionSize, freeCapital);

		// 8. Skip if too small ( < 50% of ideal)
		if (positionSize < idealPositionSize * 0.5) {
			this.skippedTrades++;
			return;
		}

		// Find available slot
		const slotIndex = this.availableSlots.findIndex(
			(isAvailable) => isAvailable,
		);
		// Reserve the slot
		if (slotIndex !== -1) {
			this.availableSlots[slotIndex] = false;
		}

		// Open Position
		this.activePositions.push({
			id: trade.id,
			asset: trade.asset,
			strategy: trade.strategy,
			entryTime: trade.entryTime,
			exitTime: trade.exitTime,
			entryPrice: trade.entryPrice,
			exitPrice: trade.exitPrice,
			pnlPct: trade.pnlPct,
			positionSize: positionSize,
			riskAmount: riskAmount,
			slotIndex: slotIndex !== -1 ? slotIndex : 0, // Fallback to 0 if something weird happens, though shouldn't with correct checks
		});
	}

	private calculateStatistics(): SimulationResult {
		// Sort equity curve by time
		this.equityCurve.sort((a, b) => a.time - b.time);

		const totalPnl = this.capital - this.config.initialCapital;
		const totalPnlPct = (totalPnl / this.config.initialCapital) * 100;

		const trades = this.closedTrades;
		const winningTrades = trades.filter((t) => t.pnlAmount > 0);
		const losingTrades = trades.filter((t) => t.pnlAmount <= 0);

		const totalTrades = trades.length;
		const winRate =
			totalTrades > 0 ? (winningTrades.length / totalTrades) * 100 : 0;

		const avgWin =
			winningTrades.length > 0
				? (winningTrades.reduce((acc, t) => acc + t.pnlPct, 0) /
						winningTrades.length) *
					100
				: 0;

		const avgLoss =
			losingTrades.length > 0
				? Math.abs(
						losingTrades.reduce((acc, t) => acc + t.pnlPct, 0) /
							losingTrades.length,
					) * 100
				: 0;

		const grossProfit = winningTrades.reduce((acc, t) => acc + t.pnlAmount, 0);
		const grossLoss = Math.abs(
			losingTrades.reduce((acc, t) => acc + t.pnlAmount, 0),
		);
		const profitFactor =
			grossLoss > 0 ? grossProfit / grossLoss : grossProfit > 0 ? Infinity : 0;

		// Max Drawdown calculation from equity curve
		let maxDrawdown = 0;
		for (const point of this.equityCurve) {
			if (point.drawdown > maxDrawdown) {
				maxDrawdown = point.drawdown;
			}
		}

		// Sharpe Ratio (Simplified)
		let sharpeRatio = 0;
		if (trades.length > 1) {
			const returns = trades.map(
				(t) => t.pnlAmount / this.config.initialCapital,
			); // Should technically be return relative to capital at entry, but simplified
			const meanReturn = returns.reduce((a, b) => a + b, 0) / returns.length;
			const variance =
				returns.reduce((sum, r) => sum + (r - meanReturn) ** 2, 0) /
				returns.length;
			const stdDev = Math.sqrt(variance);
			sharpeRatio =
				stdDev > 0.000001
					? (meanReturn / stdDev) * Math.sqrt(trades.length)
					: 0;
		}

		return {
			trades: this.closedTrades,
			equityCurve: this.equityCurve,
			stats: {
				totalPnl,
				totalPnlPct,
				winRate,
				profitFactor,
				sharpeRatio,
				maxDrawdown,
				skippedTrades: this.skippedTrades,
				avgWin,
				avgLoss,
			},
		};
	}
}
