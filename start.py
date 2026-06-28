"""Railway entrypoint — reads PORT from env (avoids literal $PORT in start command)."""

import os

import uvicorn

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8080"))
    uvicorn.run("queud_api.server:app", host="0.0.0.0", port=port)