# syntax=docker/dockerfile:1
FROM python:3.10-slim

WORKDIR /app

COPY apps/api/requirements.txt requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY apps/api ./apps/api
COPY apps/gate_service ./apps/gate_service
COPY config ./config

# Deliberately NOT `COPY .env .env` -- see apps/eval_service/Dockerfile for the
# full reasoning (§10.10, redundant with docker-compose's env_file directive
# and Helm's Secret/ConfigMap injection).

RUN touch apps/__init__.py

EXPOSE 8003
CMD ["uvicorn", "apps.gate_service.main:app", "--host", "0.0.0.0", "--port", "8003"]