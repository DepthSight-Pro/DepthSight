# api/crud.py
import uuid
import logging
import math
from datetime import datetime, timezone, date
from typing import Optional, List, Tuple
from sqlalchemy.future import select
from sqlalchemy.orm.attributes import flag_modified
from sqlalchemy.orm import (
    selectinload,
    attributes as orm_attributes,
    with_loader_criteria,
)
from sqlalchemy import desc, func, text, delete, case, distinct, update, or_
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import timedelta
from typing import Dict, Any

from . import models, schemas, security
from .plans import plans_config  # Import plans_config
from bot_module.config import PAPER_TRADING_INITIAL_BALANCE
from bot_module.exchanges import exchange_settings_key


logger = logging.getLogger(__name__)
HIDDEN_BACKTEST_TRADE_EXIT_REASON = "END_OF_DATA"


def _generate_tradingview_webhook_token() -> str:
    return f"tv_{uuid.uuid4().hex}"


def _sanitize_json_payload(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _sanitize_json_payload(item) for key, item in value.items()}

    if isinstance(value, list):
        return [_sanitize_json_payload(item) for item in value]

    if isinstance(value, tuple):
        return [_sanitize_json_payload(item) for item in value]

    if hasattr(value, "item") and callable(getattr(value, "item")):
        try:
            return _sanitize_json_payload(value.item())
        except Exception:
            pass

    if isinstance(value, float):
        return value if math.isfinite(value) else None

    return value


def _visible_backtest_trade_clause():
    return or_(
        models.BacktestTrade.exit_reason.is_(None),
        func.upper(models.BacktestTrade.exit_reason)
        != HIDDEN_BACKTEST_TRADE_EXIT_REASON,
    )


def _visible_backtest_trade_loader_option():
    return with_loader_criteria(
        models.BacktestTrade,
        lambda cls: or_(
            cls.exit_reason.is_(None),
            func.upper(cls.exit_reason) != HIDDEN_BACKTEST_TRADE_EXIT_REASON,
        ),
        include_aliases=True,
    )


# --- User CRUD ---
async def get_user_by_username(
    db: AsyncSession, username: str
) -> Optional[models.User]:
    db_result = await db.execute(
        select(models.User).filter(models.User.username == username)
    )
    return db_result.scalars().first()


async def get_user_by_email(db: AsyncSession, email: str) -> Optional[models.User]:
    db_result = await db.execute(select(models.User).filter(models.User.email == email))
    return db_result.scalars().first()


async def get_user_by_referral_code(
    db: AsyncSession, referral_code: str
) -> Optional[models.User]:
    db_result = await db.execute(
        select(models.User).filter(models.User.referral_code == referral_code)
    )
    return db_result.scalars().first()


async def get_user_by_tradingview_webhook_token(
    db: AsyncSession, token: str
) -> Optional[models.User]:
    db_result = await db.execute(
        select(models.User).filter(models.User.tradingview_webhook_token == token)
    )
    return db_result.scalars().first()


async def update_user_push_subscription(
    db: AsyncSession, user_id: int, subscription: dict
) -> Optional[models.User]:
    """Updates the push_subscription field for a specific user."""
    user = await db.get(models.User, user_id)
    if user:
        user.push_subscription = subscription
        await db.flush()
        await db.refresh(user)
    return user


async def delete_user_push_subscription(
    db: AsyncSession, user_id: int
) -> Optional[models.User]:
    """Deletes the push_subscription for a specific user by setting it to None."""
    user = await db.get(models.User, user_id)
    if user:
        user.push_subscription = None
        await db.flush()
        await db.refresh(user)
    return user


async def get_user_symbol_selection_config(
    db: AsyncSession, user_id: int
) -> Optional[dict]:
    """Retrieves the symbol selection configuration for a specific user."""
    user = await db.get(models.User, user_id)
    if user:
        return user.symbol_selection_config
    return None


async def update_user_symbol_selection_config(
    db: AsyncSession, user_id: int, config_data: dict
) -> models.User:
    """Updates the symbol selection configuration for a specific user."""
    user = await db.get(models.User, user_id)
    if user:
        user.symbol_selection_config = config_data
        flag_modified(
            user, "symbol_selection_config"
        )  # Mark as modified for SQLAlchemy
        await db.flush()
        await db.refresh(user)
        return user
    raise ValueError(f"User with ID {user_id} not found.")


# --- Payment CRUD ---
async def create_payment(
    db: AsyncSession, user_id: int, plan_name: str, amount_usd: float
) -> models.Payment:
    db_payment = models.Payment(
        user_id=user_id, plan_name=plan_name, amount_usd=amount_usd, status="PENDING"
    )
    db.add(db_payment)
    return db_payment


async def update_payment_with_bitcart_id(
    db: AsyncSession, payment_id: str, bitcart_id: str
) -> Optional[models.Payment]:
    result = await db.execute(
        select(models.Payment).filter(models.Payment.id == payment_id)
    )
    db_payment = result.scalars().first()
    if db_payment:
        db_payment.bitcart_id = bitcart_id
        await db.flush()
    return db_payment


async def update_payment_status(
    db: AsyncSession, payment_id: str, status: str
) -> Optional[models.Payment]:
    result = await db.execute(
        select(models.Payment).filter(models.Payment.id == payment_id)
    )
    db_payment = result.scalars().first()
    if db_payment:
        db_payment.status = status
        await db.flush()
    return db_payment


async def get_payment_by_id(
    db: AsyncSession, payment_id: str
) -> Optional[models.Payment]:
    result = await db.execute(
        select(models.Payment).filter(models.Payment.id == payment_id)
    )
    return result.scalars().first()


async def get_payment_by_bitcart_id(
    db: AsyncSession, bitcart_id: str
) -> Optional[models.Payment]:
    result = await db.execute(
        select(models.Payment).filter(models.Payment.bitcart_id == bitcart_id)
    )
    return result.scalars().first()


async def get_lifetime_payment_slot_counts(
    db: AsyncSession,
    plan_name: str,
    amount_usd: float,
    reservation_ttl_seconds: int,
) -> Dict[str, int]:
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=reservation_ttl_seconds)
    amount = float(amount_usd)

    used_result = await db.execute(
        select(func.count(models.Payment.id)).filter(
            models.Payment.plan_name == plan_name,
            models.Payment.amount_usd == amount,
            models.Payment.status.in_(["FINISHED", "COMPLETED"]),
        )
    )
    reserved_result = await db.execute(
        select(func.count(models.Payment.id)).filter(
            models.Payment.plan_name == plan_name,
            models.Payment.amount_usd == amount,
            models.Payment.status == "PENDING",
            models.Payment.created_at >= cutoff,
        )
    )

    return {
        "used": int(used_result.scalar() or 0),
        "reserved": int(reserved_result.scalar() or 0),
    }


async def update_user_plan(
    db: AsyncSession, user_id: int, plan_name: str, expires_at: Optional[datetime]
) -> Optional[models.User]:
    result = await db.execute(select(models.User).filter(models.User.id == user_id))
    db_user = result.scalars().first()
    if db_user:
        db_user.plan = plan_name
        db_user.plan_expires_at = expires_at
        await db.flush()
    return db_user


# --- Affiliate Program CRUD ---


async def create_commission_for_payment(db: AsyncSession, payment: models.Payment):
    """
    Creates a commission record for a successful payment if the user was referred by an affiliate.
    """
    logger.info(
        f"Checking for commission for payment_id={payment.id}, user_id={payment.user_id}"
    )
    existing_result = await db.execute(
        select(models.Commission).filter(
            models.Commission.source_payment_id == payment.id
        )
    )
    if existing_result.scalars().first():
        logger.info(f"Commission for payment_id={payment.id} already exists; skipping.")
        return

    # 1. Get the client user from the payment
    # Using .get() is efficient for primary key lookups
    client_user = await db.get(models.User, payment.user_id)
    if not client_user:
        logger.warning(
            f"Commission check failed: client user with id {payment.user_id} not found."
        )
        return

    # 2. If client has no referrer, exit
    if not client_user.referred_by_user_id:
        logger.info(f"No commission: client user {client_user.id} has no referrer.")
        return

    # 3. Get the affiliate user
    affiliate_user = await db.get(models.User, client_user.referred_by_user_id)

    # 4. Check if the referrer is a valid affiliate
    if not (
        affiliate_user
        and affiliate_user.role == "affiliate"
        and affiliate_user.affiliate_commission_rate
        and affiliate_user.affiliate_commission_rate > 0
    ):
        logger.info(
            f"No commission: referrer {client_user.referred_by_user_id} is not a valid affiliate."
        )
        return

    # 5. Calculate commission amount
    commission_amount = payment.amount_usd * affiliate_user.affiliate_commission_rate

    # 6. Get hold period from config and calculate availability date
    affiliate_config = plans_config.get_affiliate_config()
    hold_days = affiliate_config.get("commission_hold_period_days", 45)
    available_date = datetime.now(timezone.utc) + timedelta(days=hold_days)

    # 7. Create the Commission object
    new_commission = models.Commission(
        affiliate_user_id=affiliate_user.id,
        referred_user_id=client_user.id,
        source_payment_id=payment.id,
        commission_amount_usd=commission_amount,
        status="pending",
        becomes_available_at=available_date,
    )

    # 8. Add to session
    db.add(new_commission)
    await db.flush()
    logger.info(
        f"Created pending commission {new_commission.id} for affiliate {affiliate_user.id} from payment {payment.id}"
    )


async def get_affiliate_dashboard_stats(
    db: AsyncSession, redis_client: Any, user_id: int
) -> Dict[str, Any]:
    """
    Collects statistics for a specific partner's dashboard.
    """
    # 0. Get user's referral code (always needed for clicks)
    user_query = select(models.User.referral_code).filter(models.User.id == user_id)
    user_result = await db.execute(user_query)
    referral_code = user_result.scalar_one_or_none()

    # 1. Financial statistics
    financial_stats_query = select(
        func.sum(
            case(
                (
                    models.Commission.status == "pending",
                    models.Commission.commission_amount_usd,
                ),
                else_=0,
            )
        ).label("pending_amount"),
        func.sum(
            case(
                (
                    models.Commission.status == "available",
                    models.Commission.commission_amount_usd,
                ),
                else_=0,
            )
        ).label("available_amount"),
        func.sum(
            case(
                (
                    models.Commission.status == "paid",
                    models.Commission.commission_amount_usd,
                ),
                else_=0,
            )
        ).label("total_paid_out"),
    ).filter(models.Commission.affiliate_user_id == user_id)
    financial_result = await db.execute(financial_stats_query)
    financials = financial_result.one_or_none()

    # 2. Referral statistics
    total_referrals_query = select(func.count(models.User.id)).filter(
        models.User.referred_by_user_id == user_id
    )
    total_referrals_result = await db.execute(total_referrals_query)
    registrations = total_referrals_result.scalar_one()

    paying_customers_query = select(
        func.count(distinct(models.Commission.referred_user_id))
    ).filter(models.Commission.affiliate_user_id == user_id)
    paying_customers_result = await db.execute(paying_customers_query)
    paying_customers = paying_customers_result.scalar_one()

    # Retrieve clicks from Redis
    clicks = 0
    if referral_code:
        clicks_key = f"affiliate:clicks:{referral_code}"
        clicks_val = await redis_client.get(clicks_key)
        clicks = int(clicks_val) if clicks_val else 0

    return {
        "pending_amount": financials.pending_amount
        if financials and financials.pending_amount
        else 0.0,
        "available_amount": financials.available_amount
        if financials and financials.available_amount
        else 0.0,
        "total_paid_out": financials.total_paid_out
        if financials and financials.total_paid_out
        else 0.0,
        "clicks": clicks,
        "registrations": registrations,
        "paying_customers": paying_customers,
    }


async def increment_referral_clicks(redis_client: Any, referral_code: str):
    """
    Increments click counter in Redis for a partner.
    """
    clicks_key = f"affiliate:clicks:{referral_code}"
    await redis_client.incr(clicks_key)
    return True


