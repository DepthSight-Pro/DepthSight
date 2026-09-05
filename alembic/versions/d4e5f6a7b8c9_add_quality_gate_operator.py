"""add_quality_gate_operator

Revision ID: d4e5f6a7b8c9
Revises: a2b3c4d5e6f7
Create Date: 2026-09-04 13:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "d4e5f6a7b8c9"
down_revision: Union[str, Sequence[str], None] = "a2b3c4d5e6f7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "mining_config",
        sa.Column(
            "quality_gate_operator",
            sa.String(length=10),
            server_default="AND",
            nullable=False,
        ),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("mining_config", "quality_gate_operator")
