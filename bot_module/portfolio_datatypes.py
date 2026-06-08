# bot_module/portfolio_datatypes.py
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Dict, Any

# Import only base types that do not create cycles
from .strategy import SignalDirection


@dataclass
class BacktestPositionState:
    """Stores the state of an active position in the portfolio backtester."""

    position_id: str
    contract_id: str
    symbol: str
    direction: SignalDirection
    entry_price: float
    quantity: float
    entry_time: datetime
    current_sl: Optional[float] = None
    current_tp: Optional[float] = None
    initial_value_usd: float = 0.0
    last_update_time: Optional[datetime] = None
    pnl_realized: float = 0.0
    entry_commission_paid: float = 0.0
    l2_entry_details: Optional[Dict[str, Any]] = field(default_factory=dict)