async def get_affiliates_with_stats(
    db: AsyncSession, skip: int = 0, limit: int = 100
) -> Tuple[List[models.User], int]:
    """
    Gets all affiliates along with their statistics, with pagination.
    - Total number of referred users.
    - Number of referred users who have made a payment.
    - Total earnings from commissions (status 'available' or 'paid').
    """
    # Subquery to count total referrals for each affiliate
    referral_count_sq = (
        select(
            models.User.referred_by_user_id,
            func.count(models.User.id).label("referral_count"),
        )
        .filter(models.User.referred_by_user_id.isnot(None))
        .group_by(models.User.referred_by_user_id)
        .subquery()
    )

    # Subquery to count paying referrals
    paying_referral_count_sq = (
        select(
            models.Commission.affiliate_user_id,
            func.count(func.distinct(models.Commission.referred_user_id)).label(
                "paying_referral_count"
            ),
        )
        .group_by(models.Commission.affiliate_user_id)
        .subquery()
    )

    # Subquery to sum up total earnings
    earnings_sq = (
        select(
            models.Commission.affiliate_user_id,
            func.sum(
                case(
                    (
                        models.Commission.status.in_(["available", "paid"]),
                        models.Commission.commission_amount_usd,
                    ),
                    else_=0,
                )
            ).label("total_earnings"),
            func.sum(
                case(
                    (
                        models.Commission.status == "pending",
                        models.Commission.commission_amount_usd,
                    ),
                    else_=0,
                )
            ).label("pending_earnings"),
        )
        .group_by(models.Commission.affiliate_user_id)
        .subquery()
    )

    # First count the total number of partners
    count_query = (
        select(func.count())
        .select_from(models.User)
        .filter(models.User.role == "affiliate")
    )
    total_count_result = await db.execute(count_query)
    total_count = total_count_result.scalar_one()

    # The main query now directly joins the User table with subqueries
    query = (
        select(
            models.User,
            func.coalesce(referral_count_sq.c.referral_count, 0).label(
                "referral_count"
            ),
            func.coalesce(paying_referral_count_sq.c.paying_referral_count, 0).label(
                "paying_referral_count"
            ),
            func.coalesce(earnings_sq.c.total_earnings, 0.0).label("total_earnings"),
            func.coalesce(earnings_sq.c.pending_earnings, 0.0).label(
                "pending_earnings"
            ),
        )
        .outerjoin(
            referral_count_sq, models.User.id == referral_count_sq.c.referred_by_user_id
        )
        .outerjoin(
            paying_referral_count_sq,
            models.User.id == paying_referral_count_sq.c.affiliate_user_id,
        )
        .outerjoin(earnings_sq, models.User.id == earnings_sq.c.affiliate_user_id)
        .filter(models.User.role == "affiliate")
        .order_by(models.User.id)
        .offset(skip)
        .limit(limit)
    )

    result = await db.execute(query)

    affiliates_with_stats = []
    for (
        user,
        referral_count,
        paying_referral_count,
        total_earnings,
        pending_earnings,
    ) in result.all():
        user.stats = {
            "referral_count": referral_count,
            "paying_referral_count": paying_referral_count,
            "total_earnings": total_earnings,
            "pending_earnings": pending_earnings,
        }
        affiliates_with_stats.append(user)

    return affiliates_with_stats, total_count


async def get_commissions_for_affiliate(
    db: AsyncSession, affiliate_user_id: int, skip: int = 0, limit: int = 100
) -> Tuple[List[models.Commission], int]:
    """
    Gets a paginated list of commissions for a specific affiliate.
    """
    query = select(models.Commission).filter(
        models.Commission.affiliate_user_id == affiliate_user_id
    )

    # Get total count before pagination
    count_query = select(func.count()).select_from(query.subquery())
    total_count_result = await db.execute(count_query)
    total_count = total_count_result.scalar_one()

    # Get paginated results
    paginated_query = (
        query.order_by(desc(models.Commission.created_at)).offset(skip).limit(limit)
    )
    commissions_result = await db.execute(paginated_query)
    commissions = commissions_result.scalars().all()

    return commissions, total_count


async def get_referrals_for_affiliate(
    db: AsyncSession, affiliate_user_id: int, skip: int = 0, limit: int = 100
) -> Tuple[List[models.User], int]:
    """
    Gets a paginated list of referred users for a specific affiliate.
    """
    query = select(models.User).filter(
        models.User.referred_by_user_id == affiliate_user_id
    )

    # Get total count before pagination
    count_query = select(func.count()).select_from(query.subquery())
    total_count_result = await db.execute(count_query)
    total_count = total_count_result.scalar_one()

    # Get paginated results
    paginated_query = (
        query.order_by(desc(models.User.created_at)).offset(skip).limit(limit)
    )
    users_result = await db.execute(paginated_query)
    users = users_result.scalars().all()

    return users, total_count


async def get_users(
    db: AsyncSession, skip: int = 0, limit: int = 100
) -> List[models.User]:
    result = await db.execute(select(models.User).offset(skip).limit(limit))
    return result.scalars().all()


async def get_user_by_id(db: AsyncSession, user_id: int) -> Optional[models.User]:
    """Gets a user by their ID."""
    result = await db.execute(select(models.User).where(models.User.id == user_id))
    return result.scalars().first()


async def ensure_user_tradingview_webhook_token(
    db: AsyncSession, user: models.User
) -> models.User:
    if not user.tradingview_webhook_token:
        user.tradingview_webhook_token = _generate_tradingview_webhook_token()
        await db.flush()
        await db.refresh(user)
    return user


async def get_problematic_tasks(db: AsyncSession) -> List[models.Task]:
    """
    Retrieves a list of problematic tasks:
    - Tasks with FAILED status in the last 24 hours
    - Tasks with RUNNING status longer than 60 minutes
    """
    twenty_four_hours_ago = datetime.now(timezone.utc) - timedelta(hours=24)
    sixty_minutes_ago = datetime.now(timezone.utc) - timedelta(minutes=60)

    # Failed tasks
    failed_query = (
        select(models.Task)
        .where(
            models.Task.status == "FAILED",
            models.Task.submitted_at >= twenty_four_hours_ago,
        )
        .order_by(models.Task.submitted_at.desc())
    )

    failed_result = await db.execute(failed_query)
    failed_tasks = failed_result.scalars().all()

    # Hung tasks
    stuck_query = (
        select(models.Task)
        .where(
            models.Task.status == "RUNNING",
            models.Task.submitted_at <= sixty_minutes_ago,
        )
        .order_by(models.Task.submitted_at.asc())
    )

    stuck_result = await db.execute(stuck_query)
    stuck_tasks = stuck_result.scalars().all()

    return list(failed_tasks) + list(stuck_tasks)


async def get_users_paginated(
    db: AsyncSession,
    skip: int = 0,
    limit: int = 100,
    search: Optional[str] = None,
    plan: Optional[str] = None,
) -> Tuple[List[models.User], int]:
    """
    Retrieves a paginated list of users with optional search and filtering.
    """
    query = select(models.User)

    if search:
        search_term = f"%{search}%"
        query = query.filter(
            (models.User.username.ilike(search_term))
            | (models.User.email.ilike(search_term))
        )

    if plan:
        query = query.filter(models.User.plan == plan)

    # Count the total number before pagination
    count_query = select(func.count()).select_from(query.subquery())
    total_count_result = await db.execute(count_query)
    total_count = total_count_result.scalar_one()

    # Get paginated results
    paginated_query = query.offset(skip).limit(limit).order_by(models.User.id)
    users_result = await db.execute(paginated_query)
    users = users_result.scalars().all()

    return users, total_count


async def admin_get_user_details(
    db: AsyncSession, user_id: int
) -> Optional[models.User]:
    """
    Retrieves user details by ID. Admin version.
    """
    result = await db.execute(select(models.User).filter(models.User.id == user_id))
    return result.scalars().first()


async def admin_get_user_extended_details(
    db: AsyncSession, user_id: int
) -> Optional[Dict[str, Any]]:
    """
    Retrieves extended user information for the detailed admin page.
    Includes basic information, recent tasks, paper wallet balance, and bonus history.
    """
    user = await admin_get_user_details(db, user_id)
    if not user:
        return None

    # Get the last 10 tasks
    tasks_query = (
        select(models.Task)
        .where(models.Task.user_id == user_id)
        .order_by(models.Task.submitted_at.desc())
        .limit(10)
    )
    tasks_result = await db.execute(tasks_query)
    recent_tasks = tasks_result.scalars().all()

    # Get paper wallet balance
    paper_wallet_query = select(models.PaperWallet).where(
        models.PaperWallet.user_id == user_id
    )
    paper_wallet_result = await db.execute(paper_wallet_query)
    paper_wallets = paper_wallet_result.scalars().all()

    # Get bonus history
    bonuses_query = (
        select(models.Bonus)
        .where(models.Bonus.user_id == user_id)
        .order_by(models.Bonus.id.desc())
    )
    bonuses_result = await db.execute(bonuses_query)
    bonuses = bonuses_result.scalars().all()

    return {
        "user": user,
        "recent_tasks": recent_tasks,
        "paper_wallets": paper_wallets,
        "bonuses": bonuses,
    }


async def admin_update_user(
    db: AsyncSession, user_id: int, update_data: schemas.AdminUserUpdate
) -> Optional[models.User]:
    """
    Updates user data (plan, active status, partner role). Admin version.
    """
    db_user = await admin_get_user_details(db, user_id=user_id)
    if not db_user:
        return None

    update_dict = update_data.model_dump(exclude_unset=True)

    # Check if role is being changed
    if "role" in update_dict:
        # If user is becoming an affiliate and no rate is specified, set default
        if (
            update_dict["role"] == "affiliate"
            and "affiliate_commission_rate" not in update_dict
        ):
            affiliate_config = plans_config.get_affiliate_config()
            default_rate = affiliate_config.get("default_commission_rate", 0.20)
            db_user.affiliate_commission_rate = default_rate

        # If user is no longer an affiliate, nullify their rate
        elif db_user.role == "affiliate" and update_dict["role"] != "affiliate":
            db_user.affiliate_commission_rate = None

    # Generic update for all other fields
    for key, value in update_dict.items():
        if hasattr(db_user, key):
            setattr(db_user, key, value)

    # commit will be called in the endpoint
    return db_user


async def admin_create_bonus(
    db: AsyncSession, user_id: int, bonus_data: schemas.AdminBonusCreate
) -> models.Bonus:
    """
    Creates and awards an active bonus to the user. Admin version.
    """
    db_bonus = models.Bonus(
        user_id=user_id,
        feature_name=bonus_data.feature_name,
        quantity=bonus_data.quantity,
        status="active",  # Immediately active, as specified in the requirements
    )
    db.add(db_bonus)
    await db.flush()
    await db.refresh(db_bonus)
    return db_bonus


async def get_dashboard_stats(db: AsyncSession) -> schemas.DashboardStats:
    """
    Collects statistics for the admin dashboard.
    """
    seven_days_ago = datetime.now(timezone.utc) - timedelta(days=7)

    # 1. New users in 7 days
    new_users_query = select(func.count(models.User.id)).filter(
        models.User.created_at >= seven_days_ago
    )
    new_users_result = await db.execute(new_users_query)
    new_users_count = new_users_result.scalar_one_or_none() or 0

    # 2. Tasks launched in 7 days
    tasks_run_query = select(func.count(models.Task.id)).filter(
        models.Task.submitted_at >= seven_days_ago
    )
    tasks_run_result = await db.execute(tasks_run_query)
    tasks_run_count = tasks_run_result.scalar_one_or_none() or 0

    # 3. Number of tasks by type (last 7 days only)
    task_counts_query = (
        select(models.Task.task_type, func.count(models.Task.id))
        .filter(models.Task.submitted_at >= seven_days_ago)
        .group_by(models.Task.task_type)
    )
    task_counts_result = await db.execute(task_counts_query)
    task_counts_by_type = {
        task_type: count for task_type, count in task_counts_result.all()
    }

    return schemas.DashboardStats(
        new_users_last_7_days=new_users_count,
        tasks_run_last_7_days=tasks_run_count,
        task_counts_by_type=task_counts_by_type,
    )


# --- AppConfig CRUD ---


async def get_config_model(
    db: AsyncSession, user_id: int
) -> Optional[models.AppConfig]:
    """
    Retrieves the database application configuration model for the specified user.
    """
    result = await db.execute(
        select(models.AppConfig).where(models.AppConfig.user_id == user_id)
    )
    return result.scalar_one_or_none()


async def create_user(
    db: AsyncSession,
    user: schemas.UserCreate,
    referred_by_user_id: Optional[int] = None,
    is_active: bool = False,
) -> models.User:
    hashed_password = security.get_password_hash(user.password)
    referral_code = f"REF-{uuid.uuid4().hex[:8].upper()}"

    # Check if this is the first user in the system
    users_count_result = await db.execute(select(func.count(models.User.id)))
    users_count = users_count_result.scalar_one_or_none() or 0

    is_first_user = users_count == 0
    user_role = "admin" if is_first_user else "user"

    # If it's the first user, we also make them active automatically and give them the 'pro' plan forever
    final_is_active = True if is_first_user else is_active

    if is_first_user:
        initial_plan = "pro"
        initial_plan_expires_at = None
    else:
        initial_plan = "free"
        initial_plan_expires_at = None

        trial_config = plans_config.get_registration_trial_config()
        if trial_config.get("enabled") and trial_config.get("days", 0) > 0:
            trial_plan = trial_config.get("plan", "standard")
            if trial_plan in plans_config.get_all_plans():
                initial_plan = trial_plan
                initial_plan_expires_at = datetime.now(timezone.utc) + timedelta(
                    days=trial_config["days"]
                )
            else:
                logger.warning(
                    "Registration trial plan '%s' is not defined in plans_config.yml. New user will stay on free plan.",
                    trial_plan,
                )

    db_user = models.User(
        username=user.username,
        email=user.email,
        hashed_password=hashed_password,
        plan=initial_plan,
        plan_expires_at=initial_plan_expires_at,
        referral_code=referral_code,
        tradingview_webhook_token=_generate_tradingview_webhook_token(),
        referred_by_user_id=referred_by_user_id,
        is_active=final_is_active,  # Set user's active state
        role=user_role,  # Set first user as admin
        symbol_selection_config=schemas.SymbolSelectionConfig().model_dump(),
        created_at=datetime.now(timezone.utc),  # Explicitly set created_at to UTC
    )
    db.add(db_user)
    await db.flush()

    default_risk_management = schemas.RiskManagementSettings(
        maxDrawdown=10.0,
        maxConsecutiveLosses=10,
        maxConcurrentTrades=5,
        stopLossEnabled=True,
        defaultStopLossPercent=2.0,
        riskPerTradePercent=1.0,  # Default 1% risk per trade for live trading
    )
    default_backtest_risk_management = schemas.BacktestRiskManagementSettings(
        maxDrawdown=10.0,
        dailyMaxLossPercent=5.0,
        maxConsecutiveLosses=10,
        maxConcurrentTrades=5,
        stopLossEnabled=True,
        defaultStopLossPercent=2.0,
    )
    default_notifications = schemas.NotificationSettings(
        emailEnabled=security.EMAIL_CONFIRMATION_ENABLED,  # Set based on global config
        telegramEnabled=False,
        telegramChatId=None,
    )
    default_exchange_settings = schemas.ExchangeSettings(
        binance=schemas.ExchangePlatformSettings(enabled=False, api_key_name=""),
    )
    db_config = models.AppConfig(
        user_id=db_user.id,
        risk_management=default_risk_management.model_dump(by_alias=True),
        backtest_risk_management=default_backtest_risk_management.model_dump(
            by_alias=True
        ),
        notifications=default_notifications.model_dump(by_alias=True),
        exchange_settings=default_exchange_settings.model_dump(by_alias=True),
        data_sources={"symbols": ["BTCUSDT", "ETHUSDT"], "statuses": []},
    )
    db.add(db_config)

    # for strategy_name in STRATEGIES.keys():
    #     default_params = STRATEGY_DEFAULTS.get(strategy_name, {})
    #     strategy_config_schema = schemas.StrategyConfigCreate(
    #         name=strategy_name,
    #         config_data=default_params,
    #         symbol_selection_mode='DYNAMIC',
    #         use_ml_confirmation=False
    #     )
    #     db_strategy_config = models.StrategyConfig(
    #         **strategy_config_schema.model_dump(),
    #         user_id=db_user.id
    #     )
    #     db.add(db_strategy_config)

    await db.refresh(db_user)
    return db_user


