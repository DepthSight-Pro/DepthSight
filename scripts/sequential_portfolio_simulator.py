"""
Sequential Portfolio Trading Simulator with Adaptive Risk Management
Uses pre-calculated trades from dashboard_data.pkl
"""

import pickle
import pandas as pd
import numpy as np
import logging
from datetime import datetime, timedelta, date
from typing import List, Dict, Tuple, Optional
from dataclasses import dataclass
from pathlib import Path

try:
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots
    PLOTLY_AVAILABLE = True
except ImportError:
    PLOTLY_AVAILABLE = False
    go = None
    make_subplots = None

logger = logging.getLogger(__name__)

@dataclass
class SimulatorConfig:
    """Simulator Configuration"""
    initial_capital: float = 100.0
    max_concurrent_positions: int = 5
    base_risk_pct: float = 0.5
    leverage: float = 5.0  # Leverage
    
    # Adaptive Risk Management
    adaptive_risk_enabled: bool = True
    adaptive_risk_per_symbol: bool = True
    rolling_window_size: int = 10
    min_trades_for_assessment: int = 5
    
    # Risk Reduction Thresholds
    pnl_threshold_pct: float = -5.0
    win_rate_threshold_pct: float = 20.0
    max_consecutive_losses: int = 5
    
    # Risk Multipliers
    risk_multipliers: List[float] = None
    default_multiplier: float = 1.0
    
    # Risk Recovery
    recovery_consecutive_wins: int = 2
    recovery_pnl_threshold_pct: float = 5.0
    cooldown_seconds: int = 3600
    
    # Safety Mechanisms
    emergency_brake_dd_pct: float = 50.0
    emergency_max_risk_pct: float = 0.2

    estimated_stop_loss_pct: float = 0.06 
    
    def __post_init__(self):
        if self.risk_multipliers is None:
            self.risk_multipliers = [0.1, 0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 1.75, 2.0]


class AdaptiveRiskManager:
    """Adaptive Risk Manager for strategy-symbol pairs"""
    
    def __init__(self, config: SimulatorConfig):
        self.config = config
        self.performance_history: Dict[str, List[Dict]] = {}
        self.current_multipliers: Dict[str, float] = {}
        self.consecutive_wins: Dict[str, int] = {}
        self.consecutive_losses: Dict[str, int] = {}
        self.last_penalty_time: Dict[str, datetime] = {}
    
    def get_risk_multiplier(self, strategy_symbol: str, current_time: datetime) -> float:
        """Get current risk multiplier for strategy-symbol pair"""
        if not self.config.adaptive_risk_enabled:
            return self.config.default_multiplier
        
        # If global risk management, use "GLOBAL" key
        key = "GLOBAL" if not self.config.adaptive_risk_per_symbol else strategy_symbol
        
        if key not in self.current_multipliers:
            self.current_multipliers[key] = self.config.default_multiplier
        
        return self.current_multipliers[key]
    
    def update_performance(self, strategy_symbol: str, trade_result: Dict, current_time: datetime):
        """Update performance and adjust risk"""
        if not self.config.adaptive_risk_enabled:
            return
        
        # If global risk management, use "GLOBAL" key
        key = "GLOBAL" if not self.config.adaptive_risk_per_symbol else strategy_symbol
        
        # Initialization
        if key not in self.performance_history:
            self.performance_history[key] = []
            self.current_multipliers[key] = self.config.default_multiplier
            self.consecutive_wins[key] = 0
            self.consecutive_losses[key] = 0
        
        # Add result
        self.performance_history[key].append(trade_result)
        
        # Update streaks
        if trade_result['pnl'] > 0:
            self.consecutive_wins[key] += 1
            self.consecutive_losses[key] = 0
        else:
            self.consecutive_losses[key] += 1
            self.consecutive_wins[key] = 0
        
        # Check if risk adjustment is needed
        if len(self.performance_history[key]) >= self.config.min_trades_for_assessment:
            self._adjust_risk(key, current_time)
    
    def _adjust_risk(self, strategy_symbol: str, current_time: datetime):
        """Adjust risk based on performance"""
        history = self.performance_history[strategy_symbol][-self.config.rolling_window_size:]
        
        if len(history) < self.config.min_trades_for_assessment:
            return
        
        # 1. Calculate Win Rate
        wins = sum(1 for t in history if t['pnl'] > 0)
        win_rate = (wins / len(history)) * 100
        
        # 2. Calculate risk efficiency
        total_pnl = sum(t['pnl'] for t in history)
        
        # Use risk_amount or planned_risk
        total_risk = sum(t.get('risk_amount', t.get('planned_risk', 1.0)) for t in history)
        
        # % PnL from sum of risks (R-multiple in percent)
        pnl_vs_risk_pct = (total_pnl / total_risk * 100) if total_risk > 0 else 0
        
        current_multiplier = self.current_multipliers[strategy_symbol]
        current_idx = self._get_multiplier_index(current_multiplier)
        
        # Check conditions for risk DECREASE
        should_decrease = (
            pnl_vs_risk_pct < self.config.pnl_threshold_pct or
            win_rate < self.config.win_rate_threshold_pct or
            self.consecutive_losses[strategy_symbol] >= self.config.max_consecutive_losses
        )
        
        if should_decrease and current_idx > 0:
            # Decrease risk BY ONE STEP
            new_idx = current_idx - 1
            new_multiplier = self.config.risk_multipliers[new_idx]
            self.current_multipliers[strategy_symbol] = new_multiplier
            self.last_penalty_time[strategy_symbol] = current_time
            return
        
        # Check conditions for risk INCREASE
        in_cooldown = False
        if strategy_symbol in self.last_penalty_time:
            time_since_penalty = (current_time - self.last_penalty_time[strategy_symbol]).total_seconds()
            in_cooldown = time_since_penalty < self.config.cooldown_seconds
        
        should_increase = (
            not in_cooldown and
            (self.consecutive_wins[strategy_symbol] >= self.config.recovery_consecutive_wins or
             pnl_vs_risk_pct > self.config.recovery_pnl_threshold_pct)
        )
        
        if should_increase and current_idx < len(self.config.risk_multipliers) - 1:
            # Increase risk BY ONE STEP
            new_idx = current_idx + 1
            new_multiplier = self.config.risk_multipliers[new_idx]
            self.current_multipliers[strategy_symbol] = new_multiplier
            
            # Logging (disabled for performance)
            # print(f"✅ {strategy_symbol}: Risk UP {current_multiplier:.2f}x → {new_multiplier:.2f}x (WR: {win_rate:.1f}%, PnL: {pnl_vs_risk_pct:.1f}%, Wins: {self.consecutive_wins[strategy_symbol]})")
    
    def _get_multiplier_index(self, multiplier: float) -> int:
        """Get multiplier index in the list"""
        try:
            return self.config.risk_multipliers.index(multiplier)
        except ValueError:
            # Find nearest
            return min(range(len(self.config.risk_multipliers)), 
                      key=lambda i: abs(self.config.risk_multipliers[i] - multiplier))


