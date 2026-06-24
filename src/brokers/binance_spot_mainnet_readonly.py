from __future__ import annotations

import hashlib
import hmac
import json
import time
import urllib.parse
from typing import Any, Mapping
from urllib import error, request

DEFAULT_MAINNET_BASE_URL = "https://api.binance.com"
_MAINNET_HOST = "api.binance.com"
_LOCAL_MOCK_PREFIXES: tuple[str, ...] = (
    "http://localhost",
    "http://127.0.0.1",
)
_FORBIDDEN_HOST_SUBSTRINGS: tuple[str, ...] = (
    "testnet.binance.vision",
    "api.binance.us",
    "fapi.binance.com",
    "dapi.binance.com",
    "vapi.binance.com",
    "eapi.binance.com",
    "papi.binance.com",
)
ALLOWED_ENDPOINTS: frozenset[str] = frozenset(
    {
        "/api/v3/ping",
        "/api/v3/time",
        "/api/v3/exchangeInfo",
        "/api/v3/account",
        "/api/v3/openOrders",
    }
)
_REDACTED = "[REDACTED]"
_DEFAULT_RECV_WINDOW_MS = 5000
_DEFAULT_TIMEOUT_SEC = 10.0


class BinanceMainnetReadonlyConfigError(ValueError):
    pass


class BinanceMainnetReadonlyRequestError(RuntimeError):
    pass


def is_mainnet_base_url(base_url: str) -> bool:
    if not isinstance(base_url, str) or not base_url.strip():
        return False
    candidate = base_url.strip().rstrip("/")
    lowered = candidate.lower()
    for forbidden in _FORBIDDEN_HOST_SUBSTRINGS:
        if forbidden in lowered:
            return False
    for prefix in _LOCAL_MOCK_PREFIXES:
        if lowered.startswith(prefix):
            return True
    parsed = urllib.parse.urlsplit(candidate)
    if parsed.scheme != "https" or not parsed.netloc:
        return False
    return parsed.netloc.lower() == _MAINNET_HOST


def _redact(text: str, *secrets: str) -> str:
    safe = str(text)
    for secret in secrets:
        if secret:
            safe = safe.replace(secret, _REDACTED)
    return safe


def _validate_endpoint(path: str) -> str:
    if not isinstance(path, str) or not path.startswith("/"):
        raise BinanceMainnetReadonlyConfigError(f"Endpoint path must start with '/': {path!r}")
    cleaned = path.split("?", 1)[0]
    if cleaned not in ALLOWED_ENDPOINTS:
        raise BinanceMainnetReadonlyConfigError(f"Endpoint not in readonly allowlist: {cleaned!r}")
    return cleaned


def build_query_string(params: Mapping[str, Any] | None) -> str:
    if not params:
        return ""
    items: list[tuple[str, str]] = []
    for key in sorted(params.keys()):
        value = params[key]
        if value is None:
            continue
        if isinstance(value, bool):
            items.append((str(key), "true" if value else "false"))
            continue
        items.append((str(key), str(value)))
    return urllib.parse.urlencode(items, doseq=False)


def sign_query(query_string: str, *, api_secret: str) -> str:
    if not isinstance(api_secret, str) or not api_secret:
        raise BinanceMainnetReadonlyConfigError("sign_query requires a non-empty api_secret")
    return hmac.new(
        api_secret.encode("utf-8"),
        msg=query_string.encode("utf-8"),
        digestmod=hashlib.sha256,
    ).hexdigest()


def resolve_credentials(
    *,
    api_key: str | None = None,
    api_secret: str | None = None,
    env: Mapping[str, str] | None = None,
) -> tuple[str, str]:
    import os

    source: Mapping[str, str] = env if env is not None else os.environ
    resolved_key = (api_key if api_key is not None else source.get("BINANCE_MAINNET_API_KEY")) or ""
    resolved_secret = (api_secret if api_secret is not None else source.get("BINANCE_MAINNET_API_SECRET")) or ""
    resolved_key = resolved_key.strip()
    resolved_secret = resolved_secret.strip()
    if not resolved_key:
        raise BinanceMainnetReadonlyConfigError("Missing BINANCE_MAINNET_API_KEY (or pass api_key=).")
    if not resolved_secret:
        raise BinanceMainnetReadonlyConfigError("Missing BINANCE_MAINNET_API_SECRET (or pass api_secret=).")
    return resolved_key, resolved_secret