async def delete_user(db: AsyncSession, user_id: int) -> bool:
    """
    Deletes a user and all of their associated data.
    """
    user = await db.get(models.User, user_id)
    if not user:
        return False

    # Set users.referred_by_user_id to NULL for users referred by the one being deleted.
    await db.execute(
        text(
            "UPDATE users SET referred_by_user_id = NULL WHERE referred_by_user_id = :user_id"
        ),
        {"user_id": user_id},
    )

    # Set bonuses.source_user_id to NULL for bonuses sourced from the user being deleted.
    await db.execute(
        text(
            "UPDATE bonuses SET source_user_id = NULL WHERE source_user_id = :user_id"
        ),
        {"user_id": user_id},
    )

    # The order here matters if these tables have dependencies on each other.
    # Delete children first.
    await db.execute(
        delete(models.TradeAnalytics).where(models.TradeAnalytics.user_id == user_id)
    )
    await db.execute(delete(models.Trade).where(models.Trade.user_id == user_id))
    await db.execute(delete(models.UserGene).where(models.UserGene.user_id == user_id))
    await db.execute(
        delete(models.TrainingRun).where(models.TrainingRun.user_id == user_id)
    )
    await db.execute(
        delete(models.Commission).where(models.Commission.affiliate_user_id == user_id)
    )
    await db.execute(
        delete(models.Commission).where(models.Commission.referred_user_id == user_id)
    )
    await db.execute(
        delete(models.LeaderboardEntry).where(
            models.LeaderboardEntry.user_id == user_id
        )
    )
    await db.execute(
        delete(models.SharedBacktest).where(models.SharedBacktest.user_id == user_id)
    )

    # Now delete the parents of the above.
    await db.execute(
        delete(models.StrategyConfig).where(models.StrategyConfig.user_id == user_id)
    )
    await db.execute(
        delete(models.DatasetRun).where(models.DatasetRun.user_id == user_id)
    )
    await db.execute(delete(models.Payment).where(models.Payment.user_id == user_id))

    # Now delete the rest which have no other dependencies among themselves.
    await db.execute(
        delete(models.AIChatMessage).where(models.AIChatMessage.user_id == user_id)
    )
    await db.execute(
        delete(models.PhantomTrade).where(models.PhantomTrade.user_id == user_id)
    )
    await db.execute(delete(models.ApiKey).where(models.ApiKey.user_id == user_id))
    await db.execute(
        delete(models.AppConfig).where(models.AppConfig.user_id == user_id)
    )
    await db.execute(
        delete(models.PaperWallet).where(models.PaperWallet.user_id == user_id)
    )
    await db.execute(
        delete(models.UserAchievement).where(models.UserAchievement.user_id == user_id)
    )
    await db.execute(
        delete(models.SymbolStrategyPerformance).where(
            models.SymbolStrategyPerformance.user_id == user_id
        )
    )
    # Delete backtest data in strict dependency order: execution -> trade -> run -> task
    await db.execute(
        delete(models.BacktestTradeExecution).where(
            models.BacktestTradeExecution.trade_id.in_(
                select(models.BacktestTrade.id).where(
                    models.BacktestTrade.backtest_run_id.in_(
                        select(models.BacktestRun.id).where(
                            models.BacktestRun.user_id == user_id
                        )
                    )
                )
            )
        )
    )
    await db.execute(
        delete(models.BacktestTrade).where(
            models.BacktestTrade.backtest_run_id.in_(
                select(models.BacktestRun.id).where(
                    models.BacktestRun.user_id == user_id
                )
            )
        )
    )
    await db.execute(
        delete(models.BacktestRun).where(models.BacktestRun.user_id == user_id)
    )
    await db.execute(
        delete(models.FoundStrategy).where(
            models.FoundStrategy.run_id.in_(
                select(models.GeneticRun.id).where(models.GeneticRun.user_id == user_id)
            )
        )
    )
    await db.execute(
        delete(models.GeneticRun).where(models.GeneticRun.user_id == user_id)
    )
    await db.execute(delete(models.Bonus).where(models.Bonus.user_id == user_id))
    await db.execute(delete(models.Task).where(models.Task.user_id == user_id))

    # SQLAlchemy will now handle deleting related objects defined with `cascade="all, delete-orphan"`
    # on the User model, which are: BacktestRun, GeneticRun, Bonus (where user_id matches).
    await db.delete(user)

    return True


# --- Bonus CRUD ---
async def create_pending_bonuses_for_referral(
    db: AsyncSession, referrer_id: int, referred_id: int
):
    bonus_config = plans_config.get_referral_bonus_config()
    referrer_bonus_config = bonus_config.get("referrer_bonus")
    referred_user_bonus_config = bonus_config.get("referred_user_bonus")

    if referrer_bonus_config:
        db_bonus_referrer = models.Bonus(
            user_id=referrer_id,
            feature_name=referrer_bonus_config["feature_name"],
            quantity=referrer_bonus_config["quantity"],
            status="pending",
            source_user_id=referred_id,
        )
        db.add(db_bonus_referrer)

    if referred_user_bonus_config:
        db_bonus_referred = models.Bonus(
            user_id=referred_id,
            feature_name=referred_user_bonus_config["feature_name"],
            quantity=referred_user_bonus_config["quantity"],
            status="pending",
            source_user_id=referrer_id,
        )
        db.add(db_bonus_referred)
    await db.flush()


async def activate_bonuses_for_user(db: AsyncSession, user_id: int):
    result = await db.execute(
        select(models.Bonus).filter(
            models.Bonus.user_id == user_id, models.Bonus.status == "pending"
        )
    )
    bonuses_to_activate = result.scalars().all()
    for bonus in bonuses_to_activate:
        bonus.status = "active"
    await db.flush()


async def get_and_consume_bonus(
    db: AsyncSession, user_id: int, feature_name: str
) -> bool:
    result = await db.execute(
        select(models.Bonus)
        .filter(
            models.Bonus.user_id == user_id,
            models.Bonus.feature_name == feature_name,
            models.Bonus.status == "active",
            models.Bonus.quantity > 0,
        )
        .order_by(models.Bonus.id)
        .limit(1)
    )
    bonus = result.scalars().first()

    if bonus:
        bonus.quantity -= 1
        await db.flush()
        return True
    return False


async def get_user_bonuses(
    db: AsyncSession, user_id: int, include_pending: bool = True
) -> list[models.Bonus]:
    """
    Retrieves user bonuses with quantity > 0.
    Includes both active and pending bonuses by default.
    """
    filters = [models.Bonus.user_id == user_id, models.Bonus.quantity > 0]

    if not include_pending:
        filters.append(models.Bonus.status == "active")

    result = await db.execute(
        select(models.Bonus)
        .filter(*filters)
        .order_by(models.Bonus.feature_name, models.Bonus.status)
    )
    return result.scalars().all()


# --- Config CRUD ---
async def get_config(db: AsyncSession, user_id: int) -> Optional[schemas.AppConfig]:
    # 1. Get primary configuration
    config_result = await db.execute(
        select(models.AppConfig).filter(models.AppConfig.user_id == user_id)
    )
    config = config_result.scalars().first()

    if not config:
        return None

    # 2. Get API keys
    keys_result = await db.execute(
        select(models.ApiKey).filter(models.ApiKey.user_id == user_id)
    )
    api_keys = keys_result.scalars().all()

    # 3. Assemble ALL data into one dictionary BEFORE validation
    final_config_data = {
        "user_id": config.user_id,
        "risk_management": config.risk_management,
        "backtest_risk_management": config.backtest_risk_management,
        "notifications": config.notifications,
        "data_sources": config.data_sources,
        "exchange_settings": config.exchange_settings,
        # Immediately add keys to the dictionary
        "api_keys": [schemas.ApiKey.model_validate(key) for key in api_keys],
    }

    # 4. Validate full dictionary, guaranteeing all fields are present
    return schemas.AppConfig.model_validate(final_config_data)


async def update_config_section(
    db: AsyncSession, user_id: int, section: str, data: dict
):
    try:
        config_result = await db.execute(
            select(models.AppConfig).filter(models.AppConfig.user_id == user_id)
        )
        db_config = config_result.scalars().first()
        if not db_config:
            return None

        if hasattr(db_config, section):
            current_data = getattr(db_config, section)
            if current_data is None:
                # If current data is missing, set new values (filtering out None)
                filtered_data = {k: v for k, v in data.items() if v is not None}
                setattr(db_config, section, filtered_data)
            else:
                # During merge, exclude None values to avoid overwriting existing data
                filtered_data = {k: v for k, v in data.items() if v is not None}
                current_data.update(filtered_data)
            orm_attributes.flag_modified(db_config, section)
        else:
            return None

        await (
            db.flush()
        )  # Use flush so changes are sent to DB but transaction remains open
        await db.refresh(db_config)
        return db_config
    except Exception as e:
        await db.rollback()
        raise e


async def add_symbol_to_config(db: AsyncSession, user_id: int, symbol: str):
    db_config_result = await db.execute(
        select(models.AppConfig).filter(models.AppConfig.user_id == user_id)
    )
    db_config = db_config_result.scalars().first()
    if not db_config:
        return None

    if symbol.upper() not in db_config.data_sources["symbols"]:
        db_config.data_sources["symbols"].append(symbol.upper())
        orm_attributes.flag_modified(db_config, "data_sources")
        await db.flush()
        await db.refresh(db_config)

    return db_config.data_sources


async def delete_symbol_from_config(db: AsyncSession, user_id: int, symbol: str):
    result = await db.execute(
        select(models.AppConfig).filter(models.AppConfig.user_id == user_id)
    )
    db_config = result.scalars().first()
    if not db_config:
        return None

    upper_symbol = symbol.upper()
    if upper_symbol in db_config.data_sources["symbols"]:
        db_config.data_sources["symbols"].remove(upper_symbol)
        orm_attributes.flag_modified(db_config, "data_sources")
        await db.flush()
        await db.refresh(db_config)

    return db_config.data_sources


# --- ApiKey CRUD ---
async def get_active_api_keys_for_user(
    db: AsyncSession, user_id: int
) -> List[models.ApiKey]:
    """
    Returns all active API keys of the user (is_active=True).
    Allows keys with status 'valid' or 'untested'.
    """
    result = await db.execute(
        select(models.ApiKey).filter(
            models.ApiKey.user_id == user_id,
            models.ApiKey.is_active,
            models.ApiKey.status != "invalid",
        )
    )
    return result.scalars().all()


async def get_active_api_key_for_user(
    db: AsyncSession, user_id: int
) -> Optional[models.ApiKey]:
    """
    Gets the user's active API key based on their AppConfig.
    Ensures the selected key is also marked as is_active=True.
    """
    config_result = await db.execute(
        select(models.AppConfig).filter(models.AppConfig.user_id == user_id)
    )
    app_config = config_result.scalars().first()

    if not app_config or not app_config.exchange_settings:
        logger.warning(
            f"No AppConfig or exchange_settings found for user_id: {user_id}"
        )
        return None

    active_exchange_key = None
    active_key_name = None
    for configured_exchange, exchange_config in app_config.exchange_settings.items():
        if not isinstance(exchange_config, dict):
            continue
        candidate_name = exchange_config.get("api_key_name")
        if candidate_name and exchange_config.get("enabled", True):
            active_exchange_key = configured_exchange
            active_key_name = candidate_name
            break

    if not active_key_name:
        logger.warning(
            f"No active 'api_key_name' found in exchange_settings for user_id: {user_id}"
        )
        return None

    key_result = await db.execute(
        select(models.ApiKey).filter(
            models.ApiKey.user_id == user_id,
            models.ApiKey.name == active_key_name,
            models.ApiKey.is_active,
        )
    )
    candidates = key_result.scalars().all()
    api_key = next(
        (
            key
            for key in candidates
            if exchange_settings_key(key.exchange)
            == exchange_settings_key(active_exchange_key)
        ),
        candidates[0] if candidates else None,
    )

    if not api_key:
        logger.warning(
            f"Active ApiKey with name '{active_key_name}' not found or disabled for user_id: {user_id}"
        )
        return None

    return api_key


