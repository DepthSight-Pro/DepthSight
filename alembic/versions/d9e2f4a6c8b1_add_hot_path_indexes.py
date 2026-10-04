"""add_hot_path_indexes (B6)

Revision ID: d9e2f4a6c8b1
Revises: 3c4d5e6f7a8b
Create Date: 2026-09-30 00:00:00.000000

Composite indexes for the hot read paths. Single-column indexes that already
exist are left alone; a plain ASC btree serves ORDER BY ... DESC via backward
scan, so no DESC-specific indexes are needed.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "d9e2f4a6c8b1"
down_revision: Union[str, Sequence[str], None] = "3c4d5e6f7a8b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # GET /trades: COUNT(subquery) + ORDER BY timestamp_close DESC per user.
    op.create_index(
        "ix_trades_user_id_timestamp_close",
        "trades",
        ["user_id", "timestamp_close"],
    )
    # Live-analytics filters on (user, source_type).
    op.create_index(
        "ix_trade_analytics_user_source_ts",
        "trade_analytics",
        ["user_id", "source_type", "timestamp_close"],
    )
    # Hub/mining verification sweeps.
    op.create_index(
        "ix_hub_reports_verify_epoch_created",
        "hub_telemetry_reports",
        ["verification_status", "epoch_date", "created_at"],
    )
    op.create_index(
        "ix_hub_reports_node_created",
        "hub_telemetry_reports",
        ["node_uuid", "created_at"],
    )
    # Mining-eligibility scans touch only the eligible subset.
    op.create_index(
        "ix_hub_reports_mining_eligible",
        "hub_telemetry_reports",
        ["node_uuid", "created_at"],
        postgresql_where=sa.text("is_mining_eligible"),
    )
    # Phantom/BE analysis filters on (user, be_trigger_time).
    op.create_index(
        "ix_phantom_user_be_time",
        "phantom_trades",
        ["user_id", "be_trigger_time"],
    )


def downgrade() -> None:
    op.drop_index("ix_phantom_user_be_time", table_name="phantom_trades")
    op.drop_index("ix_hub_reports_mining_eligible", table_name="hub_telemetry_reports")
    op.drop_index("ix_hub_reports_node_created", table_name="hub_telemetry_reports")
    op.drop_index(
        "ix_hub_reports_verify_epoch_created", table_name="hub_telemetry_reports"
    )
    op.drop_index("ix_trade_analytics_user_source_ts", table_name="trade_analytics")
    op.drop_index("ix_trades_user_id_timestamp_close", table_name="trades")
