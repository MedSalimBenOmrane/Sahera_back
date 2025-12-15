#!/bin/sh
set -e

# Default to main.py if FLASK_APP not provided
export FLASK_APP="${FLASK_APP:-main.py}"

if [ -n "$DATABASE_URL" ]; then
  echo "Running database migrations..."
  attempt=1
  until flask db upgrade; do
    if [ "$attempt" -ge 5 ]; then
      echo "Migrations failed after $attempt attempts; aborting."
      exit 1
    fi
    echo "Migration failed (attempt $attempt), retrying in 5s..."
    attempt=$((attempt + 1))
    sleep 5
  done
fi

# Listen on PORT if provided by the platform; default to 80 for EB/ALB expectations
exec gunicorn -b "0.0.0.0:${PORT:-80}" main:app
