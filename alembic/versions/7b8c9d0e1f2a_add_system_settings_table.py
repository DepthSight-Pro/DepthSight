"""add_system_settings_table

Revision ID: 7b8c9d0e1f2a
Revises: e8f3b7d2c9a4
Create Date: 2026-08-24 17:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "7b8c9d0e1f2a"
down_revision: Union[str, Sequence[str], None] = "e8f3b7d2c9a4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "system_settings",
        sa.Column("key", sa.String(length=100), nullable=False),
        sa.Column("value", sa.JSON(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.Column("updated_by_user_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ["updated_by_user_id"],
            ["users.id"],
            name=op.f("fk_system_settings_updated_by_user_id_users"),
        ),
        sa.PrimaryKeyConstraint("key", name=op.f("pk_system_settings")),
    )
    op.create_index(
        op.f("ix_system_settings_key"),
        "system_settings",
        ["key"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_system_settings_key"), table_name="system_settings")
    op.drop_table("system_settings")
