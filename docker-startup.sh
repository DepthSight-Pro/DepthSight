#!/bin/bash
set -x
if touch /app/data/startup.log 2>/dev/null; then
    exec > >(tee -a /app/data/startup.log) 2>&1
fi

LOCK_FILE="/tmp/migrations.lock"

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
