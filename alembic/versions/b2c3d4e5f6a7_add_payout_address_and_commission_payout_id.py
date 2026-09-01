"""add_payout_address_and_commission_payout_id

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-08-24 22:10:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "b2c3d4e5f6a7"
down_revision: Union[str, Sequence[str], None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("users", sa.Column("payout_address", sa.String(), nullable=True))
    op.add_column("commissions", sa.Column("payout_id", sa.String(), nullable=True))
    op.create_index(
        op.f("ix_commissions_payout_id"), "commissions", ["payout_id"], unique=False
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_commissions_payout_id"), table_name="commissions")
    op.drop_column("commissions", "payout_id")
    op.drop_column("users", "payout_address")