async def check_api_key_exists(db: AsyncSession, api_key: str) -> bool:
    """
    Checks if an API key exists in the database (for any user).
    Uses SHA-256 hash for deterministic comparison.
    Returns True if the key is already in use.
    """
    key_hash = security.hash_data(api_key)
    result = await db.execute(
        select(models.ApiKey).filter(models.ApiKey.api_key_hash == key_hash)
    )
    existing_key = result.scalars().first()
    return existing_key is not None


async def create_api_key_for_user(
    db: AsyncSession, user_id: int, key_data: schemas.ApiKeyCreate
):
    # Check if this API key is already in use
    if await check_api_key_exists(db, key_data.api_key):
        raise ValueError(
            "This API key is already registered in the system. Each API key can only be used once."
        )

    encrypted_key = security.encrypt_data(key_data.api_key)

    import json

    if getattr(key_data, "api_password", None):
        packed_secret = json.dumps(
            {"secret": key_data.api_secret, "password": key_data.api_password}
        )
        encrypted_secret = security.encrypt_data(packed_secret)
    else:
        encrypted_secret = security.encrypt_data(key_data.api_secret)

    key_hash = security.hash_data(key_data.api_key)

    db_key = models.ApiKey(
        user_id=user_id,
        name=key_data.name,
        exchange=key_data.exchange,
        encrypted_api_key=encrypted_key,
        encrypted_api_secret=encrypted_secret,
        api_key_hash=key_hash,
        key_prefix=key_data.api_key[:4] + "..." + key_data.api_key[-4:],
    )
    db.add(db_key)
    return db_key


async def delete_api_key(db: AsyncSession, user_id: int, key_id: int):
    result = await db.execute(
        select(models.ApiKey)
        .filter(models.ApiKey.id == key_id)
        .filter(models.ApiKey.user_id == user_id)
    )
    db_key = result.scalars().first()

    if db_key:
        await db.delete(db_key)
        # commit will be called in the endpoint
        return db_key
    return None


async def get_api_key_by_id(
    db: AsyncSession, user_id: int, key_id: int
) -> Optional[models.ApiKey]:
    """Gets a single API key by its ID, ensuring it belongs to the user."""
    result = await db.execute(
        select(models.ApiKey).filter(
            models.ApiKey.id == key_id, models.ApiKey.user_id == user_id
        )
    )
    return result.scalars().first()


async def update_api_key_status(
    db: AsyncSession,
    key_id: int,
    user_id: int,
    status: str,
    status_message: Optional[str] = None,
) -> Optional[models.ApiKey]:
    """Updates the status and status_message of an API key. Filters by user_id for security."""
    result = await db.execute(
        select(models.ApiKey).filter(
            models.ApiKey.id == key_id, models.ApiKey.user_id == user_id
        )
    )
    db_key = result.scalars().first()
    if db_key:
        db_key.status = status
        db_key.status_message = status_message
        await db.flush()
    return db_key


async def set_api_key_active_status(
    db: AsyncSession, key_id: int, user_id: int, is_active: bool
) -> Optional[models.ApiKey]:
    """Activates/deactivates API key."""
    result = await db.execute(
        select(models.ApiKey).filter(
            models.ApiKey.id == key_id, models.ApiKey.user_id == user_id
        )
    )
    api_key = result.scalars().first()
    if api_key:
        api_key.is_active = is_active
        await db.flush()
    return api_key


async def get_api_keys_for_user(db: AsyncSession, user_id: int) -> List[models.ApiKey]:
    """
    Gets all API keys for a user.
    """
    result = await db.execute(
        select(models.ApiKey).filter(models.ApiKey.user_id == user_id)
    )
    return result.scalars().all()


# --- Trade CRUD ---
async def get_trades(
    db: AsyncSession,
    user_id: int,
    skip: int = 0,
    limit: int = 100,
    symbol: Optional[str] = None,
    strategy_config_id: Optional[str] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    trade_mode: Optional[str] = None,
    api_key_id: Optional[int] = None,
):
    # Base query
    query = select(models.Trade).filter(models.Trade.user_id == user_id)

    # Dynamic filtering
    if symbol:
        query = query.filter(models.Trade.symbol == symbol.upper())
    if strategy_config_id:
        query = query.filter(models.Trade.strategy_config_id == strategy_config_id)
    if start_date:
        query = query.filter(models.Trade.timestamp_close >= start_date)
    if end_date:
        # Add one day to include trades on the end date
        query = query.filter(
            models.Trade.timestamp_close < end_date + timedelta(days=1)
        )

    if trade_mode:
        query = query.filter(models.Trade.trade_mode == trade_mode.upper())

    if api_key_id is not None:
        query = query.filter(models.Trade.api_key_id == api_key_id)

    # Apply sorting, pagination and execute the query
    result = await db.execute(
        query.order_by(desc(models.Trade.timestamp_close)).offset(skip).limit(limit)
    )
    return result.scalars().all()


async def get_trades_with_count_by_run_id(
    db: AsyncSession, user_id: int, run_id: str, skip: int = 0, limit: int = 20
) -> Tuple[List[models.BacktestTrade], int]:
    """
    Gets the list of trades for a specific backtest with pagination and the total count.
    """
    # 1. Query to get total trade count
    count_stmt = (
        select(func.count(models.BacktestTrade.id))
        .join(
            models.BacktestRun,
            models.BacktestTrade.backtest_run_id == models.BacktestRun.id,
        )
        .where(
            models.BacktestRun.id == run_id,
            models.BacktestRun.user_id == user_id,
            _visible_backtest_trade_clause(),
        )
    )
    total_count_result = await db.execute(count_stmt)
    total_count = total_count_result.scalar_one_or_none() or 0

    if total_count == 0:
        return [], 0

    # 2. Main query to get a page of trades
    trades_stmt = (
        select(models.BacktestTrade)
        .join(
            models.BacktestRun,
            models.BacktestTrade.backtest_run_id == models.BacktestRun.id,
        )
        .where(
            models.BacktestRun.id == run_id,
            models.BacktestRun.user_id == user_id,
            _visible_backtest_trade_clause(),
        )
        .order_by(models.BacktestTrade.timestamp_exit.desc())
        .offset(skip)
        .limit(limit)
    )
    trades_result = await db.execute(trades_stmt)
    trades = trades_result.scalars().all()

    return trades, total_count


async def create_trade(
    db: AsyncSession, user_id: int, trade_data: dict, trade_mode: str = "LIVE"
) -> models.Trade:
    """
    Creates and SAVES (commits) a trade record in the database,
    and ONLY THEN triggers the analytical task.
    """
    logger.info(
        f"[crud.create_trade] Attempting to save trade for user_id={user_id}, symbol={trade_data.get('symbol')}"
    )

    db_trade = models.Trade(
        user_id=user_id,
        trade_uuid=trade_data.get("trade_uuid", str(uuid.uuid4())),
        timestamp_close=trade_data["timestamp_close"],
        timestamp_signal=trade_data.get(
            "timestamp_signal"
        ),  # When signal was generated
        timestamp_entry=trade_data.get(
            "timestamp_entry"
        ),  # When position was actually opened
        symbol=trade_data.get("symbol"),
        strategy_config_id=trade_data.get("strategy_config_id"),
        direction=trade_data.get("direction"),
        entry_price=trade_data.get("entry_price"),
        exit_price=trade_data.get("exit_price"),
        pnl=trade_data.get("pnl"),
        commission=trade_data.get("commission"),
        exit_reason=trade_data.get("exit_reason"),
        quantity=trade_data.get("quantity"),
        trade_mode=trade_mode.upper(),
        api_key_id=trade_data.get("api_key_id"),
        # New fields for grouping partial exits
        position_entry_id=trade_data.get("position_entry_id"),
        exit_type=trade_data.get("exit_type"),
        is_final_exit=trade_data.get("is_final_exit", False),
        # Signal details with decision trace for analytics
        signal_details_json=trade_data.get("signal_details_json"),
        # Maximum floating profit and loss during the trade
        max_floating_profit=trade_data.get("max_floating_profit"),
        max_floating_loss=trade_data.get("max_floating_loss"),
    )

    try:
        db.add(db_trade)
        await db.flush()
        await db.refresh(db_trade)
        logger.info(
            f"[crud.create_trade] Trade object {db_trade.trade_uuid} (ID: {db_trade.id}) successfully added to the session."
        )

        # try:
        #     if trade_mode.upper() in ["LIVE", "PAPER"]:
        #         process_live_trade_analytics_task.delay(db_trade.id)
        #         logger.info(f"[crud.create_trade] Analytical task started for trade_id: {db_trade.id}")
        # except Exception as e:
        #     logger.error(f"[crud.create_trade] Error launching analytical task for trade_id={db_trade.id}: {e}", exc_info=True)

        return db_trade

    except Exception as e:
        logger.error(
            f"[crud.create_trade] Error adding trade to session for user_id={user_id}: {e}",
            exc_info=True,
        )
        await db.rollback()
        raise


async def get_last_open_trade_for_symbol(
    db: AsyncSession, user_id: int, symbol: str
) -> Optional[models.Trade]:
    """
    Retrieves the most recent trade for a symbol that looks like an 'ENTRY' (based on entry_client_order_id pattern or simple timestamp).
    Used for reconciling orphaned positions.
    """
    # Try to find the latest trade that looks like an entry (x-entry)
    stmt = (
        select(models.Trade)
        .filter(
            models.Trade.user_id == user_id,
            models.Trade.symbol == symbol,
            models.Trade.trade_uuid.like("x-entry-%"),  # Filter for entry orders logic
        )
        .order_by(desc(models.Trade.timestamp_close))
        .limit(1)
    )

    result = await db.execute(stmt)
    return result.scalars().first()


# --- CRUD for SymbolStrategyPerformance ---


async def get_trades_with_count(
    db: AsyncSession,
    user_id: int,
    skip: int = 0,
    limit: int = 20,
    symbol: Optional[str] = None,
    strategy_config_id: Optional[str] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    trade_mode: Optional[str] = None,
    api_key_id: Optional[int] = None,
) -> Tuple[List[models.Trade], int]:
    """
    Gets the list of real (live) trades for a user with pagination, filtering, and total count.
    """
    # 1. Base query to retrieve trades with filters
    query = select(models.Trade).filter(models.Trade.user_id == user_id)
    if symbol:
        query = query.filter(models.Trade.symbol == symbol.upper())
    if strategy_config_id:
        query = query.filter(models.Trade.strategy_config_id == strategy_config_id)
    if start_date:
        query = query.filter(models.Trade.timestamp_close >= start_date)
    if end_date:
        query = query.filter(
            models.Trade.timestamp_close < end_date + timedelta(days=1)
        )
    if trade_mode:
        query = query.filter(models.Trade.trade_mode == trade_mode.upper())
    if api_key_id is not None:
        query = query.filter(models.Trade.api_key_id == api_key_id)

    # 2. Query to retrieve total count with filters
    count_stmt = select(func.count()).select_from(query.subquery())
    total_count_result = await db.execute(count_stmt)
    total_count = total_count_result.scalar_one_or_none() or 0

    if total_count == 0:
        return [], 0

    # 3. Main query to retrieve a page of trades
    trades_stmt = (
        query.order_by(models.Trade.timestamp_close.desc()).offset(skip).limit(limit)
    )
    trades_result = await db.execute(trades_stmt)
    trades = trades_result.scalars().all()

    return trades, total_count


async def get_all_symbol_strategy_performance(
    db: AsyncSession, user_id: int
) -> List[models.SymbolStrategyPerformance]:
    """
    Loads all strategy performance records for the specified user.
    Used for initializing RiskManager.
    """
    logger.debug(
        f"Querying all SymbolStrategyPerformance records for user_id={user_id}"
    )
    try:
        result = await db.execute(
            select(models.SymbolStrategyPerformance).filter(
                models.SymbolStrategyPerformance.user_id == user_id
            )
        )
        return result.scalars().all()
    except Exception as e:
        logger.error(
            f"Error loading SymbolStrategyPerformance for user_id={user_id}: {e}",
            exc_info=True,
        )
        return []


