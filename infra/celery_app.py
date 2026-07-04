import logging

import redis
from celery import Celery

from . import config

logger = logging.getLogger(__name__)

celery_app = Celery(
    "tasks",
    broker=f"{config.REDIS_URL_BASE}/1",
    backend=f"{config.REDIS_URL_BASE}/2",
    include=["tasks"],
)

celery_app.conf.update(
    task_track_started=True,
    result_expires=3600 * 24,
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    worker_concurrency=config.CELERY_WORKER_CONCURRENCY,
    worker_prefetch_multiplier=config.CELERY_WORKER_PREFETCH_MULTIPLIER,
    task_acks_late=True,
    worker_max_tasks_per_child=5,
)

try:
    redis_client_for_tasks = redis.Redis(
        host=config.REDIS_HOST,
        port=config.REDIS_PORT,
        db=0,
        username=config.REDIS_USERNAME,
        password=config.REDIS_PASSWORD,
        decode_responses=True,
    )
    redis_client_for_tasks.ping()
    logger.info("Successfully connected to Redis for Celery task counters.")
except redis.exceptions.ConnectionError as e:
    logger.error(f"FATAL: Could not connect to Redis for Celery task counters: {e}")
    redis_client_for_tasks = None

SIMULATION_INSPECTOR_STATE_TTL_SECONDS = 3600 * 6


def _simulation_inspector_state_key(task_id: str) -> str:
    return f"simulation-inspector:{task_id}"


def _simulation_inspector_events_key(task_id: str) -> str:
    return f"simulation-inspector-events:{task_id}"


_orig_send_task = celery_app.send_task


def eager_send_task(name, args=None, kwargs=None, **options):
    if celery_app.conf.task_always_eager:
        task = celery_app.tasks.get(name)
        if task:
            return task.apply(
                args=args,
                kwargs=kwargs,
                task_id=options.get("task_id"),
                priority=options.get("priority"),
            )
    return _orig_send_task(name, args=args, kwargs=kwargs, **options)


celery_app.send_task = eager_send_task
