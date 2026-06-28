FROM python:3.12-slim

WORKDIR /app

RUN mkdir -p /app/data

COPY requirements-api.txt .
RUN python -m pip install --no-cache-dir -r requirements-api.txt

COPY queud_api ./queud_api
COPY start.py .

ENV QUEUD_API_DB=/app/data/queud_baskets.db

CMD ["python", "start.py"]