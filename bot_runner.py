# bot_runner.py
# ruff: noqa: E402
import asyncio
import platform

if platform.system() == "Windows":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    print("INFO: Applied WindowsSelectorEventLoopPolicy for aiodns compatibility.")

from dotenv import load_dotenv
from pathlib import Path

env_path = Path(".") / ".env"
load_dotenv(dotenv_path=env_path)
import os
import logging
import signal
import json
import aiohttp
from aiohttp import ThreadedResolver
import multiprocessing
from typing import Dict, Optional

# --- Local Imports ---
from bot_module import config
from bot_module.logger_setup import setup_global_logging
from bot_module.data_consumer import DataConsumer
from bot_module.exchanges import create_exchange_executor
from bot_module.risk_manager import RiskManager
from bot_module.controller import TradingController
from bot_module.telegram_notifier import TelegramNotifier
from bot_module.compass_strategy import CompassStrategy
from bot_module.strategy import STRATEGIES

# Register CompassStrategy manually to avoid circular imports in strategy.py
STRATEGIES["CompassStrategy"] = CompassStrategy

# --- API Imports for Multi-User Setup ---
from api.database import get_db
from bot_module.redis_handler import user_id_context
from api import crud, models, security
from api.plans import plans_config
from api.push_sender import send_push_notification
from api.redis_client import get_redis_client
from bot_module.runtime_dependencies import configure_runtime_dependencies

from bot_module.paper_executor import PaperTradingExecutor

configure_runtime_dependencies(
    crud_module=crud,
    get_db_factory=get_db,
    push_sender=send_push_notification,
)

# --- Logging Setup ---
setup_global_logging("bot_runner.log")
from bot_module.logger_setup import setup_bot_logging

setup_bot_logging()
logger = logging.getLogger("bot_module.runner")

# --- Global Variables for Multi-User Bot ---
# user_controllers[user_id][api_key_id] = TradingController
user_controllers: Dict[int, Dict[int, TradingController]] = {}
shutdown_event = asyncio.Event()
telegram_notifier: Optional[TelegramNotifier] = None


def _count_active_controllers() -> int:
    return sum(len(controllers) for controllers in user_controllers.values())


def _coerce_int(value) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _plan_allows_live_trading(plan_name: Optional[str]) -> bool:
    if not plan_name:
        return False

    plan_config = plans_config.get_plan(plan_name)
    permissions = set(plan_config.get("permissions", []))
    limits = plan_config.get("limits", {})

    has_live_permission = "allow_real_trading" in permissions
    has_live_limit = bool(limits.get("allow_real_trading", has_live_permission))

    if has_live_permission != has_live_limit:
        logger.warning(
            "Plan '%s' has inconsistent live-trading flags (permission=%s, limit=%s). "
            "Live controller startup will remain disabled until the config is aligned.",
            plan_name,
            has_live_permission,
            has_live_limit,
        )

    return has_live_permission and has_live_limit


def _user_is_live_eligible(user: models.User) -> bool:
    plan = getattr(user, "plan", None)
    if plan:
        plan_config = plans_config.get_plan(plan)
        limits = plan_config.get("limits", {})
        if limits.get("allow_free_bybit_trading", False):
            return True
    return _plan_allows_live_trading(plan)


def _api_key_belongs_to_shard(
    api_key_id: Optional[int], shard_id: int, num_workers: int
) -> bool:
    if num_workers <= 1:
        return True

    normalized_api_key_id = _coerce_int(api_key_id)
    if normalized_api_key_id is None:
        return False

    return normalized_api_key_id % num_workers == shard_id


async def _get_sharded_active_api_keys_for_user(
    user, db, shard_id: int, num_workers: int
):
    if not _user_is_live_eligible(user):
        return []

    active_keys = await crud.get_active_api_keys_for_user(db, user.id)

    plan_name = getattr(user, "plan", None)
    if plan_name:
        plan_config = plans_config.get_plan(plan_name)
        limits = plan_config.get("limits", {})
        if limits.get(
            "allow_free_bybit_trading", False
        ) and "allow_real_trading" not in plan_config.get("permissions", []):
            active_keys = [k for k in active_keys if k.exchange.lower() == "bybit"]

    return [
        api_key_obj
        for api_key_obj in active_keys
        if _api_key_belongs_to_shard(api_key_obj.id, shard_id, num_workers)
    ]


