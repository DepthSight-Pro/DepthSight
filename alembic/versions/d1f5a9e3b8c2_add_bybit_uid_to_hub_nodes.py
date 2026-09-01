"""add_bybit_uid_to_hub_nodes

Revision ID: d1f5a9e3b8c2
Revises: c9d4e8f2a7b6
Create Date: 2026-08-22 21:30:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "d1f5a9e3b8c2"
down_revision: Union[str, Sequence[str], None] = "c9d4e8f2a7b6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Broker-verifier ownership binding: the Bybit account UID of a node's
    # owner. Used to reject reports whose orders belong to another account.
    op.add_column(
        "hub_nodes", sa.Column("bybit_uid", sa.String(length=32), nullable=True)
    )
    op.create_index(
        op.f("ix_hub_nodes_bybit_uid"), "hub_nodes", ["bybit_uid"], unique=False
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_hub_nodes_bybit_uid"), table_name="hub_nodes")
    op.drop_column("hub_nodes", "bybit_uid")