class SequentialPortfolioSimulator:
    """Sequential Portfolio Trading Simulator"""
    
    def __init__(self, config: SimulatorConfig):
        self.config = config
        self.risk_manager = AdaptiveRiskManager(config)
        
        # Simulation State
        self.capital = config.initial_capital
        self.peak_capital = config.initial_capital
        self.active_positions: List[Dict] = []
        self.closed_trades: List[Dict] = []
        self.equity_curve: List[Dict] = []
        self.skipped_trades = 0  # Counter for skipped trades
        
    def load_trades_from_pickle(self, pickle_path: str = "dashboard_data.pkl", strategies: List[str] = None) -> pd.DataFrame:
        """Load all trades from pickle file
        
        Args:
            pickle_path: path to data file
            strategies: list of strategies to load ['base', 'oracle', 'ml', 'combined']
                       if None, only 'base' is loaded
        """
        if strategies is None:
            strategies = ['base']
            
        with open(pickle_path, "rb") as f:
            data = pickle.load(f)
        
        all_trades = []
        
        for asset_name, asset_data in data["assets_data"].items():
            for strategy_name in strategies:
                # Check if strategy exists in data
                if strategy_name not in asset_data:
                    continue
                
                trades = asset_data[strategy_name]["trades"]
                
                for trade in trades:
                    trade_copy = trade.copy()
                    trade_copy['asset'] = asset_name
                    trade_copy['strategy'] = strategy_name
                    all_trades.append(trade_copy)
        
        # Create DataFrame and sort by entry time
        df = pd.DataFrame(all_trades)
        df['entry_time'] = pd.to_datetime(df['entry_time'])
        df['exit_time'] = pd.to_datetime(df['exit_time'])
        df = df.sort_values('entry_time').reset_index(drop=True)
        
        return df
    
    def simulate(self, trades_df: pd.DataFrame) -> Dict:
        """Run Simulation"""
        print(f"🚀 Starting simulation...")
        print(f"   Initial capital: ${self.config.initial_capital:.2f}")
        print(f"   Available with leverage: ${self.config.initial_capital * self.config.leverage:.2f}")
        print(f"   Max positions: {self.config.max_concurrent_positions}")
        print(f"   Base risk: {self.config.base_risk_pct}% (${self.config.initial_capital * self.config.base_risk_pct / 100:.2f} per trade)")
        print(f"   Leverage: {self.config.leverage}x")
        print(f"   Adaptive risk: {'ON' if self.config.adaptive_risk_enabled else 'OFF'}")
        print(f"   Total trades in data: {len(trades_df)}\n")
        
        # Create queue of potential trades
        pending_trades = trades_df.to_dict('records')
        
        # Time-based simulation
        for trade_opp in pending_trades:
            entry_time = trade_opp['entry_time']
            
            # Close positions finished before this time
            self._close_finished_positions(entry_time)
            
            # Try to open new position if space available
            if len(self.active_positions) < self.config.max_concurrent_positions:
                if self.capital > 0:
                    self._open_position(trade_opp)
        
        # Close all remaining positions
        self._close_finished_positions()
        
        # Final Statistics
        return self._calculate_statistics()
    
    def _open_position(self, trade_opp: Dict):
        strategy_symbol = f"{trade_opp['strategy']}_{trade_opp['asset']}"
        
        risk_multiplier = self.risk_manager.get_risk_multiplier(strategy_symbol, trade_opp['entry_time'])
        
        # Apply emergency brake
        current_dd = ((self.capital - self.peak_capital) / self.peak_capital * 100) if self.peak_capital > 0 else 0
        if abs(current_dd) > self.config.emergency_brake_dd_pct:
            effective_risk = min(
                self.config.base_risk_pct * risk_multiplier,
                self.config.emergency_max_risk_pct
            )
        else:
            effective_risk = self.config.base_risk_pct * risk_multiplier
        
        # Calculate position size CORRECTLY
        # 
        # Logic:
        # 1. Available capital with leverage = capital * leverage
        # 2. Risk per trade = capital * risk_pct (amount willing to lose)
        # 3. Position size = risk_amount / stop_loss_pct
        # 4. BUT! Position size limited by available capital with leverage
        
        # Available capital including leverage
        available_capital_with_leverage = self.capital * self.config.leverage
        
        # Capital already used in open positions
        used_capital = sum(pos['position_size'] for pos in self.active_positions)
        
        # Free capital for new position
        free_capital = available_capital_with_leverage - used_capital
        
        # Risk in dollars (amount willing to lose)
        risk_amount = self.capital * (effective_risk / 100)
        
        # Stop loss from trade (usually 6%)
        # Attempt to find in data, otherwise use constant. Do not use pnl_pct for this!
        # If your strategy implies fixed stop, better to hardcode it.
        stop_loss_pct = self.config.estimated_stop_loss_pct
        
        # Position size = Risk / % price movement to stop
        ideal_position_size = risk_amount / stop_loss_pct
        
        # Real position size (limited by free capital)
        position_size = min(ideal_position_size, free_capital)
        
        # If insufficient capital, skip trade
        if position_size < ideal_position_size * 0.5:  # If we can open less than 50% of desired
            self.skipped_trades += 1
            return  # Skip this trade
        
        # Open position
        position = {
            'asset': trade_opp['asset'],
            'strategy': trade_opp['strategy'],
            'strategy_symbol': strategy_symbol,
            'entry_time': trade_opp['entry_time'],
            'exit_time': trade_opp['exit_time'],
            'entry_price': trade_opp.get('entry_price', 1.0),
            'exit_price': trade_opp.get('exit_price', trade_opp.get('entry_price', 1.0) * (1 + trade_opp.get('pnl_pct', 0.0))),
            'pnl_pct': trade_opp['pnl_pct'],
            'commission_pct': trade_opp.get('commission_pct', 0.0024),
            'risk_amount': risk_amount,
            'position_size': position_size,
            'risk_multiplier': risk_multiplier,
            'effective_risk_pct': effective_risk,
            'capital_at_entry': self.capital
        }
        
        self.active_positions.append(position)
    
    def _close_finished_positions(self, current_time=None):
        """Close finished positions
        
        Args:
            current_time: current simulation time. If None, all positions are closed.
                         Otherwise only positions with exit_time <= current_time are closed.
        """
        if not self.active_positions:
            return
        
        # Split into closed and active
        still_active = []
        to_close = []
        
        for position in self.active_positions:
            # Position closes if current_time=None or exit_time <= current_time
            if current_time is None or position['exit_time'] <= current_time:
                to_close.append(position)
            else:
                still_active.append(position)
        
        # Close positions
        for position in to_close:
            # Calculate PnL
            # pnl_pct is already in decimal (e.g., -0.0599 for -5.99%), multiply directly
            # Leverage is already reflected in position_size, so:
            pnl_amount = position['position_size'] * position['pnl_pct']
            
            # Calculate commission in dollars
            # commission_pct includes total commission (entry + exit)
            commission_amount = position['position_size'] * position.get('commission_pct', 0.0024)
            
            # Update capital
            self.capital += pnl_amount
            
            # Update peak
            if self.capital > self.peak_capital:
                self.peak_capital = self.capital
            
            # Save closed trade
            closed_trade = position.copy()
            closed_trade['pnl_amount'] = pnl_amount
            closed_trade['commission_amount'] = commission_amount  # Commission in USD
            closed_trade['capital_after'] = self.capital
            closed_trade['drawdown'] = ((self.capital - self.peak_capital) / self.peak_capital * 100) if self.peak_capital > 0 else 0
            
            self.closed_trades.append(closed_trade)
            
            # Update risk manager
            self.risk_manager.update_performance(
                position['strategy_symbol'],
                {
                    'pnl': pnl_amount,
                    'risk_amount': position['risk_amount'], # Pass risk in USD
                    'time': position['exit_time']
                },
                position['exit_time']
            )
            
            # Record equity curve point
            self.equity_curve.append({
                'time': position['exit_time'],
                'capital': self.capital,
                'drawdown': closed_trade['drawdown']
            })
        
        # Update active positions list (keep only unclosed)
        self.active_positions = still_active
    
    def _calculate_statistics(self) -> Dict:
        """Calculate Final Statistics"""
        if not self.closed_trades:
            return {}
        
        df = pd.DataFrame(self.closed_trades)
        
        # Base metrics
        total_trades = len(df)
        wins = df[df['pnl_amount'] > 0]
        losses = df[df['pnl_amount'] <= 0]
        
        total_pnl = self.capital - self.config.initial_capital
        total_pnl_pct = (total_pnl / self.config.initial_capital) * 100
        
        win_rate = (len(wins) / total_trades * 100) if total_trades > 0 else 0
        
        # Absolute amounts (in dollars)
        avg_win = wins['pnl_amount'].mean() if len(wins) > 0 else 0
        avg_loss = abs(losses['pnl_amount'].mean()) if len(losses) > 0 else 0
        
        # Percentage-based (for frontend display)
        avg_win_pct = (wins['pnl_pct'].mean() * 100) if len(wins) > 0 else 0  # pnl_pct is in decimal form
        avg_loss_pct = abs((losses['pnl_pct'].mean() * 100)) if len(losses) > 0 else 0
        
        profit_factor = (wins['pnl_amount'].sum() / abs(losses['pnl_amount'].sum())) if len(losses) > 0 and losses['pnl_amount'].sum() != 0 else 0
        
        max_dd = df['drawdown'].min()
        
        # Streaks
        df['is_win'] = df['pnl_amount'] > 0
        df['streak'] = (df['is_win'] != df['is_win'].shift()).cumsum()
        streaks = df.groupby('streak')['is_win'].agg(['first', 'count'])
        
        max_win_streak = streaks[streaks['first'] == True]['count'].max() if len(streaks[streaks['first'] == True]) > 0 else 0
        max_loss_streak = streaks[streaks['first'] == False]['count'].max() if len(streaks[streaks['first'] == False]) > 0 else 0
        
        # Sharpe (simplified)
        returns = df['pnl_amount'] / df['capital_at_entry']
        sharpe = (returns.mean() / returns.std()) * np.sqrt(len(returns)) if returns.std() > 0 else 0
        
        # Average risk multiplier
        avg_risk_multiplier = df['risk_multiplier'].mean()
        
        return {
            'initial_capital': self.config.initial_capital,
            'final_capital': self.capital,
            'total_pnl': total_pnl,
            'total_pnl_pct': total_pnl_pct,
            'total_trades': total_trades,
            'skipped_trades': self.skipped_trades,
            'win_rate': win_rate,
            'profit_factor': profit_factor,
            'avg_win': avg_win,
            'avg_loss': avg_loss,
            'avg_win_pct': avg_win_pct,
            'avg_loss_pct': avg_loss_pct,
            'max_drawdown': max_dd,
            'max_win_streak': int(max_win_streak),
            'max_loss_streak': int(max_loss_streak),
            'sharpe_ratio': sharpe,
            'avg_risk_multiplier': avg_risk_multiplier,
            'trades_df': df,
            'equity_curve': pd.DataFrame(self.equity_curve)
        }


