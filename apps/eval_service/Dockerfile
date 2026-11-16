# syntax=docker/dockerfile:1
FROM python:3.10-slim

WORKDIR /app

# Install dependencies first (cached layer unless requirements.txt changes)
COPY apps/api/requirements.txt requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy the shared library and the service itself
COPY apps/api ./apps/api
COPY apps/eval_service ./apps/eval_service
COPY agents ./agents
# model_profiles.py resolves config/model_profiles.yaml relative to the repo root.
# Without this the agents' get_profile() calls raise FileNotFoundError at runtime --
# the image builds and starts fine, then fails on the first eval.
COPY config ./config

# Deliberately NOT `COPY .env .env` -- that would bake the Gemini key and JWT
# secret into every image layer (foundational doc §10.10 explicitly forbids
# this: "never committed to Git, never baked into images"). It was also
# redundant: docker-compose.yml already declares `env_file: .env` for this
# service, which injects the same variables as real environment variables
# before the process starts -- pydantic-settings' Settings() reads env vars in
# preference to any physical .env file regardless (apps/api/core/config.py's
# `env_file=".env"` is only ever a fallback). The k3d/Helm path was never
# affected either; it injects everything via Secrets/ConfigMaps
# (_helpers.tpl's commonEnv), never via a file inside the image.

# Empty init so apps/ is a package
RUN touch apps/__init__.py

EXPOSE 8001
CMD ["uvicorn", "apps.eval_service.main:app", "--host", "0.0.0.0", "--port", "8001"]