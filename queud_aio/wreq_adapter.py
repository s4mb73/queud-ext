"""wreq blocking client — curl_cffi-compatible request surface."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import timedelta
from typing import Any
from urllib.parse import urlencode

from wreq import Cookie, Emulation, Proxy
from wreq import exceptions as wreq_exc
from wreq.blocking import Client as WreqClient

PROXY_ERRORS = (
    wreq_exc.ProxyConnectionError,
    wreq_exc.ConnectionError,
    wreq_exc.ConnectionResetError,
    wreq_exc.TimeoutError,
)


def resolve_emulation(name: str) -> Emulation:
    key = name.strip().lower().replace("_", "").replace("-", "")
    if key.startswith("chrome"):
        attr = f"Chrome{key[6:]}"
    else:
        attr = "Chrome124"
    return getattr(Emulation, attr, Emulation.Chrome124)


class _CookieLike:
    def __init__(self, cookie: Cookie) -> None:
        self.name = cookie.name
        self.value = cookie.value
        self.domain = cookie.domain or ""
        self.path = cookie.path or "/"


class WreqCookieJarAdapter:
    def __init__(self, jar: Any, base_url: str) -> None:
        self._jar = jar
        self._base_url = base_url.rstrip("/")

    @property
    def jar(self) -> list[_CookieLike]:
        if self._jar is None:
            return []
        return [_CookieLike(cookie) for cookie in self._jar.get_all()]

    def _cookie_url(self, domain: str | None) -> str:
        if domain:
            host = domain.lstrip(".")
            return f"https://{host}/"
        return f"{self._base_url}/"

    def set(
        self,
        name: str,
        value: str,
        domain: str | None = None,
        path: str = "/",
    ) -> None:
        if self._jar is None:
            return
        cookie = Cookie(
            name,
            value,
            domain=(domain or "").lstrip("."),
            path=path or "/",
        )
        self._jar.add(cookie, self._cookie_url(domain))


class WreqResponse:
    def __init__(self, resp: Any) -> None:
        self._resp = resp
        self._text_cache: str | None = None

    @property
    def status_code(self) -> int:
        return int(str(self._resp.status).split()[0])

    @property
    def text(self) -> str:
        if self._text_cache is None:
            self._text_cache = self._resp.text()
        return self._text_cache

    @property
    def url(self) -> str:
        return str(self._resp.url)

    @property
    def headers(self) -> dict[str, str]:
        try:
            items = self._resp.headers.items()
        except AttributeError:
            items = list(self._resp.headers)
        return {str(k): str(v) for k, v in items}

    def json(self) -> Any:
        return self._resp.json()

    def raise_for_status(self) -> None:
        self._resp.raise_for_status()


class WreqHttpSession:
    """Blocking wreq session used by TmptClient."""

    def __init__(
        self,
        emulation: str,
        *,
        proxy_url: str = "",
        timeout: int = 60,
        base_url: str = "",
    ) -> None:
        kwargs: dict[str, Any] = {
            "emulation": resolve_emulation(emulation),
            "cookie_store": True,
        }
        if proxy_url:
            kwargs["proxies"] = [Proxy.all(proxy_url)]
        self._client = WreqClient(**kwargs)
        self._timeout = timeout
        self._base_url = base_url.rstrip("/")
        self.cookies = WreqCookieJarAdapter(self._client.cookie_jar, self._base_url)

    def _request(self, method: str, url: str, **kwargs: Any) -> WreqResponse:
        timeout = kwargs.pop("timeout", self._timeout)
        if isinstance(timeout, (int, float)):
            timeout = timedelta(seconds=float(timeout))
        kwargs["timeout"] = timeout
        fn = getattr(self._client, method)
        return WreqResponse(fn(url, **kwargs))

    def get(self, url: str, **kwargs: Any) -> WreqResponse:
        return self._request("get", url, **kwargs)

    def post(self, url: str, **kwargs: Any) -> WreqResponse:
        return self._request("post", url, **kwargs)

    def post_form(
        self,
        url: str,
        fields: str | Mapping[str, Any] | Sequence[tuple[str, Any]],
        **kwargs: Any,
    ) -> WreqResponse:
        """POST application/x-www-form-urlencoded (wreq needs `body=`, not `data=`)."""
        if isinstance(fields, str):
            body = fields
        else:
            body = urlencode(fields, doseq=True)
        headers = dict(kwargs.pop("headers", {}) or {})
        headers.setdefault("Content-Type", "application/x-www-form-urlencoded")
        return self.post(url, body=body, headers=headers, **kwargs)

    def put(self, url: str, **kwargs: Any) -> WreqResponse:
        return self._request("put", url, **kwargs)

    def delete(self, url: str, **kwargs: Any) -> WreqResponse:
        return self._request("delete", url, **kwargs)

    def close(self) -> None:
        self._client.close()