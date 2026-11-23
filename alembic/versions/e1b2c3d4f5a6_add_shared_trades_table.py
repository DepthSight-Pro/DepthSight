"""add_shared_trades_table

Revision ID: e1b2c3d4f5a6
Revises: d9e2f4a6c8b1
Create Date: 2026-11-22 14:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "e1b2c3d4f5a6"
down_revision: Union[str, Sequence[str], None] = "d9e2f4a6c8b1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "shared_trades",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("trade_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("public_slug", sa.String(), nullable=False),
        sa.Column("pnl_display_mode", sa.String(length=20), server_default="PERCENT", nullable=False),
        sa.Column("is_strategy_name_public", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("is_quantity_public", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("is_prices_public", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.ForeignKeyConstraint(["trade_id"], ["trades.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_shared_trades_public_slug"), "shared_trades", ["public_slug"], unique=True)
    op.create_index(op.f("ix_shared_trades_trade_id"), "shared_trades", ["trade_id"], unique=False)
    op.create_index(op.f("ix_shared_trades_user_id"), "shared_trades", ["user_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_shared_trades_user_id"), table_name="shared_trades")
    op.drop_index(op.f("ix_shared_trades_trade_id"), table_name="shared_trades")
    op.drop_index(op.f("ix_shared_trades_public_slug"), table_name="shared_trades")
    op.drop_table("shared_trades")
