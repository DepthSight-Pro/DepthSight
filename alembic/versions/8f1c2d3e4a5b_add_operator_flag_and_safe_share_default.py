"""add_operator_flag_and_safe_share_default

Revision ID: 8f1c2d3e4a5b
Revises: 3b59a8c1f902
Create Date: 2026-08-01 15:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "8f1c2d3e4a5b"
down_revision: Union[str, Sequence[str], None] = "3b59a8c1f902"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # P.9: Explicitly mark the operator (admin) node instead of picking the first row.
    op.add_column(
        "hub_nodes",
        sa.Column("is_operator", sa.Boolean(), server_default="false", nullable=False),
    )
    # P.8: Safe default for the user reward share (0.0 previously meant 100% operator fee).
    op.execute(
        "UPDATE node_mining_config SET user_reward_share_percent = 75.0 "
        "WHERE user_reward_share_percent IS NULL OR user_reward_share_percent <= 0.0"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("hub_nodes", "is_operator")
