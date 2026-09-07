"""ensure_free_okx_trading

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-09-06 19:00:00.000000

"""

import json
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "e5f6a7b8c9d0"
down_revision: Union[str, Sequence[str], None] = "d4e5f6a7b8c9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Ensure OKX free trading is enabled in system_settings plans_config."""
    conn = op.get_bind()
    try:
        res = conn.execute(
            sa.text("SELECT value FROM system_settings WHERE key = 'plans_config'")
        )
        row = res.fetchone()
        if row and row[0]:
            val = row[0]
            if isinstance(val, str):
                try:
                    val = json.loads(val)
                except Exception:
                    val = {}
            if isinstance(val, dict) and "plans" in val:
                free_plan = val["plans"].get("free", {})
                limits = free_plan.setdefault("limits", {})
                changed = False
                if limits.get("allow_free_okx_trading") is not True:
                    limits["allow_free_okx_trading"] = True
                    limits.setdefault("max_free_okx_live_strategies", 5)
                    changed = True
                features = free_plan.setdefault("features", [])
                if isinstance(features, list) and not any(
                    "okx" in str(f).lower() for f in features
                ):
                    features.append("5 live strategies on OKX")
                    changed = True
                if changed:
                    conn.execute(
                        sa.text(
                            "UPDATE system_settings SET value = :val WHERE key = 'plans_config'"
                        ).bindparams(sa.bindparam("val", value=val, type_=sa.JSON))
                    )
    except Exception:
        # Table system_settings may not exist in partial runs
        pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
