"""add_user_totp_fields

Revision ID: c1d2e3f4a5b6
Revises: b2c3d4e5f6a7
Create Date: 2026-09-02 23:00:00.000000

"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "c1d2e3f4a5b6"
down_revision: Union[str, Sequence[str], None] = "b2c3d4e5f6a7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("users", sa.Column("totp_secret", sa.String(), nullable=True))
    op.add_column(
        "users",
        sa.Column(
            "is_totp_enabled", sa.Boolean(), server_default="false", nullable=False
        ),
    )
    op.add_column("users", sa.Column("totp_backup_codes", sa.JSON(), nullable=True))
    op.add_column(
        "users", sa.Column("totp_last_used_step", sa.Integer(), nullable=True)
    )

    # Seed achievement
    try:
        op.execute(
            sa.text(
                "INSERT INTO achievements (id, name, description, icon, xp_reward, rarity) "
                "VALUES ('two_factor_enabled', 'Security Champion', 'Enable Two-Factor Authentication (2FA)', 'ShieldCheck', 50, 'RARE') "
                "ON CONFLICT (id) DO NOTHING"
            )
        )
    except Exception:
        pass


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("users", "totp_last_used_step")
    op.drop_column("users", "totp_backup_codes")
    op.drop_column("users", "is_totp_enabled")
    op.drop_column("users", "totp_secret")
