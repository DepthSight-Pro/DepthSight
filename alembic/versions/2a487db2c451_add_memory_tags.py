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
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = inspector.get_table_names()

    if "agent_memories" not in tables:
        op.create_table(
            "agent_memories",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column(
                "user_id",
                sa.Integer(),
                sa.ForeignKey("users.id"),
                nullable=False,
                index=True,
            ),
            sa.Column("memory_type", sa.String(length=50), nullable=False),
            sa.Column("content", sa.Text(), nullable=False),
            sa.Column(
                "relevance_score", sa.Float(), nullable=True, server_default="1.0"
            ),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
            ),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("tags", sa.JSON(), nullable=True, server_default="[]"),
            sa.Column("symbol", sa.String(length=20), nullable=True),
            sa.Column("strategy_type", sa.String(length=50), nullable=True),
            sa.Column("outcome", sa.String(length=20), nullable=True),
            sa.Column("confidence", sa.Float(), nullable=True, server_default="1.0"),
            sa.Column(
                "validated_count", sa.Integer(), nullable=True, server_default="1"
            ),
            sa.Column("config_hash", sa.String(length=64), nullable=True),
        )
    else:
        existing_cols = [c["name"] for c in inspector.get_columns("agent_memories")]
        if "tags" not in existing_cols:
            op.add_column(
                "agent_memories",
                sa.Column("tags", sa.JSON(), nullable=True, server_default="[]"),
            )
        if "symbol" not in existing_cols:
            op.add_column(
                "agent_memories",
                sa.Column("symbol", sa.String(length=20), nullable=True),
            )
        if "strategy_type" not in existing_cols:
            op.add_column(
                "agent_memories",
                sa.Column("strategy_type", sa.String(length=50), nullable=True),
            )
        if "outcome" not in existing_cols:
            op.add_column(
                "agent_memories",
                sa.Column("outcome", sa.String(length=20), nullable=True),
            )
        if "confidence" not in existing_cols:
            op.add_column(
                "agent_memories",
                sa.Column(
                    "confidence", sa.Float(), nullable=True, server_default="1.0"
                ),
            )
        if "validated_count" not in existing_cols:
            op.add_column(
                "agent_memories",
                sa.Column(
                    "validated_count", sa.Integer(), nullable=True, server_default="1"
                ),
            )
        if "config_hash" not in existing_cols:
            op.add_column(
                "agent_memories",
                sa.Column("config_hash", sa.String(length=64), nullable=True),
            )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = inspector.get_table_names()
    if "agent_memories" in tables:
        op.drop_table("agent_memories")