async def _clear_strategy_runtime_state(
    redis_client, user_id: int, api_key_id: int
) -> None:
    if redis_client is None:
        return

    strategies_key = f"{config.REDIS_STATE_KEY_STRATEGIES}:{user_id}:{api_key_id}"
    notification_channel = f"depthsight:events:strategies:{user_id}"
    notification_payload = json.dumps({"user_id": user_id})

    try:
        await redis_client.set(strategies_key, "[]")
        await redis_client.publish(notification_channel, notification_payload)
    except Exception as exc:
        logger.error(
            "Failed to clear strategy runtime state for user_id=%s api_key_id=%s: %s",
            user_id,
            api_key_id,
            exc,
            exc_info=True,
        )


# --- Signal Handler ---
def handle_signal(signum, frame):
    logger.warning(f"Received signal {signum}. Initiating shutdown...")
    try:
        loop = asyncio.get_running_loop()
        if loop.is_running():
            loop.call_soon_threadsafe(shutdown_event.set)
        else:
            logger.warning("Event loop not running, cannot set shutdown event.")
    except RuntimeError:
        logger.warning("No running event loop found in signal handler.")


# --- Main Bot Runner Function ---
async def run_bot(shard_id: int = 0, num_workers: int = 1):
    global user_controllers, telegram_notifier
    session = None
    db = None
    redis_client = None

    try:
        logger.info("Starting multi-user bot initialization...")

        # 1. Initialize shared components (Telegram, aiohttp Session)
        # TelegramNotifier is always created if we have a bot token.
        # This allows test messages to be sent even if global notifications are disabled.
        # The queue processor (for automatic notifications) is only started if TELEGRAM_NOTIFICATIONS_ENABLED is True.
        if (
            config.TELEGRAM_BOT_TOKEN
            and "YOUR_TELEGRAM_BOT_TOKEN" not in config.TELEGRAM_BOT_TOKEN
        ):
            try:
                telegram_notifier = TelegramNotifier(
                    bot_token=config.TELEGRAM_BOT_TOKEN,
                    chat_id=config.TELEGRAM_CHAT_ID
                    if config.TELEGRAM_CHAT_ID
                    and "YOUR_TELEGRAM_CHAT_ID" not in config.TELEGRAM_CHAT_ID
                    else "",
                    loop=asyncio.get_running_loop(),
                )
                # Only start the message queue processor if global notifications are enabled
                if config.TELEGRAM_NOTIFICATIONS_ENABLED:
                    await telegram_notifier.start()
                    logger.info(
                        "Shared TelegramNotifier initialized and queue processor started."
                    )
                else:
                    logger.info(
                        "Shared TelegramNotifier initialized (test messages only, queue processor not started because TELEGRAM_NOTIFICATIONS_ENABLED=False)."
                    )
            except Exception as e_tg_init:
                logger.error(
                    f"Failed to initialize TelegramNotifier: {e_tg_init}", exc_info=True
                )
                telegram_notifier = None
        else:
            logger.info(
                "Telegram bot token not configured. TelegramNotifier will not be available."
            )

        logger.info("Creating shared aiohttp session...")
        timeout = aiohttp.ClientTimeout(total=config.API_REQUEST_TIMEOUT_SECONDS * 2)
        resolver = ThreadedResolver()
        connector = aiohttp.TCPConnector(
            resolver=resolver, limit_per_host=20, use_dns_cache=False
        )
        session = aiohttp.ClientSession(timeout=timeout, connector=connector)
        logger.info("Shared aiohttp session created.")

        # 2. Initialize Redis Client
        logger.info("Initializing Redis client...")
        redis_client = await get_redis_client()
        logger.info("Redis client initialized.")

        # 2.5 Initialize Telegram bot handlers and polling if enabled
        # Only start polling on shard 0 to avoid 409 Conflict from multiple workers
        if (
            telegram_notifier
            and config.TELEGRAM_NOTIFICATIONS_ENABLED
            and shard_id == 0
        ):
            telegram_notifier.setup_handlers(get_db, redis_client)
            await telegram_notifier.start_polling()
            logger.info("Telegram Bot handlers registered and polling started.")
        elif telegram_notifier and config.TELEGRAM_NOTIFICATIONS_ENABLED:
            logger.info(
                "Telegram polling skipped on shard %s (only shard 0 polls).",
                shard_id,
            )

        # 3. Connect to DB and initialize controllers for each user
        logger.info("Connecting to the database to set up user controllers...")
        db_gen = get_db()
        db = await anext(db_gen)

        users = await crud.get_users(db)
        controllers_to_initialize = []
        eligible_live_users = 0

        for user in users:
            if not _user_is_live_eligible(user):
                continue

            eligible_live_users += 1
            my_keys = await _get_sharded_active_api_keys_for_user(
                user, db, shard_id, num_workers
            )
            controllers_to_initialize.extend((user, key) for key in my_keys)

        logger.info(
            "[Shard %s/%s] Initializing %s live controllers across %s live-eligible users "
            "(out of %s total users).",
            shard_id,
            num_workers,
            len(controllers_to_initialize),
            eligible_live_users,
            len(users),
        )

        for user, api_key_obj in controllers_to_initialize:
            await _initialize_controller_for_key(
                user, api_key_obj, db, session, redis_client, telegram_notifier
            )

        # 4. Start the command listener and wait for shutdown
        logger.info(
            "Bot runner initialized with %s active controllers across %s users on shard %s.",
            _count_active_controllers(),
            len(user_controllers),
            shard_id,
        )

        # Create the command listener task
        command_listener_task = asyncio.create_task(
            _run_command_listener(
                db, session, redis_client, telegram_notifier, shard_id, num_workers
            ),
            name=f"BotRunnerCommandListener_S{shard_id}",
        )

        logger.info("Command listener started. Waiting for shutdown signal...")
        await shutdown_event.wait()
        logger.info("Shutdown event received.")

        # Clean up the command listener
        command_listener_task.cancel()
        try:
            await command_listener_task
        except asyncio.CancelledError:
            logger.info("Command listener task cancelled.")

    except Exception as e:
        logger.critical(
            f"Critical unhandled exception in bot_runner: {e}", exc_info=True
        )
        if telegram_notifier:
            await telegram_notifier.bot_error(
                error_description=f"CRITICAL ERROR in bot_runner main: {e}",
                module_function="run_bot",
                action_taken="Bot is shutting down.",
            )
    finally:
        if redis_client:
            await redis_client.close()
            logger.info("Redis client closed.")


