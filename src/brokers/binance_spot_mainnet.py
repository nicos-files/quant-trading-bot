from __future__ import annotations

from typing import Any, Mapping

from src.brokers.binance_spot_mainnet_readonly import (
    DEFAULT_MAINNET_BASE_URL,
    BinanceMainnetReadonlyConfigError,
    BinanceMainnetReadonlyRequestError,
    BinanceSpotMainnetReadonlyClient,
    build_query_string,
    is_mainnet_base_url,
    mask_api_key,
    sign_query,
)

LIVE_API_KEY_ENV = "BINANCE_LIVE_API_KEY"
LIVE_API_SECRET_ENV = "BINANCE_LIVE_API_SECRET"

ALLOWED_ENDPOINTS: frozenset[str] = frozenset(
    {
        "/api/v3/ping",
        "/api/v3/time",
        "/api/v3/exchangeInfo",
        "/api/v3/account",
        "/api/v3/openOrders",
        "/api/v3/order",
    }
)


class BinanceMainnetConfigError(BinanceMainnetReadonlyConfigError):
    pass


class BinanceMainnetRequestError(BinanceMainnetReadonlyRequestError):
    pass


def resolve_credentials(
    *,
    api_key: str | None = None,
    api_secret: str | None = None,
    env: Mapping[str, str] | None = None,
) -> tuple[str, str]:
    import os

    source: Mapping[str, str] = env if env is not None else os.environ
    resolved_key = (api_key if api_key is not None else source.get(LIVE_API_KEY_ENV)) or ""
    resolved_secret = (api_secret if api_secret is not None else source.get(LIVE_API_SECRET_ENV)) or ""
    resolved_key = resolved_key.strip()
    resolved_secret = resolved_secret.strip()
    if not resolved_key:
        raise BinanceMainnetConfigError(f"Missing {LIVE_API_KEY_ENV} (or pass api_key=).")
    if not resolved_secret:
        raise BinanceMainnetConfigError(f"Missing {LIVE_API_SECRET_ENV} (or pass api_secret=).")
    return resolved_key, resolved_secret


class BinanceSpotMainnetClient(BinanceSpotMainnetReadonlyClient):
    def open_orders(self, *, symbol: str | None = None) -> list[dict[str, Any]]:
        params: dict[str, Any] = {}
        if symbol:
            params["symbol"] = str(symbol).upper()
        payload = self._signed_json("GET", "/api/v3/openOrders", params=params)
        if not isinstance(payload, list):
            raise BinanceMainnetRequestError("Invalid openOrders payload: expected a list")
        return [dict(item) for item in payload]

    def place_order(self, *, params: Mapping[str, Any]) -> dict[str, Any]:
        payload = self._signed_json("POST", "/api/v3/order", params=params)
        if not isinstance(payload, Mapping):
            raise BinanceMainnetRequestError("Invalid order payload: expected an object")
        return dict(payload)

    def _request_json(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None,
        signed: bool,
    ) -> Any:
        cleaned = _validate_endpoint(path)
        return super()._request_json(method, cleaned, params=params, signed=signed)


def _validate_endpoint(path: str) -> str:
    if not isinstance(path, str) or not path.startswith("/"):
        raise BinanceMainnetConfigError(f"Endpoint path must start with '/': {path!r}")
    cleaned = path.split("?", 1)[0]
    if cleaned not in ALLOWED_ENDPOINTS:
        raise BinanceMainnetConfigError(f"Endpoint not in live allowlist: {cleaned!r}")
    return cleaned


__all__ = [
    "ALLOWED_ENDPOINTS",
    "BinanceMainnetConfigError",
    "BinanceMainnetRequestError",
    "BinanceSpotMainnetClient",
    "DEFAULT_MAINNET_BASE_URL",
    "LIVE_API_KEY_ENV",
    "LIVE_API_SECRET_ENV",
    "build_query_string",
    "is_mainnet_base_url",
    "mask_api_key",
    "resolve_credentials",
    "sign_query",
]