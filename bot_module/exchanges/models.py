from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class SymbolFilters:
    tick_size: Optional[float] = None
    min_qty: Optional[float] = None
    max_qty: Optional[float] = None
    step_size: Optional[float] = None
    min_notional: Optional[float] = None
    raw: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class BalanceSnapshot:
    asset: str
    free: float
    locked: float = 0.0
    unrealized_pnl: float = 0.0
    raw: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PositionSnapshot:
    symbol: str
    side: str
    quantity: float
    entry_price: Optional[float] = None
    unrealized_pnl: float = 0.0
    raw: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class OrderRequest:
    symbol: str
    side: str
    order_type: str
    quantity: Optional[float] = None
    price: Optional[float] = None
    reduce_only: bool = False
    client_order_id: Optional[str] = None
    extra: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class OrderResult:
    accepted: bool
    order_id: Optional[str] = None
    client_order_id: Optional[str] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    raw: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class OrderBookSnapshot:
    symbol: str
    bids: List[List[float]]
    asks: List[List[float]]
    timestamp_ms: Optional[int] = None
    raw: Dict[str, Any] = field(default_factory=dict)
