#!/bin/bash
set -x
if touch /app/data/startup.log 2>/dev/null; then
    exec > >(tee -a /app/data/startup.log) 2>&1
fi

# /tmp is per-container, so a lock there cannot serialize migrations across
# api/bot/market-data containers (they all run `alembic upgrade head` at boot
# and race on the alembic_version insert -> UniqueViolation). /app/data is a
# shared bind mount in every compose file, so the lock actually works there.
# Fall back to /tmp only if /app/data is not writable (lock then degrades to
# the old per-container behavior instead of breaking startup).
if touch /app/data/migrations.lock 2>/dev/null; then
    LOCK_FILE="/app/data/migrations.lock"
else
    LOCK_FILE="/tmp/migrations.lock"
fi

echo "Waiting for migration lock..."

# Running alembic upgrade head.
echo "Running migrations..."
if flock -x "$LOCK_FILE" -c "alembic upgrade head"; then
    echo "Migrations check completed successfully."
else
    echo "WARNING: Migrations failed. Check the logs above. Application might fail if tables are missing."
fi


echo "Starting application..."
exec "$@"
