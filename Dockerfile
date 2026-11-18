# Un'unica immagine per il webhook + app PokeVault (Cloud Run service) e per il job giornaliero (Cloud Run job).

# 1) Interfaccia dell'app (PWA): compilata una volta sola, nell'immagine finale va solo web/dist.
FROM node:22-slim AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY web ./
RUN npm run build

# 2) Server Python.
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
COPY --from=web /web/dist ./web/dist
COPY deploy/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh && useradd --create-home --uid 10001 app
USER app

# "web" (predefinito) avvia il webhook su $PORT; "job" esegue il controllo prezzi giornaliero.
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["web"]
