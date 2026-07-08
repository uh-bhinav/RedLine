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
COPY .env .env

# Empty init so apps/ is a package
RUN touch apps/__init__.py

EXPOSE 8001
CMD ["uvicorn", "apps.eval_service.main:app", "--host", "0.0.0.0", "--port", "8001"]