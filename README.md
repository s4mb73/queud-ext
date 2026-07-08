# queud-ext

Chrome extension + basket API for short checkout links.

## Railway deploy

- **Repo:** `s4mb73/queud-ext` (branch `main`)
- **Start:** `uvicorn queud_api.server:app --host 0.0.0.0 --port $PORT`
- **Health:** `GET /health` → `{"status":"ok"}`

Do **not** point Railway at `queud-aio/queud` — that repo does not exist.