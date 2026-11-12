#!/bin/sh
# Avvio del container: applica le migrazioni del database, poi avvia il webhook o il job.
set -e

alembic upgrade head

case "${1:-web}" in
  web)
    exec uvicorn cardbot.app:app --host 0.0.0.0 --port "${PORT:-8080}" --proxy-headers
    ;;
  job)
    shift
    exec python -m cardbot.jobs.poll "$@"
    ;;
  *)
    exec "$@"
    ;;
esac
