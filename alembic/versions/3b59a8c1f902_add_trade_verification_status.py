"""add_trade_verification_status

Revision ID: 3b59a8c1f902
Revises: 11dd202c080d
Create Date: 2026-07-23 17:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "3b59a8c1f902"
down_revision: Union[str, Sequence[str], None] = "11dd202c080d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "hub_telemetry_reports",
        sa.Column(
            "verification_status",
            sa.String(length=20),
            server_default="LEGACY",
            nullable=False,
        ),
    )
    op.add_column(
        "hub_telemetry_reports",
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "hub_telemetry_reports",
        sa.Column("verified_volume_usdt", sa.Float(), nullable=True),
    )
    op.add_column(
        "hub_telemetry_reports",
        sa.Column("verification_error", sa.String(length=255), nullable=True),
    )
    op.create_index(
        op.f("ix_hub_telemetry_reports_verification_status"),
        "hub_telemetry_reports",
        ["verification_status"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        op.f("ix_hub_telemetry_reports_verification_status"),
        table_name="hub_telemetry_reports",
    )
    op.drop_column("hub_telemetry_reports", "verification_error")
    op.drop_column("hub_telemetry_reports", "verified_volume_usdt")
    op.drop_column("hub_telemetry_reports", "verified_at")
    op.drop_column("hub_telemetry_reports", "verification_status")