def plot_results(stats: Dict, config: SimulatorConfig):
    """Visualize Results"""
    fig = make_subplots(
        rows=3, cols=2,
        subplot_titles=(
            'Equity Curve', 
            'Drawdown',
            'Risk Multiplier (Rolling Avg)',
            'PnL Distribution',
            'Cumulative PnL',
            'Win/Loss Streaks'
        ),
        specs=[
            [{"secondary_y": False}, {"secondary_y": False}],
            [{"secondary_y": False}, {"secondary_y": False}],
            [{"secondary_y": False}, {"secondary_y": False}]
        ],
        vertical_spacing=0.12,
        horizontal_spacing=0.12
    )
    
    eq_df = stats['equity_curve'].copy()
    trades_df = stats['trades_df'].copy()
    
    # 1. Equity Curve - simplified
    fig.add_trace(
        go.Scatter(
            x=eq_df['time'], 
            y=eq_df['capital'],
            name='Capital',
            line=dict(color='#00CCFF', width=3),
            hovertemplate='<b>Time:</b> %{x}<br><b>Capital:</b> $%{y:.2f}<extra></extra>'
        ),
        row=1, col=1
    )
    
    # 2. Drawdown - inverted for better readability
    fig.add_trace(
        go.Scatter(
            x=eq_df['time'],
            y=eq_df['drawdown'],
            name='Drawdown',
            line=dict(color='#FF4B4B', width=2),
            fill='tozeroy',
            fillcolor='rgba(255, 75, 75, 0.4)',
            hovertemplate='<b>Time:</b> %{x}<br><b>DD:</b> %{y:.2f}%<extra></extra>'
        ),
        row=1, col=2
    )
    
    # 3. Risk Multiplier - moving average for readability
    trades_df['risk_ma'] = trades_df['risk_multiplier'].rolling(window=20, min_periods=1).mean()
    fig.add_trace(
        go.Scatter(
            x=trades_df['exit_time'],
            y=trades_df['risk_ma'],
            name='Risk Multiplier (MA20)',
            line=dict(color='#FFD700', width=2),
            hovertemplate='<b>Time:</b> %{x}<br><b>Risk:</b> %{y:.2f}x<extra></extra>'
        ),
        row=2, col=1
    )
    
    # Add horizontal line at 1.0
    fig.add_hline(y=1.0, line_dash="dash", line_color="gray", opacity=0.5, row=2, col=1)
    
    # 4. PnL Distribution - wins and losses
    wins = trades_df[trades_df['pnl_amount'] > 0]['pnl_amount']
    losses = trades_df[trades_df['pnl_amount'] <= 0]['pnl_amount']
    
    fig.add_trace(
        go.Histogram(
            x=wins,
            name='Wins',
            marker=dict(color='#00FF7F', opacity=0.7),
            nbinsx=30,
            hovertemplate='<b>PnL:</b> $%{x:.2f}<br><b>Count:</b> %{y}<extra></extra>'
        ),
        row=2, col=2
    )
    
    fig.add_trace(
        go.Histogram(
            x=losses,
            name='Losses',
            marker=dict(color='#FF4B4B', opacity=0.7),
            nbinsx=30,
            hovertemplate='<b>PnL:</b> $%{x:.2f}<br><b>Count:</b> %{y}<extra></extra>'
        ),
        row=2, col=2
    )
    
    # 5. Cumulative PnL
    trades_df['cum_pnl'] = trades_df['pnl_amount'].cumsum()
    fig.add_trace(
        go.Scatter(
            x=trades_df['exit_time'],
            y=trades_df['cum_pnl'],
            name='Cumulative PnL',
            line=dict(color='#8A2BE2', width=3),
            fill='tozeroy',
            fillcolor='rgba(138, 43, 226, 0.3)',
            hovertemplate='<b>Time:</b> %{x}<br><b>Cum PnL:</b> $%{y:.2f}<extra></extra>'
        ),
        row=3, col=1
    )
    
    # 6. Win/Loss Streaks - simplified
    trades_df['is_win'] = trades_df['pnl_amount'] > 0
    trades_df['streak_change'] = (trades_df['is_win'] != trades_df['is_win'].shift()).cumsum()
    
    streaks = trades_df.groupby('streak_change').agg({
        'is_win': 'first',
        'exit_time': 'first',
        'pnl_amount': 'size'
    }).reset_index()
    streaks.columns = ['streak_id', 'is_win', 'time', 'length']
    
    # Split into win and loss streaks
    win_streaks = streaks[streaks['is_win']]
    loss_streaks = streaks[~streaks['is_win']]
    
    fig.add_trace(
        go.Bar(
            x=win_streaks['time'],
            y=win_streaks['length'],
            name='Win Streaks',
            marker=dict(color='#00FF7F'),
            hovertemplate='<b>Time:</b> %{x}<br><b>Streak:</b> %{y}<extra></extra>'
        ),
        row=3, col=2
    )
    
    fig.add_trace(
        go.Bar(
            x=loss_streaks['time'],
            y=-loss_streaks['length'],  # Negative for visual separation
            name='Loss Streaks',
            marker=dict(color='#FF4B4B'),
            hovertemplate='<b>Time:</b> %{x}<br><b>Streak:</b> %{y}<extra></extra>'
        ),
        row=3, col=2
    )
    
    # Update layout
    fig.update_layout(
        height=1400,
        template='plotly_dark',
        showlegend=True,
        title_text=f"<b>Sequential Portfolio Simulation</b><br>Final: ${stats['final_capital']:.2f} ({stats['total_pnl_pct']:.2f}%) | Max DD: {stats['max_drawdown']:.2f}% | Win Rate: {stats['win_rate']:.2f}%",
        title_font_size=16,
        hovermode='x unified'
    )
    
    # Update axes
    fig.update_xaxes(title_text="Date", row=1, col=1, showgrid=True, gridcolor='rgba(128,128,128,0.2)')
    fig.update_xaxes(title_text="Date", row=1, col=2, showgrid=True, gridcolor='rgba(128,128,128,0.2)')
    fig.update_xaxes(title_text="Date", row=2, col=1, showgrid=True, gridcolor='rgba(128,128,128,0.2)')
    fig.update_xaxes(title_text="PnL ($)", row=2, col=2, showgrid=True, gridcolor='rgba(128,128,128,0.2)')
    fig.update_xaxes(title_text="Date", row=3, col=1, showgrid=True, gridcolor='rgba(128,128,128,0.2)')
    fig.update_xaxes(title_text="Date", row=3, col=2, showgrid=True, gridcolor='rgba(128,128,128,0.2)')
    
    fig.update_yaxes(title_text="Capital ($)", row=1, col=1, showgrid=True, gridcolor='rgba(128,128,128,0.2)')
    fig.update_yaxes(title_text="Drawdown (%)", row=1, col=2, showgrid=True, gridcolor='rgba(128,128,128,0.2)')
    fig.update_yaxes(title_text="Risk Multiplier", row=2, col=1, showgrid=True, gridcolor='rgba(128,128,128,0.2)')
    fig.update_yaxes(title_text="Frequency", row=2, col=2, showgrid=True, gridcolor='rgba(128,128,128,0.2)')
    fig.update_yaxes(title_text="Cumulative PnL ($)", row=3, col=1, showgrid=True, gridcolor='rgba(128,128,128,0.2)')
    fig.update_yaxes(title_text="Streak Length", row=3, col=2, showgrid=True, gridcolor='rgba(128,128,128,0.2)')
    
    return fig


