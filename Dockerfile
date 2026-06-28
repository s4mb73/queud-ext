FROM python:3.12-slim

WORKDIR /app

COPY requirements-api.txt .
RUN pip install --no-cache-dir -r requirements-api.txt

COPY queud_api ./queud_api

ENV QUEUD_API_DB=data/queud_baskets.db

CMD uvicorn queud_api.server:app --host 0.0.0.0 --port ${PORT:-8080}