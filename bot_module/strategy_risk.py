from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional


_FIXED_USD_RISK_TYPES = frozenset(
    {
        "fixed_usd",
        "fixed_usdt",
        "fixed_quote",
        "fixed_quote_currency",
    }
)

_PERCENT_BALANCE_RISK_TYPES = frozenset(
    {
        "percent_balance",
        "percent_of_balance",
        "balance_percent",
        "percent",
    }
)


@dataclass(frozen=True)
class StrategyRiskOverride:
    risk_pct: Optional[float] = None
    risk_usd: Optional[float] = None

    @property
    def is_explicit(self) -> bool:
        return self.risk_pct is not None or self.risk_usd is not None


def normalize_strategy_risk_type(raw_risk_type: Any) -> str:
    if raw_risk_type is None:
        return "percent_balance"

    normalized = str(raw_risk_type).strip().lower()
    return normalized or "percent_balance"


def resolve_strategy_risk_override(
    raw_risk_type: Any,
    risk_value: Optional[float],
) -> StrategyRiskOverride:
    if risk_value is None:
        return StrategyRiskOverride()

    numeric_risk_value = max(float(risk_value), 0.0)
    risk_type = normalize_strategy_risk_type(raw_risk_type)

    if risk_type in _FIXED_USD_RISK_TYPES:
        return StrategyRiskOverride(risk_usd=numeric_risk_value)

    if risk_type in _PERCENT_BALANCE_RISK_TYPES:
        return StrategyRiskOverride(risk_pct=numeric_risk_value / 100.0)

    return StrategyRiskOverride()
