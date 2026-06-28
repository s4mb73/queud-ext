FROM python:3.12-slim

WORKDIR /app

RUN mkdir -p /app/data

COPY requirements-api.txt .
RUN python -m pip install --no-cache-dir -r requirements-api.txt

COPY queud_api ./queud_api

ENV QUEUD_API_DB=/app/data/queud_baskets.db

CMD ["sh", "-c", "uvicorn queud_api.server:app --host 0.0.0.0 --port ${PORT:-8080}"]