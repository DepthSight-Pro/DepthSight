"""add_min_price_movement_percent

Revision ID: e8f3b7d2c9a4
Revises: d1f5a9e3b8c2
Create Date: 2026-08-23 00:30:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "e8f3b7d2c9a4"
down_revision: Union[str, Sequence[str], None] = "d1f5a9e3b8c2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Anti-instant-exit gate: minimum |exit-entry|/entry movement (%) required
    # for a trade to mine; enforced at submission and re-checked by the broker
    # verifier against real exchange prices.
    op.add_column(
        "mining_config",
        sa.Column(
            "min_price_movement_percent",
            sa.Float(),
            nullable=False,
            server_default="0.15",
        ),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("mining_config", "min_price_movement_percent")
