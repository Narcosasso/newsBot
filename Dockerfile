# Un'unica immagine per il webhook (Cloud Run service) e per il job giornaliero (Cloud Run job).
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY pyproject.toml ./
COPY cardbot ./cardbot
RUN pip install ".[postgres]"

COPY alembic.ini ./
COPY migrations ./migrations
COPY deploy/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh && useradd --create-home --uid 10001 app
USER app

# "web" (predefinito) avvia il webhook su $PORT; "job" esegue il controllo prezzi giornaliero.
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["web"]
