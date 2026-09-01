"""add_used_ownership_messages

Revision ID: c9d4e8f2a7b6
Revises: 8f1c2d3e4a5b
Create Date: 2026-08-22 20:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "c9d4e8f2a7b6"
down_revision: Union[str, Sequence[str], None] = "8f1c2d3e4a5b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Replay protection for wallet ownership signatures: each consumed message
    # hash is recorded once; resubmission of the same signed message is rejected.
    op.create_table(
        "used_ownership_messages",
        sa.Column("message_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.BigInteger(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("message_hash"),
    )
    op.create_index(
        op.f("ix_used_ownership_messages_expires_at"),
        "used_ownership_messages",
        ["expires_at"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        op.f("ix_used_ownership_messages_expires_at"),
        table_name="used_ownership_messages",
    )
    op.drop_table("used_ownership_messages")
