"""add_public_plans_to_hub_nodes

Revision ID: a1b2c3d4e5f6
Revises: 7b8c9d0e1f2a
Create Date: 2026-08-24 18:55:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, Sequence[str], None] = "7b8c9d0e1f2a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("hub_nodes", sa.Column("public_plans", sa.JSON(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("hub_nodes", "public_plans")
