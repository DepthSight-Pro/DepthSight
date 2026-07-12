"""add_memory_tags

Revision ID: 2a487db2c451
Revises: 114355827cb0
Create Date: 2026-07-10 14:30:00.000000

"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "2a487db2c451"
down_revision: Union[str, Sequence[str], None] = "114355827cb0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add new columns to agent_memories table
    op.add_column(
        "agent_memories",
        sa.Column("tags", sa.JSON(), nullable=True, server_default="[]"),
    )
    op.add_column(
        "agent_memories", sa.Column("symbol", sa.String(length=20), nullable=True)
    )
    op.add_column(
        "agent_memories",
        sa.Column("strategy_type", sa.String(length=50), nullable=True),
    )
    op.add_column(
        "agent_memories", sa.Column("outcome", sa.String(length=20), nullable=True)
    )
    op.add_column(
        "agent_memories",
        sa.Column("confidence", sa.Float(), nullable=True, server_default="1.0"),
    )
    op.add_column(
        "agent_memories",
        sa.Column("validated_count", sa.Integer(), nullable=True, server_default="1"),
    )
    op.add_column(
        "agent_memories", sa.Column("config_hash", sa.String(length=64), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("agent_memories", "config_hash")
    op.drop_column("agent_memories", "validated_count")
    op.drop_column("agent_memories", "confidence")
    op.drop_column("agent_memories", "outcome")
    op.drop_column("agent_memories", "strategy_type")
    op.drop_column("agent_memories", "symbol")
    op.drop_column("agent_memories", "tags")
