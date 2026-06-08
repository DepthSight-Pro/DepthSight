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
        self._load_config(force=True)

    def _get_config_mtime_ns(self) -> int:
        return self._config_path.stat().st_mtime_ns

    def _load_config(self, force: bool = False) -> None:
        try:
            current_mtime_ns = self._get_config_mtime_ns()
            if not force and current_mtime_ns == self._last_mtime_ns:
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
        return plan.get("billing", {}).get(selected_mode, {})

    def get_effective_plan_price(self, plan_name: str) -> float:
        self._reload_if_changed()
        mode_billing = self.get_plan_billing(plan_name)
        plan = self._plans.get(plan_name, {})
        return float(mode_billing.get("price_usd", plan.get("price_usd", 0)))

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


CONFIG_FILE_PATH = Path(__file__).parent / "plans_config.yml"

plans_config = PlansConfig(CONFIG_FILE_PATH)