async def _initialize_user_controllers(
    user,
    db,
    session,
    redis_client,
    telegram_notifier_instance,
    shard_id: int = 0,
    num_workers: int = 1,
):
    """
    Initializes TradingControllers for all active API keys of a single user
    that belong to the current shard.
    """
    if not _user_is_live_eligible(user):
        logger.info(
            "Skipping live controller initialization for user %s (ID: %s) because plan '%s' does not allow live trading.",
            user.username,
            user.id,
            user.plan,
        )
        return

    active_keys = await _get_sharded_active_api_keys_for_user(
        user, db, shard_id, num_workers
    )

    if not active_keys:
        logger.debug(
            "User %s (ID: %s) has no active API keys assigned to shard %s/%s.",
            user.username,
            user.id,
            shard_id,
            num_workers,
        )
        return

    for api_key_obj in active_keys:
        await _initialize_controller_for_key(
            user, api_key_obj, db, session, redis_client, telegram_notifier_instance
        )


async def _initialize_controller_for_key(
    user, api_key_obj, db, session, redis_client, telegram_notifier_instance
):
    """
    Initializes a single TradingController for a specific API key of a user.
    """
    global user_controllers

    # Check if controller for this key already exists
    if user.id in user_controllers and api_key_obj.id in user_controllers[user.id]:
        logger.warning(
            f"Controller for user {user.username}, key {api_key_obj.name} (ID: {api_key_obj.id}) already exists. Skipping."
        )
        return False

    token = None
    try:
        # Set user context for logging (user_id is shared across all keys of this user)
        token = user_id_context.set(user.id)

        logger.info(
            f"--- Initializing controller for user: {user.username}, key: {api_key_obj.name} (ID: {api_key_obj.id}) ---"
        )

        decrypted_key = security.decrypt_data(api_key_obj.encrypted_api_key)
        decrypted_secret = security.decrypt_data(api_key_obj.encrypted_api_secret)

        if not decrypted_key or not decrypted_secret:
            logger.error(
                f"Failed to decrypt API keys for user {user.username}, key {api_key_obj.name}. Skipping."
            )
            return False

        live_executor = create_exchange_executor(
            exchange=api_key_obj.exchange,
            api_key=decrypted_key,
            api_secret=decrypted_secret,
            session=session,
            market_type="futures_usdtm",
        )
        market_executors = {
            "futures_usdtm": live_executor,
            "spot": create_exchange_executor(
                exchange=api_key_obj.exchange,
                api_key=decrypted_key,
                api_secret=decrypted_secret,
                session=session,
                market_type="spot",
            ),
        }

        # Create DataConsumer, which will be shared within THIS controller (one per account)
        data_consumer = DataConsumer(
            loop=asyncio.get_running_loop(), executor=live_executor, event_queue=None
        )

        # Create PaperTradingExecutor
        paper_executor = PaperTradingExecutor(
            user_id=user.id,
            db_session=db,
            data_consumer=data_consumer,
            redis_client=redis_client,
        )

        # Initialize equity tracking
        await paper_executor.initialize_equity_tracking()

        user_app_config = await crud.get_config(db, user_id=user.id)
        user_settings = user_app_config.model_dump() if user_app_config else {}
        if not user_settings:
            logger.warning(
                f"Could not load AppConfig for user {user.username}, using empty settings for RiskManager."
            )

        # RiskManager should be initialized with the live executor
        user_risk_manager = RiskManager(
            executor=live_executor,
            paper_executor=paper_executor,
            user_id=user.id,
            db_session=db,
            user_settings=user_settings,
            api_key_name=api_key_obj.name,
        )
        await user_risk_manager.initialize()

        if telegram_notifier_instance:
            user_risk_manager.telegram_notifier = telegram_notifier_instance
            user_risk_manager.loop_from_controller = asyncio.get_running_loop()

        user_controller = TradingController(
            loop=asyncio.get_running_loop(),
            data_consumer=data_consumer,
            live_executor=live_executor,
            paper_executor=paper_executor,
            risk_manager=user_risk_manager,
            user_id=user.id,
            api_key_id=api_key_obj.id,
            telegram_notifier=telegram_notifier_instance,
            market_executors=market_executors,
            api_key_name=api_key_obj.name,
        )

        await user_controller.start()

        if user.id not in user_controllers:
            user_controllers[user.id] = {}

        user_controllers[user.id][api_key_obj.id] = user_controller
        logger.info(
            f"Controller for user '{user.username}', key '{api_key_obj.name}' started successfully."
        )
        return True

    except Exception as e_user_init:
        logger.error(
            f"Failed to initialize controller for user {user.username}, key {api_key_obj.name}: {api_key_obj.id}): {e_user_init}",
            exc_info=True,
        )
        return False
    finally:
        if token:
            user_id_context.reset(token)


