from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator


class SymbolSelectionConfig(BaseModel):
    mode: Literal["STATIC", "DYNAMIC_NATR", "DYNAMIC_ORACLE"] = "STATIC"
    min_natr: Optional[float] = Field(0.0, ge=0.0, le=10.0)
    oracle_regime: Optional[Literal[0, 1, 2]] = (
        None  # 0: Amnesia, 1: Paranoia, 2: Schizophrenia
    )
    oracle_confidence: Optional[float] = Field(0.0, ge=0.0, le=100.0)
    max_concurrent_symbols: int = Field(1, ge=1)

    @model_validator(mode="after")
    def validate_dynamic_modes(self):
        if self.mode == "DYNAMIC_NATR":
            if self.min_natr is None:
                raise ValueError("min_natr must be provided for DYNAMIC_NATR mode")
        elif self.mode == "DYNAMIC_ORACLE":
            if self.oracle_regime is None:
                raise ValueError(
                    "oracle_regime must be provided for DYNAMIC_ORACLE mode"
                )
            if self.oracle_confidence is None:
                raise ValueError(
                    "oracle_confidence must be provided for DYNAMIC_ORACLE mode"
                )
        return self