async def update_or_create_symbol_strategy_performance(
    db: AsyncSession, user_id: int, performance_data: Dict[str, Any]
) -> models.SymbolStrategyPerformance:
    """
    Updates an existing performance record for a "symbol-strategy" pair
    or creates a new one if it doesn't exist (UPSERT logic).
    """
    symbol = performance_data["symbol"]
    strategy_name = performance_data["strategy_name"]
    log_prefix = f"[crud.ssp_upsert|user:{user_id}|{symbol}-{strategy_name}]"

    try:
        # 1. Try to find existing record
        result = await db.execute(
            select(models.SymbolStrategyPerformance).filter_by(
                user_id=user_id, symbol=symbol, strategy_name=strategy_name
            )
        )
        record = result.scalars().first()

        # 2. If record is found - update it
        if record:
            logger.debug(f"{log_prefix} Existing record found. Updating...")
            for key, value in performance_data.items():
                setattr(record, key, value)
            # Explicit indication that JSON field was modified, if present
            if "trade_results_buffer_json" in performance_data:
                flag_modified(record, "trade_results_buffer_json")

            # Return the updated object
            await db.flush()
            await db.refresh(record)
            return record

        # 3. If record is not found - create a new one
        else:
            logger.debug(f"{log_prefix} Record not found. Creating new...")
            new_record = models.SymbolStrategyPerformance(
                user_id=user_id, **performance_data
            )
            db.add(new_record)
            await db.flush()
            await db.refresh(new_record)
            logger.info(f"{log_prefix} New record successfully created.")
            return new_record

    except Exception as e:
        logger.error(f"{log_prefix} Error during UPSERT operation: {e}", exc_info=True)
        # Roll back transaction to avoid partial saving
        await db.rollback()
        raise


# --- Task CRUD ---
async def create_task(
    db: AsyncSession, user_id: int, task_id: str, task_type: str, parameters: dict
):
    db_task = models.Task(
        user_id=user_id,
        task_id=task_id,
        task_type=task_type,
        parameters=parameters,
        status="PENDING",
        submitted_at=datetime.now(timezone.utc),  # Explicitly set submitted_at to UTC
    )
    db.add(db_task)
    return db_task


async def get_task(db: AsyncSession, user_id: int, task_id: str):
    result = await db.execute(
        select(models.Task)
        .filter(models.Task.task_id == task_id)
        .filter(models.Task.user_id == user_id)
    )
    return result.scalars().first()


async def update_task_status(
    db: AsyncSession,
    task_id: str,
    status: str,
    results: dict | None,
    error_message: str | None,
):
    result = await db.execute(
        select(models.Task).filter(models.Task.task_id == task_id)
    )
    db_task = result.scalars().first()

    if db_task:
        db_task.status = status
        db_task.results = (
            _sanitize_json_payload(results) if results is not None else None
        )
        db_task.error_message = error_message
        db_task.completed_at = datetime.now(timezone.utc)
        await db.commit()
        await db.refresh(db_task)

    return db_task


async def get_tasks_by_user(
    db: AsyncSession, user_id: int, skip: int = 0, limit: int = 10
) -> Tuple[List[models.Task], int]:
    """
    Gets a paginated list of tasks for a user.
    """
    # Query for the total count
    count_query = select(func.count(models.Task.id)).filter(
        models.Task.user_id == user_id
    )
    total_count_result = await db.execute(count_query)
    total_count = total_count_result.scalar_one()

    # Query for the paginated tasks
    tasks_query = (
        select(models.Task)
        .filter(models.Task.user_id == user_id)
        .order_by(desc(models.Task.submitted_at))
        .offset(skip)
        .limit(limit)
    )
    tasks_result = await db.execute(tasks_query)
    tasks = tasks_result.scalars().all()

    return tasks, total_count


# BacktestRun CRUD
async def create_backtest_run(
    db: AsyncSession,
    user_id: int,
    task_id: str,
    run_data: schemas.BacktestRunRequest,
    initial_balance: float,
) -> models.BacktestRun:
    parameters_json = (run_data.params or {}).copy()
    if run_data.name and not parameters_json.get("name"):
        parameters_json["name"] = run_data.name

    db_run = models.BacktestRun(
        id=str(uuid.uuid4()),
        user_id=user_id,
        task_id=task_id,
        strategy_name=run_data.strategy_name,
        symbol=run_data.symbol,
        market_type=run_data.market_type,
        start_date=datetime.fromisoformat(run_data.start_date.rstrip("Z")),
        end_date=datetime.fromisoformat(run_data.end_date.rstrip("Z")),
        initial_balance=initial_balance,
        parameters_json=parameters_json,
        status="PENDING",
    )
    db.add(db_run)
    return db_run


# --- StrategyConfig CRUD ---


async def create_strategy_config(
    db: AsyncSession, user_id: int, config_create: schemas.StrategyConfigCreate
) -> models.StrategyConfig:
    db_config = models.StrategyConfig(
        **config_create.model_dump(), user_id=user_id, id=str(uuid.uuid4())
    )
    db.add(db_config)
    await db.flush()
    return db_config


async def get_strategy_configs_by_user(
    db: AsyncSession, user_id: int
) -> List[models.StrategyConfig]:
    result = await db.execute(
        select(models.StrategyConfig)
        .filter(models.StrategyConfig.user_id == user_id)
        .order_by(models.StrategyConfig.name)
    )
    return result.scalars().all()


async def get_strategy_config(
    db: AsyncSession, user_id: int, config_id: str
) -> Optional[models.StrategyConfig]:
    result = await db.execute(
        select(models.StrategyConfig).filter(
            models.StrategyConfig.id == config_id,
            models.StrategyConfig.user_id == user_id,
        )
    )
    return result.scalars().first()


async def get_strategy_config_by_id(
    db: AsyncSession, config_id: str
) -> Optional[models.StrategyConfig]:
    result = await db.execute(
        select(models.StrategyConfig).filter(models.StrategyConfig.id == config_id)
    )
    return result.scalars().first()


async def update_strategy_config(
    db: AsyncSession,
    user_id: int,
    config_id: str,
    config_update: schemas.StrategyConfigUpdate,
) -> Optional[models.StrategyConfig]:
    db_config = await get_strategy_config(db, user_id, config_id)
    if db_config:
        update_data = config_update.model_dump(exclude_unset=True)
        for key, value in update_data.items():
            setattr(db_config, key, value)

        if "config_data" in update_data and update_data["config_data"] is not None:
            flag_modified(db_config, "config_data")

        if (
            "foundation_weights" in update_data
            and update_data["foundation_weights"] is not None
        ):
            flag_modified(db_config, "foundation_weights")

        await db.flush()
    return db_config


async def delete_strategy_config(
    db: AsyncSession, user_id: int, config_id: str
) -> Optional[models.StrategyConfig]:
    db_config = await get_strategy_config(db, user_id, config_id)
    if db_config:
        # Explicitly nullify foreign keys in related tables to avoid ForeignKeyViolationError
        # This is necessary because the ON DELETE SET NULL constraint may not be applied in the database
        await db.execute(
            update(models.Trade)
            .where(models.Trade.strategy_config_id == config_id)
            .values(strategy_config_id=None)
        )
        await db.execute(
            update(models.TradeAnalytics)
            .where(models.TradeAnalytics.strategy_config_id == config_id)
            .values(strategy_config_id=None)
        )
        await db.execute(
            update(models.UserGene)
            .where(models.UserGene.source_strategy_id == config_id)
            .values(source_strategy_id=None)
        )
        # Also nullify parent_strategy_id in child strategy configs
        await db.execute(
            update(models.StrategyConfig)
            .where(models.StrategyConfig.parent_strategy_id == config_id)
            .values(parent_strategy_id=None)
        )
        await db.delete(db_config)
        await db.flush()
    return db_config


async def update_backtest_run_status(
    db: AsyncSession, run_id: str, status: str, error_message: Optional[str] = None
):
    result = await db.execute(
        select(models.BacktestRun).filter(models.BacktestRun.id == run_id)
    )
    db_run = result.scalars().first()
    if db_run:
        db_run.status = status
        if status in ["COMPLETED", "FAILED"]:
            db_run.completed_at = datetime.now(timezone.utc)
        if error_message:
            db_run.error_message = error_message
        await db.commit()
    return db_run


async def update_backtest_run_results(
    db: AsyncSession,
    run_id: str,
    kpi_results: Optional[dict] = None,
    equity_curve: Optional[list] = None,
    analytics_report: Optional[dict] = None,
):
    result = await db.execute(
        select(models.BacktestRun).filter(models.BacktestRun.id == run_id)
    )
    db_run = result.scalars().first()
    if db_run:
        db_run.status = "COMPLETED"
        db_run.completed_at = datetime.now(timezone.utc)
        if kpi_results:
            db_run.kpi_results_json = _sanitize_json_payload(kpi_results)
        if equity_curve:
            db_run.equity_curve_json = _sanitize_json_payload(equity_curve)
        if analytics_report:
            db_run.analytics_report_json = _sanitize_json_payload(analytics_report)
        await db.commit()
    return db_run


async def get_all_backtest_runs_for_user(
    db: AsyncSession, user_id: int
) -> List[models.BacktestRun]:
    result = await db.execute(
        select(models.BacktestRun)
        .filter(models.BacktestRun.user_id == user_id)
        .order_by(desc(models.BacktestRun.created_at))
    )
    return result.scalars().all()


async def get_backtest_run_with_trades(db: AsyncSession, user_id: int, run_id: str):
    result = await db.execute(
        select(models.BacktestRun)
        .options(
            selectinload(models.BacktestRun.trades),
            _visible_backtest_trade_loader_option(),
        )
        .where(models.BacktestRun.id == run_id, models.BacktestRun.user_id == user_id)
    )
    return result.scalar_one_or_none()


async def delete_backtest_run(db: AsyncSession, user_id: int, task_id_to_delete: str):
    task_result = await db.execute(
        select(models.Task).where(
            models.Task.task_id == task_id_to_delete, models.Task.user_id == user_id
        )
    )
    task_to_delete = task_result.scalar_one_or_none()

    if not task_to_delete:
        logging.warning(
            f"No Task found with task_id '{task_id_to_delete}' for user {user_id}. Cannot delete."
        )
        return None

    run_result = await db.execute(
        select(models.BacktestRun).where(
            models.BacktestRun.task_id == task_to_delete.task_id,
            models.BacktestRun.user_id == user_id,
        )
    )
    run_to_delete = run_result.scalar_one_or_none()

    if run_to_delete:
        logging.info(
            f"Deleting associated BacktestRun (ID: {run_to_delete.id}) for task {task_to_delete.task_id}."
        )
        await db.delete(run_to_delete)

    logging.info(f"Deleting Task record with task_id: {task_to_delete.task_id}.")
    await db.delete(task_to_delete)

    return task_to_delete


async def create_genetic_run(
    db: AsyncSession,
    user_id: int,
    config_json: dict,
    initial_status: str = "PENDING",
    celery_task_id: Optional[str] = None,
) -> models.GeneticRun:
    db_run = models.GeneticRun(
        id=str(uuid.uuid4()),
        user_id=user_id,
        config_json=config_json,
        status=initial_status,
        created_at=datetime.now(timezone.utc),
    )
    if celery_task_id:
        db_run.celery_task_id = celery_task_id
    db.add(db_run)
    await db.flush()
    return db_run


async def get_genetic_run(
    db: AsyncSession, run_id: str, user_id: int
) -> Optional[models.GeneticRun]:
    result = await db.execute(
        select(models.GeneticRun).filter(
            models.GeneticRun.id == run_id, models.GeneticRun.user_id == user_id
        )
    )
    return result.scalars().first()


async def get_genetic_runs_for_user(
    db: AsyncSession, user_id: int, skip: int = 0, limit: int = 100
) -> List[models.GeneticRun]:
    result = await db.execute(
        select(models.GeneticRun)
        .filter(models.GeneticRun.user_id == user_id)
        .order_by(desc(models.GeneticRun.created_at))
        .offset(skip)
        .limit(limit)
    )
    return result.scalars().all()


async def update_genetic_run_status(
    db: AsyncSession,
    run_id: str,
    status: str,
    error_message: Optional[str] = None,
    celery_task_id: Optional[str] = None,
    progress_data: Optional[dict] = None,
) -> Optional[models.GeneticRun]:
    db_run = await db.get(models.GeneticRun, run_id)
    if not db_run:
        result = await db.execute(
            select(models.GeneticRun).filter(models.GeneticRun.id == run_id)
        )
        db_run = result.scalars().first()

    if db_run:
        db_run.status = status
        if status == "RUNNING" and not db_run.started_at:
            db_run.started_at = datetime.now(timezone.utc)
        if status in ["COMPLETED", "FAILED", "STOPPED"]:
            db_run.completed_at = datetime.now(timezone.utc)
        if error_message:
            db_run.error_message = error_message
        if celery_task_id:
            db_run.celery_task_id = celery_task_id
        if progress_data:
            if db_run.progress is None:
                db_run.progress = progress_data
            else:
                db_run.progress.update(progress_data)
            orm_attributes.flag_modified(db_run, "progress")
        await db.flush()
    return db_run


async def update_genetic_run_progress(
    db: AsyncSession, run_id: str, progress_data: dict
) -> Optional[models.GeneticRun]:
    db_run = await db.get(models.GeneticRun, run_id)
    if not db_run:
        result = await db.execute(
            select(models.GeneticRun).filter(models.GeneticRun.id == run_id)
        )
        db_run = result.scalars().first()

    if db_run:
        if db_run.progress is None:
            db_run.progress = progress_data
        else:
            db_run.progress.update(progress_data)
        orm_attributes.flag_modified(db_run, "progress")
        await db.flush()
    return db_run


# --- FoundStrategy CRUD ---


async def create_found_strategy(
    db: AsyncSession,
    genetic_run_id: str,
    rank: int,
    strategy_json: dict,
    fitness_score: float,
    kpis_json: dict,
) -> models.FoundStrategy:
    db_found_strategy = models.FoundStrategy(
        id=str(uuid.uuid4()),
        run_id=genetic_run_id,
        rank=rank,
        strategy_json=strategy_json,
        fitness_score=fitness_score,
        kpis_json=kpis_json,
        created_at=datetime.now(timezone.utc),
    )
    db.add(db_found_strategy)
    await db.flush()
    return db_found_strategy


