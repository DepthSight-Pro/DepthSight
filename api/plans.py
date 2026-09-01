# api/plans.py
import logging
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)


class PlansConfig:
    def __init__(self, config_path: Path):
        self._config_path = Path(config_path)
        self._plans = {}
        self._billing = {}
        self._referral_program = {}
        self._affiliate_program = {}
        self._block_restrictions = {}
        self._registration_trial = {}
        self._last_mtime_ns = -1
        self._last_size = -1
        self._has_db_override = False
        self._load_config(force=True)

    def _get_config_stat(self) -> tuple[int, int]:
        try:
            st = self._config_path.stat()
            return st.st_mtime_ns, st.st_size
        except Exception:
            return -1, -1

    def _load_config(self, force: bool = False) -> None:
        try:
            current_mtime_ns, current_size = self._get_config_stat()
            if (
                not force
                and current_mtime_ns == self._last_mtime_ns
                and current_size == self._last_size
            ):
                return

            with open(self._config_path, "r", encoding="utf-8") as f:
                config = yaml.safe_load(f) or {}

            self._plans = config.get("plans", {})
            self._billing = config.get("billing", {})
            self._referral_program = config.get("referral_program", {})
            self._affiliate_program = config.get("affiliate_program", {})
            self._block_restrictions = config.get("block_restrictions", {})
            self._registration_trial = config.get("registration_trial", {})
            self._last_mtime_ns = current_mtime_ns
            self._last_size = current_size

            if self._plans:
                logger.info(
                    f"Successfully loaded {len(self._plans)} plans from {self._config_path}"
                )
            else:
                logger.warning(
                    f"Plans config file loaded from {self._config_path}, but no plans were found inside."
                )

            if self._referral_program:
                logger.info(
                    f"Successfully loaded referral program config from {self._config_path}"
                )
            else:
                logger.warning(
                    f"Referral program config not found in {self._config_path}."
                )
        except FileNotFoundError:
            logger.error(
                f"FATAL: Plans config file not found at path: {self._config_path}"
            )
        except Exception as e:
            logger.error(
                f"Error loading or parsing plans config file: {e}", exc_info=True
            )

    def _reload_if_changed(self) -> None:
        if not self._has_db_override:
            self._load_config(force=False)

    def get_plan(self, plan_name: str) -> dict:
        self._reload_if_changed()
        return self._plans.get(plan_name, {"permissions": [], "quotas": {}})

    def get_all_plans(self) -> dict:
        self._reload_if_changed()
        return self._plans

    def get_billing_config(self) -> dict:
        self._reload_if_changed()
        return self._billing

    def get_billing_mode(self) -> str:
        self._reload_if_changed()
        mode = str(self._billing.get("mode", "monthly")).lower()
        return mode if mode in {"monthly", "lifetime"} else "monthly"

    def get_plan_billing(self, plan_name: str, mode: str | None = None) -> dict:
        self._reload_if_changed()
        selected_mode = mode or self.get_billing_mode()
        plan = self._plans.get(plan_name, {})
        billing = plan.get("billing", {}).get(selected_mode, {})
        if (
            selected_mode == "monthly"
            and "price_usd" not in billing
            and "price_usd" in plan
        ):
            billing = dict(billing)
            billing["price_usd"] = plan["price_usd"]
        return billing

    def get_effective_plan_price(self, plan_name: str) -> float:
        self._reload_if_changed()
        selected_mode = self.get_billing_mode()
        plan = self._plans.get(plan_name, {})
        if selected_mode == "lifetime":
            lifetime_billing = plan.get("billing", {}).get("lifetime", {})
            if lifetime_billing.get("enabled"):
                return float(
                    lifetime_billing.get("price_usd", plan.get("price_usd", 0))
                )
        return float(plan.get("price_usd", 0))

    def get_lifetime_reservation_ttl_seconds(self) -> int:
        self._reload_if_changed()
        lifetime_config = self._billing.get("lifetime", {})
        return int(lifetime_config.get("reservation_ttl_seconds", 900))

    def get_referral_bonus_config(self) -> dict:
        self._reload_if_changed()
        return self._referral_program

    def get_affiliate_config(self) -> dict:
        self._reload_if_changed()
        return self._affiliate_program

    def get_block_restrictions(self) -> dict:
        self._reload_if_changed()
        return self._block_restrictions

    def get_registration_trial_config(self) -> dict:
        self._reload_if_changed()
        config = self._registration_trial or {}

        try:
            days = int(config.get("days", 7))
        except (TypeError, ValueError):
            logger.warning(
                "Invalid registration_trial.days value in %s. Falling back to 7.",
                self._config_path,
            )
            days = 7

        return {
            "enabled": bool(config.get("enabled", False)),
            "plan": str(config.get("plan", "standard") or "standard"),
            "days": max(days, 0),
        }

    def get_full_config(self) -> dict:
        """Returns the full parsed plans configuration."""
        self._reload_if_changed()
        return {
            "registration_trial": self._registration_trial,
            "block_restrictions": self._block_restrictions,
            "billing": self._billing,
            "plans": self._plans,
            "referral_program": self._referral_program,
            "affiliate_program": self._affiliate_program,
        }

    def update_full_config(self, config: dict, write_to_file: bool = True) -> dict:
        """Updates internal structures and writes back to YAML file."""
        if not isinstance(config, dict):
            raise ValueError("Plans config must be a dictionary.")

        self._plans = config.get("plans", {})
        self._billing = config.get("billing", {})
        self._referral_program = config.get("referral_program", {})
        self._affiliate_program = config.get("affiliate_program", {})
        self._block_restrictions = config.get("block_restrictions", {})
        self._registration_trial = config.get("registration_trial", {})

        # Ensure monthly billing price stays in sync with plan price_usd
        for _, p_data in self._plans.items():
            if isinstance(p_data, dict):
                p_price = p_data.get("price_usd", 0)
                if "billing" in p_data and isinstance(p_data["billing"], dict):
                    if "monthly" in p_data["billing"] and isinstance(
                        p_data["billing"]["monthly"], dict
                    ):
                        p_data["billing"]["monthly"]["price_usd"] = p_price

        if write_to_file and self._config_path:
            try:
                full_dict = {
                    "registration_trial": self._registration_trial,
                    "block_restrictions": self._block_restrictions,
                    "billing": self._billing,
                    "plans": self._plans,
                    "referral_program": self._referral_program,
                    "affiliate_program": self._affiliate_program,
                }
                with open(self._config_path, "w", encoding="utf-8") as f:
                    yaml.safe_dump(
                        full_dict, f, sort_keys=False, allow_unicode=True, indent=2
                    )
                current_mtime_ns, current_size = self._get_config_stat()
                self._last_mtime_ns = current_mtime_ns
                self._last_size = current_size
                logger.info(
                    "Successfully updated plans configuration file %s",
                    self._config_path,
                )
            except Exception as e:
                logger.warning(
                    "Notice: Could not write updated plans config to disk file %s (DB remains primary): %s",
                    self._config_path,
                    e,
                )

        return self.get_full_config()

    async def load_from_db(self, db) -> bool:
        """Loads plans configuration from the system_settings table if present."""
        try:
            from sqlalchemy import select
            from .models import SystemSetting

            stmt = select(SystemSetting).where(SystemSetting.key == "plans_config")
            result = await db.execute(stmt)
            setting = result.scalar_one_or_none()
            if setting and isinstance(setting.value, dict):
                self._has_db_override = True
                self.update_full_config(setting.value, write_to_file=True)
                logger.info("Loaded plans configuration from system_settings DB table.")
                return True
        except Exception as e:
            logger.warning(
                "Could not load plans configuration from DB (using YAML fallback): %s",
                e,
            )
        return False

    async def save_to_db(self, db, config: dict, user_id: int | None = None) -> None:
        """Saves plans configuration to the system_settings table and synchronizes file."""
        from sqlalchemy import select
        from sqlalchemy.orm.attributes import flag_modified
        from .models import SystemSetting

        self._has_db_override = True
        self.update_full_config(config, write_to_file=True)

        stmt = select(SystemSetting).where(SystemSetting.key == "plans_config")
        result = await db.execute(stmt)
        setting = result.scalar_one_or_none()
        if setting:
            setting.value = config
            setting.updated_by_user_id = user_id
            flag_modified(setting, "value")
        else:
            setting = SystemSetting(
                key="plans_config",
                value=config,
                description="Platform subscription plans, billing, and restriction settings",
                updated_by_user_id=user_id,
            )
            db.add(setting)
        await db.commit()


CONFIG_FILE_PATH = Path(__file__).parent / "plans_config.yml"

plans_config = PlansConfig(CONFIG_FILE_PATH)
