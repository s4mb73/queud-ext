"""EPSF / tmpt solving (HTTP, headless pool, CapSolver)."""

from __future__ import annotations

import hashlib
import json
import random
import time
from typing import Any

import requests as http_requests

from queud_aio.cookies import has_cookie
from queud_aio.log_util import log, warn
from queud_aio.proxy import parse_proxy
from queud_aio.settings import Settings
from queud_aio.tmpt_solver import HttpTmptSolver


def capsolver_post(api_key: str, payload: dict[str, Any]) -> dict[str, Any]:
    resp = http_requests.post(
        "https://api.capsolver.com/createTask", json=payload, timeout=45
    )
    resp.raise_for_status()
    return resp.json()


def capsolver_result(api_key: str, task_id: str) -> dict[str, Any]:
    resp = http_requests.post(
        "https://api.capsolver.com/getTaskResult",
        json={"clientKey": api_key, "taskId": task_id},
        timeout=45,
    )
    resp.raise_for_status()
    return resp.json()


def solve_recaptcha_enterprise(
    settings: Settings,
    page_url: str,
    site_key: str,
    page_action: str,
    proxy_line: str,
) -> str:
    if not settings.capsolver_api_key:
        raise RuntimeError("CAPSOLVER_API_KEY not set")
    task: dict[str, Any] = {
        "type": "ReCaptchaV3EnterpriseTaskProxyLess",
        "websiteURL": page_url,
        "websiteKey": site_key,
        "pageAction": page_action,
    }
    if proxy_line:
        _, _, capsolver_proxy = parse_proxy(proxy_line)
        task["type"] = "ReCaptchaV3EnterpriseTask"
        task["proxy"] = capsolver_proxy

    created = capsolver_post(
        settings.capsolver_api_key,
        {"clientKey": settings.capsolver_api_key, "task": task},
    )
    if created.get("errorId"):
        raise RuntimeError(f"CapSolver createTask failed: {created}")
    task_id = created.get("taskId")
    if not task_id:
        raise RuntimeError(f"CapSolver returned no taskId: {created}")

    log(f"CapSolver task {task_id} ({task['type']})...")
    deadline = time.time() + settings.capsolver_max_wait
    while time.time() < deadline:
        time.sleep(settings.capsolver_poll_interval)
        result = capsolver_result(settings.capsolver_api_key, task_id)
        if result.get("errorId"):
            raise RuntimeError(f"CapSolver getTaskResult failed: {result}")
        if result.get("status") == "ready":
            return result["solution"]["gRecaptchaResponse"]
    raise RuntimeError("CapSolver timed out waiting for reCAPTCHA token")


def refresh_tmpt_capsolver(client: Any, page_url: str) -> None:
    s = client.settings
    client.session.get(page_url, allow_redirects=False)
    client.session.get(f"{client.base_url}/eps-mgr")
    fpjs = hashlib.md5(str(random.random()).encode()).hexdigest()
    client.session.get(
        f"{client.base_url}/eps/log?hasPublicKeyCredential=true"
        f"&hasConditionalMediation=true&conditionalMediationAvailable=true"
        f"&platformAuthenticator=true&err=&fpjs={fpjs}"
    )
    captcha_token = solve_recaptcha_enterprise(
        s,
        page_url,
        s.recaptcha_site_key,
        s.recaptcha_page_action,
        client.proxy_line,
    )
    body = json.dumps(
        {
            "hostname": client.hostname,
            "key": s.recaptcha_site_key,
            "token": captcha_token,
        }
    )
    headers = {
        "Content-Type": "application/json",
        "Origin": client.base_url,
        "Referer": page_url,
    }
    gec = client.session.post(
        f"{client.base_url}/epsf/gec/v3/{s.recaptcha_page_action}",
        headers=headers,
        data=body,
    )
    if gec.status_code >= 400:
        raise RuntimeError(f"GEC failed: HTTP {gec.status_code} {gec.text[:200]}")
    if not has_cookie(client.session, "tmpt"):
        raise RuntimeError("GEC succeeded but tmpt cookie was not set")


def refresh_tmpt_http(client: Any, page_url: str) -> None:
    s = client.settings
    HttpTmptSolver(
        client.session,
        client.base_url,
        site_key=s.recaptcha_site_key,
        proxy_line=getattr(client, "proxy_line", ""),
    ).refresh(page_url, s.recaptcha_page_action, s.recaptcha_site_key)


def _http_tmpt_ok(client: Any, page_url: str) -> bool:
    resp = client.get(page_url, allow_redirects=True)
    if resp.status_code == 200 and "ism-module" in resp.text:
        return True
    if has_cookie(client.session, "tmpt", client.hostname) and resp.status_code < 500:
        if "Let's Get Your Identity Verified" not in resp.text:
            return True
    return False


def refresh_tmpt(client: Any, page_url: str) -> None:
    solver = client.settings.tmpt_solver

    if solver in ("headless", "headless-pool", "browser"):
        from queud_aio.headless_tmpt import refresh_tmpt_headless

        refresh_tmpt_headless(
            client, page_url, use_pool=solver in ("headless", "headless-pool")
        )
        return

    if solver == "capsolver":
        refresh_tmpt_capsolver(client, page_url)
        log("tmpt acquired")
        return

    if solver == "auto":
        try:
            refresh_tmpt_http(client, page_url)
            if _http_tmpt_ok(client, page_url):
                log("tmpt acquired (http)")
                return
            warn("HTTP tmpt did not pass EPSF — falling back to headless pool")
        except Exception as exc:
            warn(f"HTTP tmpt failed ({exc}) — falling back to headless pool")
        from queud_aio.headless_tmpt import refresh_tmpt_headless

        refresh_tmpt_headless(client, page_url, use_pool=True)
        return

    try:
        refresh_tmpt_http(client, page_url)
    except Exception as exc:
        if not client.settings.tmpt_auto_fallback:
            raise
        warn(f"HTTP tmpt failed ({exc}) — falling back to headless pool")
        from queud_aio.headless_tmpt import refresh_tmpt_headless

        refresh_tmpt_headless(client, page_url, use_pool=True)
        return
    if client.settings.tmpt_auto_fallback and not _http_tmpt_ok(client, page_url):
        warn("HTTP tmpt weak — retrying with headless pool")
        from queud_aio.headless_tmpt import refresh_tmpt_headless

        refresh_tmpt_headless(client, page_url, use_pool=True)
        return
    log("tmpt acquired")