async def get_found_strategies_for_run(
    db: AsyncSession, run_id: str, skip: int = 0, limit: int = 10
) -> List[models.FoundStrategy]:
    result = await db.execute(
        select(models.FoundStrategy)
        .filter(models.FoundStrategy.run_id == run_id)
        .order_by(models.FoundStrategy.rank)
        .offset(skip)
        .limit(limit)
    )
    return result.scalars().all()


# --- DatasetRun CRUD ---


async def create_dataset_run(
    db: AsyncSession,
    user_id: int,
    run_create: schemas.DatasetRunCreate,
    celery_task_id: str,
) -> models.DatasetRun:
    db_run = models.DatasetRun(
        id=str(uuid.uuid4()),
        name=run_create.name,
        user_id=user_id,
        celery_task_id=celery_task_id,
        parameters_json=run_create.model_dump(),
        status="QUEUED",
    )
    db.add(db_run)
    await db.flush()
    return db_run


async def get_dataset_run(
    db: AsyncSession, user_id: int, run_id: str
) -> Optional[models.DatasetRun]:
    result = await db.execute(
        select(models.DatasetRun).filter(
            models.DatasetRun.id == run_id, models.DatasetRun.user_id == user_id
        )
    )
    return result.scalars().first()


async def get_dataset_runs_by_user(
    db: AsyncSession, user_id: int
) -> List[models.DatasetRun]:
    result = await db.execute(
        select(models.DatasetRun)
        .filter(models.DatasetRun.user_id == user_id)
        .order_by(desc(models.DatasetRun.created_at))
    )
    return result.scalars().all()


async def delete_dataset_run(
    db: AsyncSession, user_id: int, run_id: str
) -> Optional[models.DatasetRun]:
    db_run = await get_dataset_run(db, user_id=user_id, run_id=run_id)
    if db_run:
        await db.delete(db_run)
        await db.flush()
    return db_run


# --- TrainingRun CRUD ---


async def create_training_run(
    db: AsyncSession,
    user_id: int,
    run_create: schemas.TrainingRunCreate,
    celery_task_id: str,
) -> models.TrainingRun:
    dataset = await get_dataset_run(db, user_id=user_id, run_id=run_create.dataset_id)
    if not dataset:
        raise ValueError("Dataset not found or does not belong to the user.")
    if dataset.status != "COMPLETED":
        raise ValueError("Cannot start training on a dataset that is not completed.")

    db_run = models.TrainingRun(
        id=str(uuid.uuid4()),
        user_id=user_id,
        dataset_id=run_create.dataset_id,
        celery_task_id=celery_task_id,
        parameters_json=run_create.model_dump(),
        status="QUEUED",
    )
    db.add(db_run)
    await db.flush()
    return db_run


async def get_training_run(
    db: AsyncSession, user_id: int, run_id: str
) -> Optional[models.TrainingRun]:
    result = await db.execute(
        select(models.TrainingRun)
        .options(selectinload(models.TrainingRun.dataset))
        .filter(models.TrainingRun.id == run_id, models.TrainingRun.user_id == user_id)
    )
    return result.scalars().first()


async def get_training_runs_by_user(
    db: AsyncSession, user_id: int
) -> List[models.TrainingRun]:
    result = await db.execute(
        select(models.TrainingRun)
        .options(selectinload(models.TrainingRun.dataset))
        .filter(models.TrainingRun.user_id == user_id)
        .order_by(desc(models.TrainingRun.created_at))
    )
    return result.scalars().all()


async def delete_training_run(
    db: AsyncSession, user_id: int, run_id: str
) -> Optional[models.TrainingRun]:
    db_run = await get_training_run(db, user_id=user_id, run_id=run_id)
    if db_run:
        await db.delete(db_run)
        await db.flush()
    return db_run


async def get_backtest_run_by_any_id(db: AsyncSession, user_id: int, identity: str):
    result = await db.execute(
        select(models.BacktestRun)
        .options(
            selectinload(models.BacktestRun.trades),
            _visible_backtest_trade_loader_option(),
        )
        .where(models.BacktestRun.id == identity, models.BacktestRun.user_id == user_id)
    )
    run = result.scalar_one_or_none()
    if run:
        return run

    result = await db.execute(
        select(models.BacktestRun)
        .options(
            selectinload(models.BacktestRun.trades),
            _visible_backtest_trade_loader_option(),
        )
        .where(
            models.BacktestRun.task_id == identity,
            models.BacktestRun.user_id == user_id,
        )
    )
    return result.scalar_one_or_none()


async def create_trade_analytics(
    db: AsyncSession, trade_analytics: schemas.TradeAnalyticsCreate
) -> models.TradeAnalytics:
    db_trade_analytics = models.TradeAnalytics(**trade_analytics.model_dump())
    db.add(db_trade_analytics)
    await db.flush()
    await db.refresh(db_trade_analytics)
    return db_trade_analytics


async def get_foundation_effectiveness_stats(db: AsyncSession, source_type: str):
    """
    Get foundation effectiveness statistics for a given source type.

    Uses SQLAlchemy ORM for database compatibility (works with both PostgreSQL and SQLite).
    JSON array processing is done in Python to avoid database-specific syntax.
    """
    from collections import defaultdict

    # Fetch all trade analytics records for the source type
    query = select(models.TradeAnalytics).where(
        models.TradeAnalytics.source_type == source_type
    )
    result = await db.execute(query)
    trades = result.scalars().all()

    # Aggregate stats by foundation_id in Python
    foundation_stats = defaultdict(
        lambda: {
            "count": 0,
            "win_rate_contributions": [],
            "gross_profit": 0,
            "gross_loss": 0,
        }
    )

    for trade in trades:
        try:
            # Get foundations from trade, default to __no_foundation__ if empty
            foundations = trade.used_foundations

            # Check if foundations is a string (sometimes happens with some DB configs)
            if isinstance(foundations, str):
                import json

                try:
                    foundations = json.loads(foundations)
                except Exception:
                    foundations = [
                        foundations
                    ]  # Treat as single string if not valid JSON

            if not foundations:
                foundations = ["__no_foundation__"]

            # Ensure it's a list for iteration
            if not isinstance(foundations, list):
                foundations = [str(foundations)]

            for foundation_id in foundations:
                stats = foundation_stats[foundation_id]
                stats["count"] += 1
                stats["win_rate_contributions"].append(trade.win_rate_contribution or 0)
                stats["gross_profit"] += trade.profit_factor_gross_profit or 0
                stats["gross_loss"] += trade.profit_factor_gross_loss or 0
        except Exception as e:
            import logging

            logger = logging.getLogger(__name__)
            logger.error(
                f"Error processing stats for trade_analytics record {getattr(trade, 'id', 'unknown')}: {e}"
            )
            continue

    # Convert to output format
    result_stats = []
    for foundation_id, data in foundation_stats.items():
        total_gross_loss = data["gross_loss"]
        total_gross_profit = data["gross_profit"]

        # Calculate profit factor
        if total_gross_loss > 0:
            profit_factor = total_gross_profit / total_gross_loss
        elif total_gross_profit > 0:
            profit_factor = (
                9999  # Arbitrary large number to represent high profitability
            )
        else:
            profit_factor = 0

        # Calculate average win rate contribution
        win_rate_contribs = data["win_rate_contributions"]
        avg_win_rate_contribution = (
            sum(win_rate_contribs) / len(win_rate_contribs) if win_rate_contribs else 0
        )

        result_stats.append(
            {
                "foundation_id": foundation_id,
                "count": data["count"],
                "avg_win_rate_contribution": avg_win_rate_contribution,
                "total_gross_profit": total_gross_profit,
                "total_gross_loss": total_gross_loss,
                "profit_factor": profit_factor,
            }
        )

    # Sort by count descending
    result_stats.sort(key=lambda x: x["count"], reverse=True)
    return result_stats


async def get_market_sentiment(db: AsyncSession, source_type: str):
    query = (
        select(
            models.TradeAnalytics.direction,
            func.sum(models.TradeAnalytics.pnl_usd).label("total_pnl"),
        )
        .where(models.TradeAnalytics.source_type == source_type)
        .group_by(models.TradeAnalytics.direction)
    )
    result = await db.execute(query)
    rows = result.all()
    return [{"direction": row.direction, "total_pnl": row.total_pnl} for row in rows]


async def get_backtest_run(
    db: AsyncSession, run_id: str, user_id: int
) -> Optional[models.BacktestRun]:
    result = await db.execute(
        select(models.BacktestRun)
        .options(
            selectinload(models.BacktestRun.trades),
            _visible_backtest_trade_loader_option(),
        )
        .filter(models.BacktestRun.id == run_id, models.BacktestRun.user_id == user_id)
    )
    return result.scalars().first()


async def create_leaderboard_entry(
    db: AsyncSession,
    user_id: int,
    backtest_run: models.BacktestRun,
    shared_backtest_slug: str,
):
    """
    Creates or updates a record in LeaderboardEntry for all periods and categories.
    A periodic task will update 'rank' later.
    """
    kpis = backtest_run.kpi_results_json
    if not kpis:
        return  # Cannot create entry without KPI

    # Determine categories and their corresponding values from KPI
    categories_scores = {
        "sharpe_ratio": kpis.get("sharpe_ratio"),
        "net_pnl_percent": (kpis.get("total_pnl", 0) / backtest_run.initial_balance)
        * 100,
    }

    # Determine periods (for MVP can start with 'all_time')
    periods = [models.LeaderboardPeriod.ALL_TIME]
    # TODO: In the future add logic for weekly/monthly based on backtest created_at

    # Meta-data for rendering in the table
    meta_data = {
        "pnl": kpis.get("total_pnl"),
        "win_rate": kpis.get("win_rate"),
        "trades": kpis.get("trades"),
        "symbol": backtest_run.symbol,
    }

    for period in periods:
        for category, score in categories_scores.items():
            if score is None:
                continue

            # Search for existing record for this backtest
            result = await db.execute(
                select(models.LeaderboardEntry).filter_by(
                    backtest_run_id=backtest_run.id, period=period, category=category
                )
            )
            existing_entry = result.scalars().first()

            if existing_entry:
                # Update if the record already exists
                existing_entry.score = score
                existing_entry.meta_data = meta_data
                existing_entry.shared_backtest_slug = shared_backtest_slug
            else:
                # Create a new record
                new_entry = models.LeaderboardEntry(
                    user_id=user_id,
                    backtest_run_id=backtest_run.id,
                    shared_backtest_slug=shared_backtest_slug,
                    period=period,
                    category=category,
                    score=score,
                    rank=0,  # Rank will be assigned later
                    meta_data=meta_data,
                )
                db.add(new_entry)

    await db.flush()


# --- SharedBacktest CRUD ---


async def get_shared_backtest_by_slug(
    db: AsyncSession, public_slug: str
) -> Optional[models.SharedBacktest]:
    """Retrieves SharedBacktest object by its public identifier (slug)."""
    result = await db.execute(
        select(models.SharedBacktest)
        .options(selectinload(models.SharedBacktest.backtest_run))
        .filter(
            models.SharedBacktest.public_slug == public_slug,
            models.SharedBacktest.is_active,
        )
    )
    return result.scalars().first()


async def get_shared_backtest_by_run_id(
    db: AsyncSession, run_id: str, user_id: int
) -> Optional[models.SharedBacktest]:
    """Retrieves active SharedBacktest object for a specific backtest run."""
    result = await db.execute(
        select(models.SharedBacktest).filter(
            models.SharedBacktest.backtest_run_id == run_id,
            models.SharedBacktest.user_id == user_id,
            models.SharedBacktest.is_active,
        )
    )
    return result.scalars().first()


async def create_or_update_shared_backtest(
    db: AsyncSession, run_id: str, user_id: int, settings: schemas.ShareCreate
) -> models.SharedBacktest:
    """Creates new or updates existing public link for backtest."""
    # 1. Check if an active link already exists
    existing_share = await get_shared_backtest_by_run_id(
        db, run_id=run_id, user_id=user_id
    )

    if existing_share:
        # 2. If it exists - update privacy settings
        existing_share.is_strategy_name_public = settings.is_strategy_name_public
        existing_share.are_parameters_public = settings.are_parameters_public
        await db.flush()
        await db.refresh(existing_share)
        return existing_share
    else:
        # 3. If it doesn't exist - create a new record
        new_share = models.SharedBacktest(
            backtest_run_id=run_id,
            user_id=user_id,
            is_strategy_name_public=settings.is_strategy_name_public,
            are_parameters_public=settings.are_parameters_public,
            # public_slug, created_at, is_active are generated by default
        )
        db.add(new_share)
        await db.flush()
        await db.refresh(new_share)
        return new_share


# --- PaperWallet CRUD ---


async def get_paper_wallet(db: AsyncSession, user_id: int) -> List[models.PaperWallet]:
    """
    Gets all paper wallet balances for a user.
    """
    result = await db.execute(
        select(models.PaperWallet).filter(models.PaperWallet.user_id == user_id)
    )
    return result.scalars().all()


async def get_paper_wallet_asset(
    db: AsyncSession, user_id: int, asset: str
) -> Optional[models.PaperWallet]:
    """
    Gets a specific asset from the paper wallet for a user.
    """
    result = await db.execute(
        select(models.PaperWallet).filter(
            models.PaperWallet.user_id == user_id,
            models.PaperWallet.asset == asset.upper(),
        )
    )
    return result.scalars().first()


