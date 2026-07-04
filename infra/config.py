import os

try:
    from dotenv import load_dotenv

    load_dotenv()
except ModuleNotFoundError:
    pass


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


REDIS_HOST = os.environ.get("REDIS_HOST", "localhost")
REDIS_PORT = _env_int("REDIS_PORT", 6379)
REDIS_USERNAME = os.environ.get("REDIS_USERNAME") or None
REDIS_PASSWORD = os.environ.get("REDIS_PASSWORD") or None

CELERY_WORKER_CONCURRENCY = _env_int("CELERY_WORKER_CONCURRENCY", 4)
CELERY_WORKER_PREFETCH_MULTIPLIER = _env_int("CELERY_WORKER_PREFETCH_MULTIPLIER", 1)


def redis_auth_fragment() -> str:
    if not REDIS_PASSWORD:
        return ""
    if REDIS_USERNAME:
        return f"{REDIS_USERNAME}:{REDIS_PASSWORD}@"
    return f":{REDIS_PASSWORD}@"


REDIS_URL_BASE = f"redis://{redis_auth_fragment()}{REDIS_HOST}:{REDIS_PORT}"