def print_statistics(stats: Dict):
    """Print statistics to console"""
    print("\n" + "="*80)
    print("📊 SIMULATION RESULTS")
    print("="*80)
    
    print(f"\n💰 CAPITAL:")
    print(f"   Initial: ${stats['initial_capital']:.2f}")
    print(f"   Final: ${stats['final_capital']:.2f}")
    print(f"   PnL: ${stats['total_pnl']:.2f} ({stats['total_pnl_pct']:.2f}%)")
    
    print(f"\n📈 PERFORMANCE:")
    print(f"   Total Trades: {stats['total_trades']}")
    print(f"   Skipped Trades: {stats['skipped_trades']} (insufficient capital)")
    print(f"   Win Rate: {stats['win_rate']:.2f}%")
    print(f"   Profit Factor: {stats['profit_factor']:.2f}")
    print(f"   Sharpe Ratio: {stats['sharpe_ratio']:.2f}")
    
    print(f"\n💵 AVERAGES:")
    print(f"   Avg Win: ${stats['avg_win']:.2f}")
    print(f"   Avg Loss: ${stats['avg_loss']:.2f}")
    print(f"   Avg Risk Multiplier: {stats['avg_risk_multiplier']:.2f}x")
    
    print(f"\n📉 RISKS:")
    print(f"   Max Drawdown: {stats['max_drawdown']:.2f}%")
    print(f"   Max Win Streak: {stats['max_win_streak']}")
    print(f"   Max Loss Streak: {stats['max_loss_streak']}")
    
    print("\n" + "="*80)