async def _run_command_listener(
    db, session, redis_client, telegram_notifier_instance, shard_id, num_workers
):
    """
    Listens for Redis commands to dynamically manage user controllers.
    Only acts on controllers assigned to this shard.
    """
    import json

    logger.info(
        f"Starting bot runner command listener on channel: '{config.REDIS_COMMAND_CHANNEL}'"
    )
    pubsub = redis_client.pubsub()
    await pubsub.subscribe(config.REDIS_COMMAND_CHANNEL)

    while True:
        try:
            message = await pubsub.get_message(
                ignore_subscribe_messages=True, timeout=1.0
            )
            if message and message["type"] == "message":
                try:
                    command_data = json.loads(message["data"])
                    command_type = command_data.get("command")
                    payload = command_data.get("payload", {})

                    if command_type == "ACTIVATE_API_KEY":
                        user_id = _coerce_int(payload.get("user_id"))
                        api_key_id = _coerce_int(payload.get("api_key_id"))
                        if user_id and api_key_id:
                            if not _api_key_belongs_to_shard(
                                api_key_id, shard_id, num_workers
                            ):
                                continue

                            logger.info(
                                "[Shard %s] Received ACTIVATE_API_KEY for user_id=%s, api_key_id=%s",
                                shard_id,
                                user_id,
                                api_key_id,
                            )

                            if (
                                user_id in user_controllers
                                and api_key_id in user_controllers[user_id]
                            ):
                                logger.info(
                                    f"Controller for user_id {user_id}, key_id {api_key_id} already exists. Ignoring."
                                )
                                continue

                            user = await crud.get_user_by_id(db, user_id=user_id)
                            api_key_obj = await crud.get_api_key_by_id(
                                db, user_id=user_id, key_id=api_key_id
                            )

                            if user and api_key_obj:
                                plan_config = plans_config.get_plan(user.plan)
                                limits = plan_config.get("limits", {})
                                if limits.get(
                                    "allow_free_bybit_trading", False
                                ) and "allow_real_trading" not in plan_config.get(
                                    "permissions", []
                                ):
                                    if api_key_obj.exchange.lower() != "bybit":
                                        logger.warning(
                                            "[Shard %s] Ignoring ACTIVATE_API_KEY for user_id=%s, api_key_id=%s because plan '%s' only allows Bybit key live trading.",
                                            shard_id,
                                            user_id,
                                            api_key_id,
                                            user.plan,
                                        )
                                        continue

                                if not _user_is_live_eligible(user):
                                    logger.warning(
                                        "[Shard %s] Ignoring ACTIVATE_API_KEY for user_id=%s, api_key_id=%s because plan '%s' does not allow live trading.",
                                        shard_id,
                                        user_id,
                                        api_key_id,
                                        user.plan,
                                    )
                                    continue

                                success = await _initialize_controller_for_key(
                                    user,
                                    api_key_obj,
                                    db,
                                    session,
                                    redis_client,
                                    telegram_notifier_instance,
                                )
                                if success:
                                    logger.info(
                                        f"Successfully activated controller for key {api_key_id}"
                                    )
                                else:
                                    logger.error(
                                        f"Failed to activate controller for key {api_key_id}"
                                    )
                            else:
                                logger.error(
                                    f"User {user_id} or Key {api_key_id} not found."
                                )
                        else:
                            logger.error(f"Invalid ACTIVATE_API_KEY payload: {payload}")

                    elif command_type == "DEACTIVATE_API_KEY":
                        user_id = _coerce_int(payload.get("user_id"))
                        api_key_id = _coerce_int(payload.get("api_key_id"))
                        if user_id and api_key_id:
                            if not _api_key_belongs_to_shard(
                                api_key_id, shard_id, num_workers
                            ):
                                continue

                            logger.info(
                                "[Shard %s] Received DEACTIVATE_API_KEY for user_id=%s, api_key_id=%s",
                                shard_id,
                                user_id,
                                api_key_id,
                            )

                            if (
                                user_id in user_controllers
                                and api_key_id in user_controllers[user_id]
                            ):
                                controller = user_controllers[user_id].pop(api_key_id)
                                try:
                                    await controller.stop()
                                    logger.info(
                                        f"Successfully deactivated and removed controller for key {api_key_id}"
                                    )
                                except Exception as exc:
                                    logger.error(
                                        "Failed to stop controller for user_id=%s api_key_id=%s: %s",
                                        user_id,
                                        api_key_id,
                                        exc,
                                        exc_info=True,
                                    )
                                finally:
                                    if (
                                        user_id in user_controllers
                                        and not user_controllers[user_id]
                                    ):
                                        user_controllers.pop(user_id, None)
                            else:
                                logger.warning(
                                    f"Controller for key {api_key_id} not found. Nothing to deactivate."
                                )

                            await _clear_strategy_runtime_state(
                                redis_client, user_id, api_key_id
                            )
                        else:
                            logger.error(
                                f"Invalid DEACTIVATE_API_KEY payload: {payload}"
                            )

                    elif command_type == "INITIALIZE_USER_CONTROLLER":
                        # This command is broadcast to every shard. Each shard initializes only
                        # the API keys assigned to it for the specified user.
                        user_id = _coerce_int(payload.get("user_id"))
                        if user_id:
                            logger.info(
                                f"[Shard {shard_id}] Received INITIALIZE_USER_CONTROLLER for user_id: {user_id}"
                            )
                            user = await crud.get_user_by_id(db, user_id=user_id)
                            if user:
                                await _initialize_user_controllers(
                                    user,
                                    db,
                                    session,
                                    redis_client,
                                    telegram_notifier_instance,
                                    shard_id=shard_id,
                                    num_workers=num_workers,
                                )
                            else:
                                logger.error(
                                    f"User with ID {user_id} not found in database."
                                )
                        else:
                            logger.error(
                                f"Invalid INITIALIZE_USER_CONTROLLER payload: missing user_id. Payload: {payload}"
                            )

                    # Other commands are handled by individual controllers

                except json.JSONDecodeError as e:
                    logger.error(f"Failed to parse command message: {e}")
                except Exception as e:
                    logger.error(f"Error processing command: {e}", exc_info=True)

        except asyncio.CancelledError:
            logger.info("Bot runner command listener task cancelled.")
            break
        except Exception as e:
            logger.error(f"Error in bot runner command listener: {e}", exc_info=True)
            await asyncio.sleep(5)

    await pubsub.unsubscribe(config.REDIS_COMMAND_CHANNEL)
    logger.info("Bot runner command listener stopped.")


