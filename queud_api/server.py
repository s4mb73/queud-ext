"""
queud basket API — short checkout links like Carbon/Adonis.

Deploy on your domain, then set in .env:
  QUEUD_API_BASE=https://api.yourdomain.com

Discord links become:
  https://api.yourdomain.com/basket/2b573cc4-e27d-4358-b3a1-73eb6f50d6d6
"""

from __future__ import annotations

import json
import os
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field

DB_PATH = Path(os.environ.get("QUEUD_API_DB", "data/queud_baskets.db"))
API_KEY = os.environ.get("QUEUD_API_KEY", "").strip()
TTL_MINUTES = int(os.environ.get("QUEUD_BASKET_TTL_MIN", "30"))

app = FastAPI(title="queud basket API", version="1.0.0")


class BasketCreate(BaseModel):
    session: str = Field(..., description="Base64 checkout session payload")
    endUrl: str
    proxy: str = ""


@contextmanager
def _db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS baskets (
                id TEXT PRIMARY KEY,
                session TEXT NOT NULL,
                end_url TEXT NOT NULL,
                proxy TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                consumed INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        conn.commit()
        yield conn
        conn.commit()
    finally:
        conn.close()


def _auth(authorization: str | None, x_api_key: str | None) -> None:
    if not API_KEY:
        return
    token = ""
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
    elif x_api_key:
        token = x_api_key.strip()
    if token != API_KEY:
        raise HTTPException(status_code=401, detail="unauthorized")


def _purge_expired(conn: sqlite3.Connection) -> None:
    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=TTL_MINUTES)).isoformat()
    conn.execute("DELETE FROM baskets WHERE created_at < ?", (cutoff,))


QUEUD_API_VERSION = "1.3.5"


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "version": QUEUD_API_VERSION}


@app.get("/version")
def version() -> dict[str, str]:
    return {"version": QUEUD_API_VERSION}


@app.post("/basket")
def create_basket(
    body: BasketCreate,
    authorization: str | None = Header(default=None),
    x_api_key: str | None = Header(default=None),
) -> dict[str, str]:
    _auth(authorization, x_api_key)
    basket_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    with _db() as conn:
        _purge_expired(conn)
        conn.execute(
            "INSERT INTO baskets (id, session, end_url, proxy, created_at) VALUES (?, ?, ?, ?, ?)",
            (basket_id, body.session, body.endUrl, body.proxy or "", now),
        )
    return {"id": basket_id, "path": f"/basket/{basket_id}"}


@app.get("/basket/{basket_id}/session")
def basket_session(basket_id: str) -> JSONResponse:
    # No API key — UUID is the one-time secret; queud extension fetches this in-browser.
    with _db() as conn:
        _purge_expired(conn)
        row = conn.execute(
            "SELECT session, end_url, proxy, consumed FROM baskets WHERE id = ?",
            (basket_id,),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="basket not found or expired")
        if row["consumed"]:
            raise HTTPException(status_code=410, detail="basket already used")
        conn.execute(
            "UPDATE baskets SET consumed = 1 WHERE id = ?",
            (basket_id,),
        )
    return JSONResponse(
        {
            "session": row["session"],
            "endUrl": row["end_url"],
            "proxy": row["proxy"],
        }
    )


QUEUD_EXTENSION_ID = "cinkmcgingnfflllnhdfckdfcfcnocjk"


@app.get("/basket/{basket_id}")
def basket_page(basket_id: str) -> HTMLResponse:
    """Browser lands here; page fetches session and pings queud extension."""
    html = f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"><title>queud</title></head>
<body style="background:#0a1628;color:#fff;font-family:system-ui,sans-serif;text-align:center;padding:3rem">
<p id="queud-status">Opening checkout…</p>
<p style="opacity:.7;font-size:14px">Requires queud Chrome extension v1.3.5 (reload at chrome://extensions).</p>
<script>
(function() {{
  window.__queudBasketInit = 1;
  const EXT_ID = {json.dumps(QUEUD_EXTENSION_ID)};
  const basketId = {json.dumps(basket_id)};
  const status = document.getElementById("queud-status");

  function fail(msg) {{
    status.textContent = msg;
    status.style.color = "#f87171";
  }}

  function fallbackLink(data) {{
    if (document.getElementById("queud-fallback")) return;
    const href =
      "chrome-extension://" + EXT_ID + "/checkout.html" +
      "?session=" + encodeURIComponent(data.session) +
      "&endUrl=" + encodeURIComponent(data.endUrl) +
      (data.proxy ? "&proxy=" + encodeURIComponent(data.proxy) : "");
    const a = document.createElement("a");
    a.id = "queud-fallback";
    a.href = href;
    a.textContent = "Click here to open checkout (queud)";
    a.style.cssText = "display:inline-block;margin-top:1.5rem;padding:12px 20px;background:#3498db;color:#fff;border-radius:8px;text-decoration:none;font-weight:600";
    document.body.appendChild(a);
  }}

  fetch("/basket/" + basketId + "/session")
    .then(function(r) {{
      if (!r.ok) throw new Error("Session " + r.status + " — link used or expired. Get a new Discord link.");
      return r.json();
    }})
    .then(function(data) {{
      if (typeof chrome !== "undefined" && chrome.runtime && chrome.runtime.sendMessage) {{
        chrome.runtime.sendMessage(
          EXT_ID,
          {{
            type: "QUEUD_CHECKOUT",
            session: data.session,
            endUrl: data.endUrl,
            proxy: data.proxy || ""
          }},
          function(resp) {{
            if (chrome.runtime.lastError) {{
              fail("Extension: " + chrome.runtime.lastError.message);
              fallbackLink(data);
              return;
            }}
            if (!resp || !resp.ok) {{
              fail("Checkout failed: " + (resp && resp.error ? resp.error : "unknown"));
              fallbackLink(data);
            }}
          }}
        );
        return;
      }}
      fail("Install queud extension v1.3.5, then reload this page");
      fallbackLink(data);
    }})
    .catch(function(err) {{
      fail(err.message || String(err));
    }});
}})();
</script>
</body></html>"""
    return HTMLResponse(html)


def main() -> None:
    import uvicorn

    host = os.environ.get("QUEUD_API_HOST", "0.0.0.0")
    # Railway injects PORT; fall back to QUEUD_API_PORT for local runs.
    port = int(os.environ.get("PORT", os.environ.get("QUEUD_API_PORT", "8787")))
    uvicorn.run("queud_api.server:app", host=host, port=port, reload=False)


if __name__ == "__main__":
    main()