def compare_strategies():
    """Compare all strategies and save results"""
    # All 4 strategies from dashboard_data.pkl
    strategies = ['base', 'oracle_no_exit', 'oracle_exit_5min', 'oracle_breakeven']
    
    # Configuration for sequential trading
    config = SimulatorConfig(
        initial_capital=100.0,
        max_concurrent_positions=5,
        base_risk_pct=1.0,  # 1% risk per trade
        leverage=5.0,  # 5x leverage for entire portfolio
        adaptive_risk_enabled=False,
        rolling_window_size=10,
        min_trades_for_assessment=5,
        pnl_threshold_pct=-10.0,
        win_rate_threshold_pct=20.0,
        max_consecutive_losses=10,
        recovery_consecutive_wins=1,
        recovery_pnl_threshold_pct=10.0,
        cooldown_seconds=3600,
        emergency_brake_dd_pct=50.0,
        emergency_max_risk_pct=0.5
    )
    
    print("🚀 Sequential Trading Strategy Comparison\n")
    print("="*80)
    
    results = {}
    
    for strategy in strategies:
        print(f"\n📊 Testing Strategy: {strategy.upper()}")
        print("-"*80)
        
        simulator = SequentialPortfolioSimulator(config)
        
        try:
            trades_df = simulator.load_trades_from_pickle(strategies=[strategy])
            print(f"   Loaded trades: {len(trades_df)}")
            
            if len(trades_df) == 0:
                print(f"   ⚠️  No trades for strategy {strategy}")
                continue
            
            stats = simulator.simulate(trades_df)
            
            if stats:
                results[strategy] = stats
                print(f"   ✅ Final Capital: ${stats['final_capital']:.2f} ({stats['total_pnl_pct']:.2f}%)")
                print(f"   ✅ Max DD: {stats['max_drawdown']:.2f}%")
                print(f"   ✅ Win Rate: {stats['win_rate']:.2f}%")
                print(f"   ✅ Sharpe: {stats['sharpe_ratio']:.2f}")
        except Exception as e:
            print(f"   ❌ Error: {e}")
    
    # Create comparison table
    print("\n" + "="*80)
    print("📊 SUMMARY TABLE")
    print("="*80)
    
    comparison_data = []
    for strategy, stats in results.items():
        comparison_data.append({
            'Strategy': strategy.upper(),
            'Final Capital': f"${stats['final_capital']:.2f}",
            'Total PnL': f"{stats['total_pnl_pct']:.2f}%",
            'Win Rate': f"{stats['win_rate']:.2f}%",
            'Profit Factor': f"{stats['profit_factor']:.2f}",
            'Max DD': f"{stats['max_drawdown']:.2f}%",
            'Sharpe': f"{stats['sharpe_ratio']:.2f}",
            'Total Trades': stats['total_trades'],
            'Skipped': stats['skipped_trades']
        })
    
    comparison_df = pd.DataFrame(comparison_data)
    print("\n" + comparison_df.to_string(index=False))
    
    # Save results in dashboard_data.pkl format
    print("\n📦 Creating dashboard_data.pkl for sequential trading...")
    save_sequential_dashboard_data(results, config)
    
    # Save CSV for quick view
    comparison_df.to_csv("sequential_comparison.csv", index=False)
    print(f"✅ Comparison saved to sequential_comparison.csv")
    
    # Save detailed trades for each strategy
    for strategy, stats in results.items():
        filename = f"sequential_{strategy}_trades.csv"
        stats['trades_df'].to_csv(filename, index=False)
        print(f"✅ Detailed trades for {strategy}: {filename}")
    
    # Create comparison chart
    print("\n📊 Creating comparison charts...")
    fig = create_comparison_chart(results)
    fig.write_html("sequential_comparison.html")
    print("✅ Charts saved to sequential_comparison.html")
    
    return results