# --- Entry Point ---
# --- Worker Entry Point for Multiprocessing ---
def worker_main(shard_id, num_workers):
    """
    Entry point for a child process. Sets up its own event loop and runs the bot.
    """
    import platform as worker_platform

    if worker_platform.system() == "Windows":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    # We re-register signals in the child process
    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    logger.info(f"Worker shard {shard_id}/{num_workers} started (PID: {os.getpid()})")
    try:
        asyncio.run(run_bot(shard_id, num_workers))
    except KeyboardInterrupt:
        pass
    except Exception as e:
        logger.critical(f"Worker {shard_id} died with error: {e}", exc_info=True)


# --- Entry Point ---
if __name__ == "__main__":
    num_workers = getattr(config, "BOT_RUNNER_PROCESSES", 1)
    import time

    if num_workers <= 1:
        # Standard single-process mode
        try:
            signal.signal(signal.SIGINT, handle_signal)
            signal.signal(signal.SIGTERM, handle_signal)
            logger.info("Starting bot runner in SINGLE-PROCESS mode...")
            asyncio.run(run_bot(shard_id=0, num_workers=1))
        except KeyboardInterrupt:
            logger.info("Runner execution interrupted.")
        except Exception as e_main_run:
            logger.critical(
                f"Critical error in single-process run: {e_main_run}", exc_info=True
            )
    else:
        # Multi-process mode (Sharding)
        logger.info(
            f"Starting bot runner in MULTI-PROCESS mode with {num_workers} workers..."
        )
        processes = []

        # Set start method for cleaner multiprocessing behavior (especially on Windows)
        if platform.system() != "Windows":
            try:
                multiprocessing.set_start_method("spawn", force=True)
            except RuntimeError:
                pass

        for i in range(num_workers):
            p = multiprocessing.Process(
                target=worker_main, args=(i, num_workers), name=f"BotShard_{i}"
            )
            p.start()
            processes.append(p)
            logger.info(f"Spawned worker shard {i} (PID: {p.pid})")

        # Main process waits for signals or child process completion
        try:
            # Use a simple loop to check on children and wait for signal
            while not shutdown_event.is_set():
                # Check if all processes are still alive
                alive_count = sum(1 for p in processes if p.is_alive())
                if alive_count < num_workers:
                    logger.warning(
                        f"Some workers died! (Alive: {alive_count}/{num_workers})."
                    )

                # Sleep a bit to not burn CPU in the master process
                time.sleep(2)

        except (KeyboardInterrupt, SystemExit):
            logger.info("Master process received shutdown. Terminating workers...")
        finally:
            for p in processes:
                if p.is_alive():
                    # Send SIGTERM to children
                    try:
                        os.kill(p.pid, signal.SIGTERM)
                    except Exception:
                        p.terminate()

            # Wait for them to finish
            for p in processes:
                p.join(timeout=5)
                if p.is_alive():
                    p.terminate()

            logger.info("All worker shards stopped. Master process exiting.")