async def update_paper_wallet_balance(
    db: AsyncSession, user_id: int, asset: str, amount_change: float
) -> models.PaperWallet:
    """
    Updates the balance of a specific asset in the paper wallet by a certain amount (delta).
    If the asset does not exist, it creates it with the specified amount.
    """
    wallet_asset = await get_paper_wallet_asset(db, user_id, asset)

    if not wallet_asset:
        # If asset doesn't exist, create it
        wallet_asset = models.PaperWallet(
            user_id=user_id, asset=asset.upper(), balance=amount_change
        )
        db.add(wallet_asset)
    else:
        # If it exists, update the balance
        wallet_asset.balance += amount_change

    await db.flush()
    await db.refresh(wallet_asset)
    return wallet_asset


async def init_or_reset_paper_wallet(
    db: AsyncSession, user_id: int, initial_balance: Optional[float] = None
) -> List[models.PaperWallet]:
    """
    Creates or resets the paper wallet for a user to the initial balance.
    Deletes existing wallet entries for the user and creates a new one for USDT.
    """
    # Use provided initial_balance or fall back to config
    balance_to_set = (
        initial_balance
        if initial_balance is not None
        else PAPER_TRADING_INITIAL_BALANCE
    )

    # Delete existing wallet entries for the user
    await db.execute(
        delete(models.PaperWallet).where(models.PaperWallet.user_id == user_id)
    )
    await db.flush()  # Ensure deletes are processed before adds

    # Create a new wallet with the initial USDT balance
    new_wallet = models.PaperWallet(
        user_id=user_id, asset="USDT", balance=balance_to_set
    )
    db.add(new_wallet)
    await db.flush()

    # Return all wallet assets for the user (which will be just the one we created)
    return await get_paper_wallet(db, user_id)


async def get_leaderboard(
    db: AsyncSession, period: models.LeaderboardPeriod, category: str, limit: int = 100
) -> List[models.LeaderboardEntry]:
    """
    Gets leaderboard entries for a given period and category.
    """
    result = await db.execute(
        select(models.LeaderboardEntry)
        .options(
            selectinload(models.LeaderboardEntry.user),
            selectinload(models.LeaderboardEntry.shared_backtest),
        )
        .filter(
            models.LeaderboardEntry.period == period,
            models.LeaderboardEntry.category == category,
        )
        .order_by(desc(models.LeaderboardEntry.score))
        .limit(limit)
    )
    return result.scalars().all()


async def delete_leaderboard_entry(db: AsyncSession, entry_id: str) -> bool:
    """
    Deletes a leaderboard entry by its ID.
    """
    result = await db.execute(
        select(models.LeaderboardEntry).filter(models.LeaderboardEntry.id == entry_id)
    )
    entry = result.scalar_one_or_none()
    if not entry:
        return False

    await db.delete(entry)
    await db.commit()
    return True


async def get_achievements(db: AsyncSession) -> List[models.Achievement]:
    """
    Gets all achievements.
    """
    result = await db.execute(select(models.Achievement))
    return result.scalars().all()


async def get_user_achievements(
    db: AsyncSession, user_id: int
) -> List[models.UserAchievement]:
    """
    Gets user's achievements.
    """
    result = await db.execute(
        select(models.UserAchievement)
        .options(selectinload(models.UserAchievement.achievement))
        .filter(models.UserAchievement.user_id == user_id)
    )
    return result.scalars().all()


# === Genome Project CRUD ===


