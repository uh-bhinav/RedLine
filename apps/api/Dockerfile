# syntax=docker/dockerfile:1
# Build context: repo root (see docker-compose.yml).
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

# Optional corporate/proxy CA certificates: drop *.pem files into ./certs/.
# A bind mount of the build context (BuildKit) lets the build succeed whether or
# not ./certs exists (a plain COPY of a missing path would fail).
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/*
RUN --mount=type=bind,source=.,target=/ctx,readonly \
    set -eu; \
    found=0; \
    for f in /ctx/certs/*.pem; do \
        [ -f "$f" ] || continue; \
        cp "$f" "/usr/local/share/ca-certificates/$(basename "$f" .pem).crt"; \
        found=1; \
    done; \
    if [ "$found" = 1 ]; then update-ca-certificates; fi
ENV PIP_CERT=/etc/ssl/certs/ca-certificates.crt \
    REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt \
    SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt

WORKDIR /app

COPY apps/api/requirements.txt /tmp/requirements.txt
RUN pip install -r /tmp/requirements.txt

COPY apps/ ./apps/
COPY agents/ ./agents/
COPY eval-suites/ ./eval-suites/
COPY alembic.ini pyproject.toml ./

RUN useradd --create-home --uid 10001 redline \
    && chown -R redline:redline /app
USER redline

EXPOSE 8000
CMD ["uvicorn", "apps.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