def save_sequential_dashboard_data(results: Dict, config: SimulatorConfig):
    """Save results in dashboard_data.pkl format for viewing in dashboard"""
    # Structure similar to inspector.py
    dashboard_data = {
        "best_strategy": {
            "type": "sequential_portfolio",
            "config": {
                "initial_capital": config.initial_capital,
                "max_positions": config.max_concurrent_positions,
                "risk_pct": config.base_risk_pct,
                "leverage": config.leverage,
                "adaptive_risk": config.adaptive_risk_enabled
            }
        },
        "assets_data": {},
        "all_strategies": {}
    }
    
    # Collect data by assets
    all_assets = set()
    for strategy_name, stats in results.items():
        trades_df = stats['trades_df']
        for asset in trades_df['asset'].unique():
            all_assets.add(asset)
    
    # Create structure for each asset
    for asset_name in all_assets:
        asset_data = {
            "df": pd.DataFrame(),  # Empty DataFrame as we already have trades
        }
        
        # Add results of each strategy
        for strategy_name, stats in results.items():
            trades_df = stats['trades_df']
            asset_trades = trades_df[trades_df['asset'] == asset_name]
            
            if len(asset_trades) == 0:
                continue
            
            # Convert to format similar to inspector.py
            trades_list = []
            for _, trade in asset_trades.iterrows():
                trades_list.append({
                    'entry_time': trade['entry_time'],
                    'exit_time': trade['exit_time'],
                    'entry_price': trade['entry_price'],
                    'exit_price': trade['exit_price'],
                    'pnl_pct': trade['pnl_pct'],
                    'position_size': trade['position_size'],
                    'pnl_amount': trade['pnl_amount']
                })
            
            # Calculate KPIs for asset
            total_pnl = asset_trades['pnl_amount'].sum()
            wins = asset_trades[asset_trades['pnl_amount'] > 0]
            win_rate = (len(wins) / len(asset_trades) * 100) if len(asset_trades) > 0 else 0
            
            asset_data[strategy_name] = {
                "trades": trades_list,
                "kpis": {
                    "total_pnl": total_pnl,
                    "total_pnl_pct": (total_pnl / config.initial_capital * 100),
                    "total_trades": len(asset_trades),
                    "win_rate": win_rate,
                    "avg_pnl_pct": asset_trades['pnl_pct'].mean()
                }
            }
        
        dashboard_data["assets_data"][asset_name] = asset_data
    
    # Summary statistics by strategies
    for strategy_name, stats in results.items():
        dashboard_data["all_strategies"][strategy_name] = {
            "name": strategy_name.upper(),
            "pnl": stats['total_pnl_pct'],
            "trades": stats['total_trades'],
            "wr": stats['win_rate'],
            "avg_pnl": stats['total_pnl'] / stats['total_trades'] if stats['total_trades'] > 0 else 0,
            "assets": len(all_assets),
            "final_capital": stats['final_capital'],
            "max_drawdown": stats['max_drawdown'],
            "sharpe_ratio": stats['sharpe_ratio'],
            "profit_factor": stats['profit_factor']
        }
    
    # Save
    with open("sequential_dashboard_data.pkl", "wb") as f:
        pickle.dump(dashboard_data, f)
    
    print("✅ Data saved to sequential_dashboard_data.pkl")
    print("   Use: python dashboard.py to view")


