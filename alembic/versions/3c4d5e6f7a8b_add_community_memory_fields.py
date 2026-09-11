"""add_community_memory_fields

Revision ID: 3c4d5e6f7a8b
Revises: f1a2b3c4d5e6
Create Date: 2026-09-10 14:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "3c4d5e6f7a8b"
down_revision: Union[str, Sequence[str], None] = "f1a2b3c4d5e6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = inspector.get_table_names()

    # 1. Update users table if present
    if "users" in tables:
        user_cols = [c["name"] for c in inspector.get_columns("users")]
        if "share_community_memories" not in user_cols:
            op.add_column(
                "users",
                sa.Column(
                    "share_community_memories",
                    sa.Boolean(),
                    nullable=False,
                    server_default="false",
                ),
            )

    # 2. Update agent_memories table if present
    if "agent_memories" in tables:
        mem_cols = [c["name"] for c in inspector.get_columns("agent_memories")]
        if "visibility" not in mem_cols:
            op.add_column(
                "agent_memories",
                sa.Column(
                    "visibility",
                    sa.String(length=20),
                    nullable=False,
                    server_default="private",
                ),
            )
            op.create_index(
                "ix_agent_memories_visibility",
                "agent_memories",
                ["visibility"],
            )
            op.create_index(
                "ix_agent_memories_visibility_symbol",
                "agent_memories",
                ["visibility", "symbol"],
            )

        if "source_node_uuid" not in mem_cols:
            op.add_column(
                "agent_memories",
                sa.Column(
                    "source_node_uuid",
                    sa.String(length=36),
                    nullable=True,
                ),
            )

        if "author_user_id" not in mem_cols:
            op.add_column(
                "agent_memories",
                sa.Column(
                    "author_user_id",
                    sa.Integer(),
                    nullable=True,
                ),
            )

        if "community_confirmations" not in mem_cols:
            op.add_column(
                "agent_memories",
                sa.Column(
                    "community_confirmations",
                    sa.Integer(),
                    nullable=False,
                    server_default="0",
                ),
            )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = inspector.get_table_names()

    if "agent_memories" in tables:
        mem_cols = [c["name"] for c in inspector.get_columns("agent_memories")]
        if "visibility" in mem_cols:
            op.drop_index(
                "ix_agent_memories_visibility_symbol", table_name="agent_memories"
            )
            op.drop_index("ix_agent_memories_visibility", table_name="agent_memories")
            op.drop_column("agent_memories", "visibility")
        if "source_node_uuid" in mem_cols:
            op.drop_column("agent_memories", "source_node_uuid")
        if "author_user_id" in mem_cols:
            op.drop_column("agent_memories", "author_user_id")
        if "community_confirmations" in mem_cols:
            op.drop_column("agent_memories", "community_confirmations")

    if "users" in tables:
        user_cols = [c["name"] for c in inspector.get_columns("users")]
        if "share_community_memories" in user_cols:
            op.drop_column("users", "share_community_memories")
