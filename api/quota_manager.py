# api/quota_manager.py
import redis.asyncio as redis
from datetime import datetime, timedelta, timezone
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession

from . import models, crud
from .plans import plans_config


class QuotaManager:
    """
    Manages usage quotas for a user using Redis.
    """

    def __init__(self, user: models.User, redis_client: redis.Redis, db: AsyncSession):
        self.user = user
        self.redis = redis_client
        self.db = db
        self.plan = plans_config.get_plan(user.plan)

    async def check_and_consume(self, feature: str) -> bool:
        """
        Checks if a feature is available under the quota, and if so, "consumes" one unit.
        First, standard quotas are checked. Bonuses are used only if no standard quota
        is defined for the feature (or if it is unlimited).
        Returns True if usage is allowed, otherwise False.
        """
        quota_was_checked = await self._check_standard_quotas(feature)

        if quota_was_checked is True:
            # Standard quota found and not exceeded, usage is allowed
            return True
        elif quota_was_checked is False:
            # Standard quota found but exceeded. Do NOT use bonuses.
            return False
        elif quota_was_checked is None:
            # Standard quota not found. Now we can check bonuses.
            bonus_quota_ok = await crud.get_and_consume_bonus(
                self.db, self.user.id, feature
            )
            if bonus_quota_ok:
                await self.db.commit()  # Save the changes to the bonus count
                return True

            # If there is no standard quota and no bonus either, then the feature is unlimited
            return True

        # This return will trigger only if _check_standard_quotas returned False (limit exceeded)
        return False

    async def _check_standard_quotas(self, feature: str) -> Optional[bool]:
        """
        Checks and consumes standard quotas in Redis.
        Returns:
        - True: if the quota is not exceeded and has been consumed.
        - False: if the quota is exceeded.
        - None: if there are no standard periodic quotas defined for this feature.
        """
        standard_quota_defined = False

        for period in ["day", "week", "month"]:
            quota_key = f"{feature}_per_{period}"
            limit = self.plan["quotas"].get(quota_key)

            if limit is None:
                continue  # No such quota defined, keep searching

            standard_quota_defined = True

            if limit == 0:
                return False  # Feature is forbidden

            if limit == -1:
                continue  # Unlimited in this period, but there might be a limit in another

            redis_key, expire_seconds = self._get_redis_key_and_ttl(quota_key, period)
            if not redis_key:
                continue

            current_usage_raw = await self.redis.get(redis_key)
            current_usage = int(current_usage_raw) if current_usage_raw else 0

            if current_usage >= limit:
                return False  # Limit is exhausted

        # If we reached here, it means no limits were exceeded
        # Check if any limit was defined at all
        if not standard_quota_defined:
            # If no standard quota was found, return None so QuotaManager can check bonuses
            return None

        # If at least one quota was present, but none were exceeded,
        # then we need to increment the counter for the shortest period
        for period in ["day", "week", "month"]:
            quota_key = f"{feature}_per_{period}"
            limit = self.plan["quotas"].get(quota_key)
            if limit is not None and limit != -1:  # Find the very first relevant quota
                redis_key, expire_seconds = self._get_redis_key_and_ttl(
                    quota_key, period
                )
                new_usage = await self.redis.incr(redis_key)
                if new_usage == 1 and expire_seconds > 0:
                    await self.redis.expire(redis_key, expire_seconds)
                return True  # Report that usage is allowed and successfully counted

        # If all quotas are unlimited (-1)
        return True

    def _get_redis_key_and_ttl(
        self, quota_key: str, period: str
    ) -> tuple[Optional[str], int]:
        """
        Generates a key for Redis and a TTL depending on the period.
        """
        now = datetime.now(timezone.utc)
        if period == "day":
            date_str = now.strftime("%Y-%m-%d")
            end_of_day = datetime(
                now.year, now.month, now.day, 23, 59, 59, tzinfo=timezone.utc
            )
            ttl = int((end_of_day - now).total_seconds())
        elif period == "week":
            start_of_week = now - timedelta(days=now.weekday())
            date_str = start_of_week.strftime("%Y-%m-%d")
            end_of_week = start_of_week.replace(
                hour=23, minute=59, second=59
            ) + timedelta(days=6)
            ttl = int((end_of_week - now).total_seconds())
        elif period == "month":
            date_str = now.strftime("%Y-%m")
            # Approximate TTL, can be improved for accuracy
            next_month = now.replace(day=28) + timedelta(days=4)
            end_of_month = next_month - timedelta(days=next_month.day)
            end_of_month = end_of_month.replace(hour=23, minute=59, second=59)
            ttl = int((end_of_month - now).total_seconds())
        else:
            return None, 0

        return f"usage:{self.user.id}:{quota_key}:{date_str}", ttl