def create_comparison_chart(results: Dict):
    """Create comparison chart for all strategies"""
    
    # 3x2 grid setup
    fig = make_subplots(
        rows=3, cols=2,
        subplot_titles=(
            'Equity Curves (Capital Growth)', 
            'Drawdown Comparison', 
            'Final Capital (Total Result)', 
            'Risk Metrics (Sharpe Ratio)',
            'Pain Metrics (Max Consecutive Losses)',
            'Win Rate Comparison'
        ),
        specs=[[{"secondary_y": False}, {"secondary_y": False}],
               [{"type": "bar"}, {"type": "bar"}],
               [{"type": "bar"}, {"type": "bar"}]],
        vertical_spacing=0.1,
        horizontal_spacing=0.1
    )
    
    # --- COLOR SETUP ---
    colors = {
        'base': '#00CCFF',             # Cyan
        'oracle_no_exit': '#00FF7F',   # SpringGreen
        'oracle_exit_5min': '#FFD700', # Gold
        'oracle_breakeven': '#FF69B4'  # HotPink
    }
    default_color = '#CCCCCC'
    
    # 1. Equity Curves
    for strategy, stats in results.items():
        color = colors.get(strategy, default_color)
        eq_df = stats['equity_curve']
        fig.add_trace(
            go.Scatter(
                x=eq_df['time'],
                y=eq_df['capital'],
                name=strategy.upper(),
                line=dict(color=color, width=2),
                legendgroup=strategy
            ),
            row=1, col=1
        )
    
    # 2. Drawdown
    for strategy, stats in results.items():
        color = colors.get(strategy, default_color)
        eq_df = stats['equity_curve']
        fig.add_trace(
            go.Scatter(
                x=eq_df['time'],
                y=eq_df['drawdown'],
                name=f"{strategy.upper()} DD",
                line=dict(color=color, width=1),
                legendgroup=strategy,
                showlegend=False
            ),
            row=1, col=2
        )
    
    # Prepare data for bar charts
    strategies_list = list(results.keys())
    display_names = [s.upper().replace('_', ' ') for s in strategies_list]
    bar_colors = [colors.get(s, default_color) for s in strategies_list]
    
    # 3. Final Capital
    final_capitals = [results[s]['final_capital'] for s in strategies_list]
    fig.add_trace(
        go.Bar(
            x=display_names,
            y=final_capitals,
            marker=dict(color=bar_colors),
            showlegend=False,
            text=[f"${v:.0f}" for v in final_capitals],
            textposition='auto'
        ),
        row=2, col=1
    )
    
    # 4. Sharpe Ratio
    sharpe_ratios = [results[s]['sharpe_ratio'] for s in strategies_list]
    fig.add_trace(
        go.Bar(
            x=display_names,
            y=sharpe_ratios,
            marker=dict(color=bar_colors),
            showlegend=False,
            text=[f"{v:.2f}" for v in sharpe_ratios],
            textposition='auto'
        ),
        row=2, col=2
    )

    # 5. Max Consecutive Losses
    max_losses = [results[s]['max_loss_streak'] for s in strategies_list]
    fig.add_trace(
        go.Bar(
            x=display_names,
            y=max_losses,
            marker=dict(color=bar_colors),
            showlegend=False,
            text=max_losses,
            textposition='auto'
        ),
        row=3, col=1
    )

    # 6. Win Rate
    win_rates = [results[s]['win_rate'] for s in strategies_list]
    fig.add_trace(
        go.Bar(
            x=display_names,
            y=win_rates,
            marker=dict(color=bar_colors),
            showlegend=False,
            text=[f"{v:.1f}%" for v in win_rates],
            textposition='auto'
        ),
        row=3, col=2
    )
    
    # Update Layout
    fig.update_layout(
        height=1200,
        template='plotly_dark',
        title_text="<b>Strategy Comparison - Sequential Portfolio Trading (Corrected Risk)</b>",
        title_font_size=20,
        showlegend=True,
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="right",
            x=1
        )
    )
    
    # Axis titles
    fig.update_yaxes(title_text="Capital ($)", row=1, col=1)
    fig.update_yaxes(title_text="Drawdown (%)", row=1, col=2)
    fig.update_yaxes(title_text="Final Capital ($)", row=2, col=1)
    fig.update_yaxes(title_text="Sharpe Ratio", row=2, col=2)
    fig.update_yaxes(title_text="Consecutive Losses (Count)", row=3, col=1)
    fig.update_yaxes(title_text="Win Rate (%)", row=3, col=2)
    
    return fig