async def get_user_genes(
    db: AsyncSession, user_id: int, limit: int = 100, offset: int = 0
):
    """Get all genes discovered by a user with pagination."""
    result = await db.execute(
        select(models.UserGene, models.Gene)
        .join(models.Gene, models.UserGene.gene_id == models.Gene.id)
        .where(models.UserGene.user_id == user_id)
        .order_by(models.UserGene.unlocked_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return result.all()


async def count_user_genes(db: AsyncSession, user_id: int) -> int:
    """Count total genes discovered by user."""
    result = await db.execute(
        select(func.count(models.UserGene.id)).where(models.UserGene.user_id == user_id)
    )
    return result.scalar_one()


async def get_total_genes_in_system(db: AsyncSession) -> int:
    """Get total number of unique genes in the system."""
    result = await db.execute(select(func.count(models.Gene.id)))
    return result.scalar_one()


async def get_user_genes_by_rarity(db: AsyncSession, user_id: int):
    """Get breakdown of user's genes by rarity tier."""
    result = await db.execute(
        select(models.Gene.rarity, func.count(models.UserGene.id))
        .join(models.UserGene, models.Gene.id == models.UserGene.gene_id)
        .where(models.UserGene.user_id == user_id)
        .group_by(models.Gene.rarity)
    )

    breakdown = {"COMMON": 0, "RARE": 0, "EPIC": 0, "LEGENDARY": 0}
    for rarity, count in result.all():
        if rarity < 1.0:
            breakdown["LEGENDARY"] += count
        elif rarity < 5.0:
            breakdown["EPIC"] += count
        elif rarity < 20.0:
            breakdown["RARE"] += count
        else:
            breakdown["COMMON"] += count

    return breakdown


async def get_recent_user_genes(db: AsyncSession, user_id: int, limit: int = 5):
    """Get user's most recently discovered genes."""
    result = await db.execute(
        select(models.UserGene, models.Gene)
        .join(models.Gene, models.UserGene.gene_id == models.Gene.id)
        .where(models.UserGene.user_id == user_id)
        .order_by(models.UserGene.unlocked_at.desc())
        .limit(limit)
    )
    return result.all()


# ==============================================================================
# EVOLUTION TREE FUNCTIONS
# ==============================================================================


async def get_root_strategies(db: AsyncSession, user_id: int):
    """Get all root strategies (strategies without parents) for user."""
    result = await db.execute(
        select(models.StrategyConfig)
        .options(selectinload(models.StrategyConfig.children))
        .where(
            models.StrategyConfig.user_id == user_id,
            models.StrategyConfig.parent_strategy_id.is_(None),
        )
        .order_by(models.StrategyConfig.created_at.desc())
    )
    return result.scalars().all()


async def get_strategy_lineage(db: AsyncSession, user_id: int, strategy_id: str):
    """
    Get complete lineage (ancestors and descendants) for a strategy using recursive CTE.
    Returns dict with nodes and edges for visualization.
    """
    from sqlalchemy import text

    # First verify the strategy belongs to the user
    verify_result = await db.execute(
        select(models.StrategyConfig).where(
            models.StrategyConfig.id == strategy_id,
            models.StrategyConfig.user_id == user_id,
        )
    )
    root_strategy = verify_result.scalar_one_or_none()
    if not root_strategy:
        return None

    # Find the actual root of this lineage (ancestor with no parent)
    current = root_strategy
    while current.parent_strategy_id:
        parent_result = await db.execute(
            select(models.StrategyConfig).where(
                models.StrategyConfig.id == current.parent_strategy_id,
                models.StrategyConfig.user_id == user_id,
            )
        )
        parent = parent_result.scalar_one_or_none()
        if not parent:
            break
        current = parent

    lineage_root_id = current.id

    # Use recursive CTE to get all descendants from the lineage root
    query = text("""
        WITH RECURSIVE strategy_tree AS (
            -- Base case: start with the root
            SELECT id, name, parent_strategy_id, generation, source_mutation, created_at
            FROM strategy_configs
            WHERE id = :root_id AND user_id = :user_id
            
            UNION ALL
            
            -- Recursive case: get children
            SELECT sc.id, sc.name, sc.parent_strategy_id, sc.generation, sc.source_mutation, sc.created_at
            FROM strategy_configs sc
            INNER JOIN strategy_tree st ON sc.parent_strategy_id = st.id
            WHERE sc.user_id = :user_id
        )
        SELECT * FROM strategy_tree
        ORDER BY generation, created_at
    """)

    result = await db.execute(query, {"root_id": lineage_root_id, "user_id": user_id})
    rows = result.fetchall()

    # Build nodes and edges
    nodes = []
    edges = []

    for row in rows:
        node = {
            "id": row.id,
            "name": row.name,
            "generation": row.generation,
            "source_mutation": row.source_mutation,
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "is_current": row.id == strategy_id,
        }
        nodes.append(node)

        if row.parent_strategy_id:
            edge = {"from": row.parent_strategy_id, "to": row.id}
            edges.append(edge)

    return {"nodes": nodes, "edges": edges, "root_id": lineage_root_id}


# --- AI Chat CRUD ---


async def create_chat_message(
    db: AsyncSession, user_id: int, message_data: schemas.AIChatMessageCreate
) -> models.AIChatMessage:
    """
    Creates and saves a new AI chat message to the database.
    """
    logger.info(
        f"Creating chat message for user {user_id}, session {message_data.session_id}, role {message_data.role}"
    )
    db_message = models.AIChatMessage(
        user_id=user_id,
        session_id=message_data.session_id,
        role=message_data.role,
        content=message_data.content,
        image_base64=message_data.image_base64,
        image_mime_type=message_data.image_mime_type,
        created_at=datetime.now(timezone.utc),
    )

    db.add(db_message)
    await db.flush()
    await db.refresh(db_message)
    logger.info(f"Chat message created with ID: {db_message.id}")
    return db_message


async def get_chat_history(
    db: AsyncSession, user_id: int, session_id: str, limit: int = 50
) -> List[models.AIChatMessage]:
    """
    Retrieves the chat history for a specific user and session.
    """
    logger.info(f"Retrieving chat history for user {user_id}, session {session_id}")
    result = await db.execute(
        select(models.AIChatMessage)
        .filter(
            models.AIChatMessage.user_id == user_id,
            models.AIChatMessage.session_id == session_id,
        )
        .order_by(models.AIChatMessage.created_at.asc(), models.AIChatMessage.id.asc())
        .limit(limit)
    )
    messages = result.scalars().all()
    logger.info(f"Retrieved {len(messages)} messages from chat history")
    return messages


async def get_latest_chat_session_id(db: AsyncSession, user_id: int) -> Optional[str]:
    """
    Retrieves the session_id of the most recent chat message for a user.
    Returns None if no messages exist.
    """
    logger.info(f"Retrieving latest session ID for user {user_id}")
    result = await db.execute(
        select(models.AIChatMessage.session_id)
        .filter(models.AIChatMessage.user_id == user_id)
        .order_by(models.AIChatMessage.created_at.desc())
        .limit(1)
    )
    session_id = result.scalar_one_or_none()
    if session_id:
        logger.info(f"Latest session ID for user {user_id}: {session_id}")
    else:
        logger.info(f"No chat history found for user {user_id}")
    return session_id


async def delete_chat_session(db: AsyncSession, user_id: int, session_id: str) -> int:
    """
    Deletes all messages for a specific chat session and returns the number of deleted messages.
    """
    result = await db.execute(
        delete(models.AIChatMessage).where(
            models.AIChatMessage.user_id == user_id,
            models.AIChatMessage.session_id == session_id,
        )
    )
    # Do not call commit, so endpoint can manage transaction
    await db.flush()
    return result.rowcount


async def update_user_telegram_chat_id(
    db: AsyncSession, user_id: int, chat_id: str, username: Optional[str] = None
):
    """Updates the telegramChatId and telegramEnabled in user's NotificationSettings."""
    from sqlalchemy.orm import attributes as orm_attributes

    result = await db.execute(
        select(models.AppConfig).filter(models.AppConfig.user_id == user_id)
    )
    db_config = result.scalars().first()
    if not db_config:
        return None

    notifications = db_config.notifications or {}
    notifications["telegramChatId"] = str(chat_id)
    notifications["telegramEnabled"] = True
    if username:
        notifications["telegramUsername"] = username

    db_config.notifications = notifications
    orm_attributes.flag_modified(db_config, "notifications")
    await db.flush()
    return db_config


async def create_hub_feedback(
    db: AsyncSession,
    feedback_data: schemas.HubFeedbackCreate,
    ip_address: Optional[str] = None,
) -> models.HubFeedback:
    db_feedback = models.HubFeedback(
        category=feedback_data.category,
        text=feedback_data.text,
        contact_email=feedback_data.contact_email,
        ip_address=ip_address,
    )
    db.add(db_feedback)
    await db.flush()
    return db_feedback


async def create_hub_topic(
    db: AsyncSession, topic_data: schemas.HubTopicCreate
) -> models.HubTopic:
    db_topic = models.HubTopic(
        topic_type=topic_data.topic_type,
        title=topic_data.title,
        description=topic_data.description,
        author_name=topic_data.author_name,
        symbol=topic_data.symbol,
        period_start=topic_data.period_start,
        period_end=topic_data.period_end,
        kpis=topic_data.kpis,
        equity_curve=topic_data.equity_curve,
        strategy_json=topic_data.strategy_json,
        tags=topic_data.tags,
        is_verified=False,
        delete_token=str(uuid.uuid4()),
    )
    db.add(db_topic)
    await db.flush()
    db_topic.comments_count = 0
    return db_topic


async def get_hub_topics(
    db: AsyncSession, topic_type: Optional[str] = None
) -> List[models.HubTopic]:
    stmt = select(models.HubTopic)
    if topic_type:
        stmt = stmt.filter(models.HubTopic.topic_type == topic_type)
    stmt = stmt.order_by(desc(models.HubTopic.created_at))
    result = await db.execute(stmt)
    topics = list(result.scalars().all())
    if topics:
        topic_ids = [t.id for t in topics]
        count_stmt = (
            select(models.HubComment.topic_id, func.count(models.HubComment.id))
            .filter(models.HubComment.topic_id.in_(topic_ids))
            .group_by(models.HubComment.topic_id)
        )
        count_result = await db.execute(count_stmt)
        counts = {row[0]: row[1] for row in count_result.all()}
        for t in topics:
            t.comments_count = counts.get(t.id, 0)
    return topics


async def like_hub_topic(db: AsyncSession, topic_id: str) -> Optional[models.HubTopic]:
    stmt = select(models.HubTopic).filter(models.HubTopic.id == topic_id)
    result = await db.execute(stmt)
    db_topic = result.scalars().first()
    if db_topic:
        db_topic.likes_count = (db_topic.likes_count or 0) + 1
        await db.flush()
        count_stmt = select(func.count(models.HubComment.id)).filter(
            models.HubComment.topic_id == topic_id
        )
        count_result = await db.execute(count_stmt)
        db_topic.comments_count = count_result.scalar() or 0
    return db_topic


async def create_hub_comment(
    db: AsyncSession, topic_id: str, comment_data: schemas.HubCommentCreate
) -> models.HubComment:
    db_comment = models.HubComment(
        topic_id=topic_id,
        author_name=comment_data.author_name,
        text=comment_data.text,
    )
    db.add(db_comment)
    await db.flush()
    return db_comment


async def get_hub_comments(db: AsyncSession, topic_id: str) -> List[models.HubComment]:
    stmt = (
        select(models.HubComment)
        .filter(models.HubComment.topic_id == topic_id)
        .order_by(models.HubComment.created_at.asc())
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def delete_hub_topic(db: AsyncSession, topic_id: str):
    stmt = delete(models.HubTopic).filter(models.HubTopic.id == topic_id)
    await db.execute(stmt)


DEFAULT_STRATEGIES = [
    {
        "name": "Genetic Scalper",
        "author": "DepthSight Team",
        "tags": ["Futures", "Scalping", "1m"],
        "description": "High-frequency scalping strategy optimized via genetic algorithms. Uses RSI and volatility filters for precision entries.",
        "strategy_json": {
            "strategy_name": "GeneticScalp",
            "symbol": "BTCUSDT",
            "marketType": "FUTURES",
            "filters": {
                "type": "AND",
                "children": [
                    {
                        "type": "volatility_filter",
                        "params": {"operator": "gt", "value": 0.0058},
                    }
                ],
            },
            "entryTrigger": {
                "type": "on_candle_close",
                "params": {},
                "timeframe": "1m",
            },
            "entryConditions": {
                "type": "AND",
                "children": [
                    {
                        "type": "rsi_condition",
                        "params": {"period": 6, "operator": "cross_below", "value": 20},
                    }
                ],
            },
            "initialization": {
                "type": "open_position",
                "params": {
                    "direction": "LONG",
                    "sl_type": "atr_multiplier",
                    "sl_value_atr": 1.45,
                    "tp_type": "rr_multiplier",
                    "tp_value_rr": 2.8,
                    "move_sl_to_be_on_first_tp": True,
                    "sim_trailing_pct": 0.0012,
                    "sim_breakeven_rr": 0.95,
                    "max_hold_candles": 200,
                },
            },
            "positionManagement": [],
        },
    },
    {
        "name": "EMA Trend Rider",
        "author": "DepthSight Team",
        "tags": ["Spot", "Trend", "5m"],
        "description": "Trend-following strategy designed for spot markets. Rides medium-term trends using Exponential Moving Averages.",
        "strategy_json": {
            "strategy_name": "EmaTrend",
            "symbol": "ETHUSDT",
            "marketType": "SPOT",
            "filters": {"type": "AND", "children": []},
            "entryTrigger": {
                "type": "on_candle_close",
                "params": {},
                "timeframe": "5m",
            },
            "entryConditions": {
                "type": "AND",
                "children": [
                    {
                        "type": "ema_crossover",
                        "params": {
                            "fast_period": 9,
                            "slow_period": 21,
                            "operator": "above",
                        },
                    }
                ],
            },
            "initialization": {
                "type": "open_position",
                "params": {
                    "direction": "LONG",
                    "sl_type": "percentage",
                    "sl_value_pct": 2.5,
                    "tp_type": "percentage",
                    "tp_value_pct": 7.5,
                    "move_sl_to_be_on_first_tp": False,
                },
            },
            "positionManagement": [],
        },
    },
    {
        "name": "RSI Rebounder",
        "author": "DepthSight Team",
        "tags": ["Futures", "Mean Reversion", "15m"],
        "description": "Mean reversion strategy identifying oversold and overbought conditions on 15m charts.",
        "strategy_json": {
            "strategy_name": "RsiRebound",
            "symbol": "SOLUSDT",
            "marketType": "FUTURES",
            "filters": {"type": "AND", "children": []},
            "entryTrigger": {
                "type": "on_candle_close",
                "params": {},
                "timeframe": "15m",
            },
            "entryConditions": {
                "type": "AND",
                "children": [
                    {
                        "type": "rsi_condition",
                        "params": {
                            "period": 14,
                            "operator": "cross_below",
                            "value": 30,
                        },
                    }
                ],
            },
            "initialization": {
                "type": "open_position",
                "params": {
                    "direction": "LONG",
                    "sl_type": "atr_multiplier",
                    "sl_value_atr": 2.0,
                    "tp_type": "rr_multiplier",
                    "tp_value_rr": 2.0,
                    "move_sl_to_be_on_first_tp": True,
                },
            },
            "positionManagement": [],
        },
    },
]

DEFAULT_NEWS = [
    {
        "title": "DepthSight Federation Hub Phase 1 Released",
        "date": "2026-06-04",
        "text": "We are excited to launch the first phase of the **DepthSight Federation Hub**! You can now import free strategies directly into your workspace and send feedback or bug reports to the developers.",
    },
    {
        "title": "New Genetic Algorithm Optimizations",
        "date": "2026-05-20",
        "text": "Our Genetic Lab has been upgraded with **faster population breeding** and better fitness scoring functions. Try running search on the new parameters now!",
    },
    {
        "title": "Adaptive Risk Manager Improvements",
        "date": "2026-05-10",
        "text": "Adaptive Risk Management is now active for backtests. Set your drawdown limits and let the bot dynamically adjust trade size based on recent performance.",
    },
]


async def get_hub_strategies(db: AsyncSession) -> List[models.HubTopic]:
    stmt = (
        select(models.HubTopic)
        .filter(
            models.HubTopic.topic_type == "strategy",
            models.HubTopic.is_verified.is_(True),
        )
        .order_by(models.HubTopic.created_at.asc())
    )
    result = await db.execute(stmt)
    strategies = list(result.scalars().all())
    if not strategies:
        for s_data in DEFAULT_STRATEGIES:
            strategy = models.HubTopic(
                topic_type="strategy",
                title=s_data["name"],
                author_name=s_data["author"],
                tags=s_data["tags"],
                description=s_data["description"],
                strategy_json=s_data["strategy_json"],
                is_verified=True,
                delete_token=str(uuid.uuid4()),
            )
            db.add(strategy)
        await db.commit()
        stmt = (
            select(models.HubTopic)
            .filter(
                models.HubTopic.topic_type == "strategy",
                models.HubTopic.is_verified.is_(True),
            )
            .order_by(models.HubTopic.created_at.asc())
        )
        result = await db.execute(stmt)
        strategies = list(result.scalars().all())

    if strategies:
        topic_ids = [t.id for t in strategies]
        count_stmt = (
            select(models.HubComment.topic_id, func.count(models.HubComment.id))
            .filter(models.HubComment.topic_id.in_(topic_ids))
            .group_by(models.HubComment.topic_id)
        )
        count_result = await db.execute(count_stmt)
        counts = {row[0]: row[1] for row in count_result.all()}
        for t in strategies:
            t.comments_count = counts.get(t.id, 0)
    return strategies


async def create_hub_strategy(
    db: AsyncSession, strategy_data: schemas.HubStrategy
) -> models.HubTopic:
    strategy = models.HubTopic(
        topic_type="strategy",
        title=strategy_data.name,
        author_name=strategy_data.author,
        tags=strategy_data.tags,
        description=strategy_data.description,
        strategy_json=strategy_data.strategy_json,
        is_verified=True,
        delete_token=str(uuid.uuid4()),
    )
    db.add(strategy)
    await db.flush()
    strategy.comments_count = 0
    return strategy


async def delete_hub_strategy(db: AsyncSession, strategy_id: str):
    stmt = select(models.HubTopic).filter(models.HubTopic.id == strategy_id)
    result = await db.execute(stmt)
    topic = result.scalars().first()
    if topic:
        topic.is_verified = False


async def verify_hub_topic(
    db: AsyncSession, topic_id: str
) -> Optional[models.HubTopic]:
    stmt = select(models.HubTopic).filter(models.HubTopic.id == topic_id)
    result = await db.execute(stmt)
    topic = result.scalars().first()
    if topic:
        topic.is_verified = True
        await db.flush()
        count_stmt = select(func.count(models.HubComment.id)).filter(
            models.HubComment.topic_id == topic_id
        )
        count_result = await db.execute(count_stmt)
        topic.comments_count = count_result.scalar() or 0
    return topic


async def unverify_hub_topic(
    db: AsyncSession, topic_id: str
) -> Optional[models.HubTopic]:
    stmt = select(models.HubTopic).filter(models.HubTopic.id == topic_id)
    result = await db.execute(stmt)
    topic = result.scalars().first()
    if topic:
        topic.is_verified = False
        await db.flush()
        count_stmt = select(func.count(models.HubComment.id)).filter(
            models.HubComment.topic_id == topic_id
        )
        count_result = await db.execute(count_stmt)
        topic.comments_count = count_result.scalar() or 0
    return topic


async def get_hub_news(db: AsyncSession) -> List[models.HubNewsItem]:
    stmt = select(models.HubNewsItem).order_by(
        desc(models.HubNewsItem.is_pinned), desc(models.HubNewsItem.id)
    )
    result = await db.execute(stmt)
    news = list(result.scalars().all())
    if not news:
        for n_data in DEFAULT_NEWS:
            news_item = models.HubNewsItem(
                title=n_data["title"],
                date=n_data["date"],
                text=n_data["text"],
                is_pinned=False,
            )
            db.add(news_item)
        await db.commit()
        stmt = select(models.HubNewsItem).order_by(
            desc(models.HubNewsItem.is_pinned), desc(models.HubNewsItem.id)
        )
        result = await db.execute(stmt)
        news = list(result.scalars().all())

    if news:
        news_ids = [n.id for n in news]
        count_stmt = (
            select(models.HubNewsComment.news_id, func.count(models.HubNewsComment.id))
            .filter(models.HubNewsComment.news_id.in_(news_ids))
            .group_by(models.HubNewsComment.news_id)
        )
        count_result = await db.execute(count_stmt)
        counts = {row[0]: row[1] for row in count_result.all()}
        for n in news:
            n.comments_count = counts.get(n.id, 0)
    return news


async def create_hub_news(
    db: AsyncSession, news_data: schemas.HubNews
) -> models.HubNewsItem:
    news_item = models.HubNewsItem(
        title=news_data.title,
        date=news_data.date,
        text=news_data.text,
        is_pinned=news_data.is_pinned or False,
    )
    db.add(news_item)
    await db.flush()
    return news_item


async def pin_hub_news(
    db: AsyncSession, news_id: int, pin: bool
) -> Optional[models.HubNewsItem]:
    stmt = select(models.HubNewsItem).filter(models.HubNewsItem.id == news_id)
    result = await db.execute(stmt)
    db_news = result.scalars().first()
    if db_news:
        db_news.is_pinned = pin
        await db.flush()
    return db_news


async def delete_hub_news(db: AsyncSession, news_id: int):
    stmt = delete(models.HubNewsItem).filter(models.HubNewsItem.id == news_id)
    await db.execute(stmt)


async def like_hub_news(db: AsyncSession, news_id: int) -> Optional[models.HubNewsItem]:
    stmt = select(models.HubNewsItem).filter(models.HubNewsItem.id == news_id)
    result = await db.execute(stmt)
    db_news = result.scalars().first()
    if db_news:
        db_news.likes_count = (db_news.likes_count or 0) + 1
        await db.flush()
        count_stmt = select(func.count(models.HubNewsComment.id)).filter(
            models.HubNewsComment.news_id == news_id
        )
        count_result = await db.execute(count_stmt)
        db_news.comments_count = count_result.scalar() or 0
    return db_news


async def create_hub_news_comment(
    db: AsyncSession, news_id: int, comment_data: schemas.HubNewsCommentCreate
) -> models.HubNewsComment:
    db_comment = models.HubNewsComment(
        news_id=news_id,
        author_name=comment_data.author_name,
        text=comment_data.text,
    )
    db.add(db_comment)
    await db.flush()
    return db_comment


async def get_hub_news_comments(
    db: AsyncSession, news_id: int
) -> List[models.HubNewsComment]:
    stmt = (
        select(models.HubNewsComment)
        .filter(models.HubNewsComment.news_id == news_id)
        .order_by(models.HubNewsComment.created_at.asc())
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())