def mask_api_key(api_key: str) -> str:
    text = str(api_key or "")
    if len(text) <= 4:
        return "*" * len(text)
    return ("*" * (len(text) - 4)) + text[-4:]


class BinanceSpotMainnetReadonlyClient:
    def __init__(
        self,
        *,
        api_key: str,
        api_secret: str,
        base_url: str = DEFAULT_MAINNET_BASE_URL,
        recv_window_ms: int = _DEFAULT_RECV_WINDOW_MS,
        timeout_seconds: float = _DEFAULT_TIMEOUT_SEC,
    ) -> None:
        if not is_mainnet_base_url(base_url):
            raise BinanceMainnetReadonlyConfigError(f"Invalid mainnet base URL: {base_url!r}")
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key.strip()
        self.api_secret = api_secret.strip()
        if not self.api_key or not self.api_secret:
            raise BinanceMainnetReadonlyConfigError("Readonly client requires non-empty key + secret")
        self.api_key_masked = mask_api_key(self.api_key)
        self.recv_window_ms = int(recv_window_ms)
        self.timeout_seconds = float(timeout_seconds)

    def ping(self) -> dict[str, Any]:
        return self._unsigned_json("GET", "/api/v3/ping")

    def server_time(self) -> dict[str, Any]:
        return self._unsigned_json("GET", "/api/v3/time")

    def exchange_info(self, symbols: list[str] | None = None) -> dict[str, Any]:
        params: dict[str, Any] = {}
        if symbols:
            normalized = [str(item).upper() for item in symbols if str(item).strip()]
            if len(normalized) == 1:
                params["symbol"] = normalized[0]
            elif normalized:
                params["symbols"] = json.dumps(normalized)
        return self._unsigned_json("GET", "/api/v3/exchangeInfo", params=params)

    def account(self) -> dict[str, Any]:
        return self._signed_json("GET", "/api/v3/account")

    def open_orders(self, *, symbol: str | None = None) -> list[dict[str, Any]]:
        params: dict[str, Any] = {}
        if symbol:
            params["symbol"] = str(symbol).upper()
        payload = self._signed_json("GET", "/api/v3/openOrders", params=params)
        if not isinstance(payload, list):
            raise BinanceMainnetReadonlyRequestError("Invalid openOrders payload: expected a list")
        return [dict(item) for item in payload]

    def _unsigned_json(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
    ) -> Any:
        return self._request_json(method, path, params=params, signed=False)

    def _signed_json(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
    ) -> Any:
        signed_params = dict(params or {})
        signed_params["timestamp"] = int(time.time() * 1000)
        signed_params["recvWindow"] = self.recv_window_ms
        query = build_query_string(signed_params)
        signature = sign_query(query, api_secret=self.api_secret)
        signed_params["signature"] = signature
        return self._request_json(method, path, params=signed_params, signed=True)

    def _request_json(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None,
        signed: bool,
    ) -> Any:
        cleaned = _validate_endpoint(path)
        query = build_query_string(params)
        url = f"{self.base_url}{cleaned}"
        if query:
            url = f"{url}?{query}"
        headers = {"X-MBX-APIKEY": self.api_key} if signed else {}
        req = request.Request(url=url, method=method.upper(), headers=headers)
        try:
            with request.urlopen(req, timeout=self.timeout_seconds) as response:
                body = response.read().decode("utf-8")
        except error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            message = _redact(body or str(exc), self.api_key, self.api_secret)
            raise BinanceMainnetReadonlyRequestError(f"HTTP {exc.code} calling {cleaned}: {message}") from None
        except Exception as exc:
            message = _redact(str(exc), self.api_key, self.api_secret)
            raise BinanceMainnetReadonlyRequestError(f"Request failed for {cleaned}: {message}") from None
        try:
            return json.loads(body or "{}")
        except Exception as exc:
            raise BinanceMainnetReadonlyRequestError(f"Invalid JSON from {cleaned}: {exc}") from None