def main():
    """Main function"""
    # Configuration
    config = SimulatorConfig(
        initial_capital=100.0,
        max_concurrent_positions=10,
        base_risk_pct=1.0,  # 1% risk per trade
        leverage=10.0,  # 10x leverage for entire portfolio
        adaptive_risk_enabled=False,
        rolling_window_size=10,
        min_trades_for_assessment=5,
        pnl_threshold_pct=-10.0,
        win_rate_threshold_pct=20.0,
        max_consecutive_losses=10,
        recovery_consecutive_wins=1,
        recovery_pnl_threshold_pct=10.0,
        cooldown_seconds=3600,
        emergency_brake_dd_pct=50.0,
        emergency_max_risk_pct=0.5
    )
    
    # Create simulator
    simulator = SequentialPortfolioSimulator(config)
    
    # Load trades
    print("📂 Loading trades from dashboard_data.pkl...")
    trades_df = simulator.load_trades_from_pickle()
    print(f"✓ Loaded {len(trades_df)} trades\n")
    
    # Run simulation
    stats = simulator.simulate(trades_df)
    
    # Print statistics
    print_statistics(stats)
    
    # Visualization
    print("\n📊 Creating charts...")
    fig = plot_results(stats, config)
    fig.write_html("sequential_simulation_results.html")
    print("✓ Charts saved to sequential_simulation_results.html")
    
    # Save detailed results
    stats['trades_df'].to_csv("sequential_simulation_trades.csv", index=False)
    print("✓ Detailed trades saved to sequential_simulation_trades.csv")
    
    print("\n✅ Simulation completed!")


def run_simulation_interface(assets_data: Dict, source_strategy_name: str, config_dict: Dict) -> Optional[Dict]:
    """
    Adapter for running simulation from dashboard.
    
    Args:
        assets_data: assets_data dictionary from dashboard_data.pkl
        source_strategy_name: source strategy name ('base', 'oracle_no_exit', etc.)
        config_dict: dictionary with configuration parameters
        
    Returns:
        dictionary with results compatible with dashboard_data['all_strategies'][name]
        plus additional data for plotting.
    """
    # 1. Create config
    config = SimulatorConfig(
        initial_capital=config_dict.get('initial_capital', 100.0),
        max_concurrent_positions=config_dict.get('max_concurrent_positions', 5),
        base_risk_pct=config_dict.get('base_risk_pct', 1.0),
        leverage=config_dict.get('leverage', 1.0),
        adaptive_risk_enabled=config_dict.get('adaptive_risk_enabled', False),
        rolling_window_size=config_dict.get('rolling_window_size', 10),
        min_trades_for_assessment=config_dict.get('min_trades_for_assessment', 5),
        pnl_threshold_pct=config_dict.get('pnl_threshold_pct', -10.0),
        win_rate_threshold_pct=config_dict.get('win_rate_threshold_pct', 20.0),
        max_consecutive_losses=config_dict.get('max_consecutive_losses', 10),
        recovery_consecutive_wins=config_dict.get('recovery_consecutive_wins', 1),
        recovery_pnl_threshold_pct=config_dict.get('recovery_pnl_threshold_pct', 10.0),
        cooldown_seconds=config_dict.get('cooldown_seconds', 3600),
        emergency_brake_dd_pct=config_dict.get('emergency_brake_dd_pct', 50.0),
        emergency_max_risk_pct=config_dict.get('emergency_max_risk_pct', 0.5)
    )
    
    # 2. Prepare data
    all_trades = []
    data_key = source_strategy_name
    
    for asset_name, asset_data in assets_data.items():
        if data_key not in asset_data:
            continue
        trades = asset_data[data_key].get("trades", [])
        for trade in trades:
            trade_copy = trade.copy()
            trade_copy['asset'] = asset_name
            trade_copy['strategy'] = source_strategy_name
            
            # Time conversion
            if isinstance(trade_copy['entry_time'], str):
                trade_copy['entry_time'] = pd.to_datetime(trade_copy['entry_time'])
            if isinstance(trade_copy['exit_time'], str):
                trade_copy['exit_time'] = pd.to_datetime(trade_copy['exit_time'])
            
            # Protection: if volatility field is missing
            if 'volatility' not in trade_copy:
                trade_copy['volatility'] = 0.0
            
            # Protection: if prices are missing
            if 'entry_price' not in trade_copy:
                trade_copy['entry_price'] = 1.0 
            if 'exit_price' not in trade_copy:
                trade_copy['exit_price'] = trade_copy['entry_price'] * (1 + trade_copy.get('pnl_pct', 0.0))
                
            all_trades.append(trade_copy)
            
    if not all_trades: return None
        
    df = pd.DataFrame(all_trades)
    
    # Sorting logic:
    # 1. By entry_time (earliest first)
    # 2. If same time, by higher Volatility (prioritize high-vola assets)
    
    df = df.sort_values(
        by=['entry_time', 'volatility'], 
        ascending=[True, False]
    ).reset_index(drop=True)
    
    # 3. Run simulation
    simulator = SequentialPortfolioSimulator(config)
    stats = simulator.simulate(df)
    
    if not stats:
        return None
        
    # 4. Form result
    summary = {
        "name": f"SIMULATED ({source_strategy_name})",
        "pnl": stats['total_pnl_pct'],
        "wr": stats['win_rate'],
        "pf": stats['profit_factor'],
        "trades": stats['total_trades'],
        "final_capital": stats['final_capital'],
        "max_dd": stats['max_drawdown'],
        "sharpe": stats['sharpe_ratio'],
        "skipped": stats['skipped_trades']
    }
    
    result = {
        "summary": summary,
        "stats": stats,
        "config": config
    }
    
    return result


if __name__ == "__main__":
    import sys
    
    # Check command line arguments
    if len(sys.argv) > 1 and sys.argv[1] == "compare":
        # Strategy comparison mode
        compare_strategies()
    else:
        # Normal mode (base strategy)
        main()
