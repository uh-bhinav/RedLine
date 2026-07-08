# syntax=docker/dockerfile:1
FROM python:3.10-slim

WORKDIR /app

COPY apps/api/requirements.txt requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY apps/api ./apps/api
COPY apps/agent_service ./apps/agent_service
COPY .env .env

RUN touch apps/__init__.py

EXPOSE 8002
CMD ["uvicorn", "apps.agent_service.main:app", "--host", "0.0.0.0", "--port", "8002"]