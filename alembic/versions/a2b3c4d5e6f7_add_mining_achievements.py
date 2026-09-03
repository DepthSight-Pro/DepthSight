"""add_mining_achievements

Revision ID: a2b3c4d5e6f7
Revises: c1d2e3f4a5b6
Create Date: 2026-09-03 00:00:00.000000

"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "a2b3c4d5e6f7"
down_revision: Union[str, Sequence[str], None] = "c1d2e3f4a5b6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

ACHIEVEMENTS = [
    # Onboarding & Web3
    (
        "mining_activated",
        "Genesis",
        "Activate Trade Mining and accept telemetry sharing",
        "Pickaxe",
        50,
        "COMMON",
    ),
    (
        "mining_wallet_linked",
        "Web3 Citizen",
        "Link and verify an EVM wallet for mining",
        "Wallet",
        50,
        "COMMON",
    ),
    (
        "mining_first_trade",
        "First Spark",
        "Execute first trade successfully verified in the mining pool",
        "Sparkles",
        100,
        "COMMON",
    ),
    (
        "welcome_bonus_claimed",
        "Golden Ticket",
        "Generate $1.0 rebate and claim Welcome Bonus (1,000 $DEPTH)",
        "Ticket",
        250,
        "RARE",
    ),
    # Volume Milestones
    (
        "mining_volume_1k",
        "Tunnel Miner",
        "Reach $1,000 in cumulative trading volume",
        "CircleDollarSign",
        50,
        "COMMON",
    ),
    (
        "mining_volume_10k",
        "Mining Foreman",
        "Reach $10,000 in cumulative trading volume",
        "Coins",
        150,
        "COMMON",
    ),
    (
        "mining_volume_100k",
        "Quarry Titan",
        "Reach $100,000 in cumulative trading volume",
        "TrendingUp",
        500,
        "RARE",
    ),
    (
        "mining_volume_1m",
        "Crypto Whale",
        "Reach $1,000,000 in cumulative trading volume",
        "Fish",
        1500,
        "EPIC",
    ),
    (
        "mining_volume_10m",
        "Market Maker",
        "Reach $10,000,000 in cumulative trading volume",
        "Crown",
        5000,
        "LEGENDARY",
    ),
    # Daily Highs
    (
        "mining_daily_volume_10k",
        "Stakhanovite",
        "Generate $10,000 volume in a single 24-hour epoch",
        "Activity",
        200,
        "RARE",
    ),
    (
        "mining_daily_volume_100k",
        "Market Tempest",
        "Generate $100,000 volume in a single 24-hour epoch",
        "CloudLightning",
        750,
        "EPIC",
    ),
    (
        "mining_daily_top_miner",
        "King of the Hill",
        "Rank #1 in volume across all nodes in a daily epoch",
        "Trophy",
        2000,
        "LEGENDARY",
    ),
    (
        "mining_daily_top5_miner",
        "Major League",
        "Finish in the top 5 daily volume miners",
        "Medal",
        500,
        "EPIC",
    ),
    # Referrals & Social
    (
        "mining_first_referral",
        "Network Partner",
        "Invite your first user who activates mining",
        "UserPlus",
        100,
        "COMMON",
    ),
    (
        "mining_5_referrals",
        "Squad Leader",
        "Invite 5 active miners",
        "Users",
        300,
        "RARE",
    ),
    (
        "mining_10_referrals",
        "Mining Brigade",
        "Invite 10 active miners",
        "Network",
        750,
        "EPIC",
    ),
    (
        "mining_50_referrals",
        "Mining Syndicate",
        "Build a network of 50 active nodes",
        "Building",
        2500,
        "LEGENDARY",
    ),
    (
        "mining_active_squad",
        "All Hands On Deck",
        "Have 5+ referrals mining simultaneously on the same day",
        "Radio",
        500,
        "EPIC",
    ),
    (
        "mining_mentor_bonus",
        "Mentor",
        "Your referral claimed their Welcome Bonus",
        "GraduationCap",
        250,
        "RARE",
    ),
    (
        "mining_ref_volume_100k",
        "Network Megaphone",
        "Referral network combined volume exceeded $100,000",
        "Share2",
        1000,
        "EPIC",
    ),
    (
        "mining_ref_earnings_100k",
        "Passive Income",
        "Earn 100,000 $DEPTH purely from 10% referral bonuses",
        "Gem",
        3000,
        "LEGENDARY",
    ),
    # Streaks & Consistency
    (
        "mining_streak_7d",
        "Weekly Marathon",
        "Participate in mining emission for 7 consecutive epochs",
        "Flame",
        350,
        "RARE",
    ),
    (
        "mining_streak_30d",
        "Iron Discipline",
        "Unbroken mining streak for 30 consecutive epochs",
        "Shield",
        1500,
        "EPIC",
    ),
    (
        "mining_epochs_100",
        "Network Veteran",
        "Participate in 100 daily epochs in total",
        "Award",
        3000,
        "LEGENDARY",
    ),
    (
        "mining_halving_survivor",
        "Halving Survivor",
        "Be an active miner during an emission halving event",
        "Hourglass",
        2500,
        "LEGENDARY",
    ),
    # Token Milestones
    (
        "mining_depth_1k",
        "First Thousand",
        "Mine a cumulative total of 1,000 $DEPTH",
        "Coins",
        100,
        "COMMON",
    ),
    (
        "mining_depth_10k",
        "Gold Reserve",
        "Mine a cumulative total of 10,000 $DEPTH",
        "Boxes",
        500,
        "RARE",
    ),
    (
        "mining_depth_100k",
        "Crypto Tycoon",
        "Mine a cumulative total of 100,000 $DEPTH",
        "Crown",
        3000,
        "LEGENDARY",
    ),
    (
        "mining_jackpot_epoch",
        "Hit the Jackpot",
        "Receive over 5,000 $DEPTH in a single daily epoch",
        "Zap",
        1000,
        "EPIC",
    ),
    # Execution & Telemetry
    (
        "mining_flawless_telemetry",
        "Flawless Stream",
        "50 consecutive trades without a single verification rejection",
        "CheckCircle2",
        300,
        "RARE",
    ),
    (
        "mining_high_speed_turnover",
        "High Frequency",
        "Execute 50+ verified trades in a single trading day",
        "Gauge",
        250,
        "RARE",
    ),
    (
        "mining_profitable",
        "In the Green",
        "10 consecutive closed mining trades with positive PnL",
        "TrendingUp",
        250,
        "RARE",
    ),
    # Multi-exchange & Infra
    (
        "mining_multi_exchange",
        "Arbitrageur",
        "Mine trades on 2+ different exchanges within one week",
        "Shuffle",
        300,
        "RARE",
    ),
    (
        "mining_all_exchanges",
        "Omnipresent",
        "Link UIDs and mine trades on all supported exchanges",
        "Globe",
        750,
        "EPIC",
    ),
    (
        "mining_node_operator",
        "Private Datacenter",
        "Operate a mining server node hosting other miners",
        "Server",
        2000,
        "LEGENDARY",
    ),
    # Staking & Boosters
    (
        "mining_boost_active",
        "Afterburner",
        "Activate any mining boost multiplier",
        "Rocket",
        150,
        "COMMON",
    ),
    (
        "mining_diamond_staker",
        "Diamond Staker",
        "Lock $DEPTH for 360 days to unlock the maximum 2.0x multiplier",
        "HandHeart",
        2500,
        "LEGENDARY",
    ),
]


def upgrade() -> None:
    """Seed mining achievements."""
    for ach_id, name, desc, icon, xp, rarity in ACHIEVEMENTS:
        try:
            op.execute(
                sa.text(
                    "INSERT INTO achievements (id, name, description, icon, xp_reward, rarity) "
                    f"VALUES ('{ach_id}', :name, :desc, '{icon}', {xp}, '{rarity}') "
                    "ON CONFLICT (id) DO UPDATE SET "
                    "name = EXCLUDED.name, "
                    "description = EXCLUDED.description, "
                    "icon = EXCLUDED.icon, "
                    "xp_reward = EXCLUDED.xp_reward, "
                    "rarity = EXCLUDED.rarity"
                ).bindparams(name=name, desc=desc)
            )
        except Exception:
            pass


def downgrade() -> None:
    """Remove seeded mining achievements."""
    ach_ids = "', '".join([a[0] for a in ACHIEVEMENTS])
    try:
        op.execute(sa.text(f"DELETE FROM achievements WHERE id IN ('{ach_ids}')"))
    except Exception:
        pass
