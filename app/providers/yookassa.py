"""Клиент YooKassa.

Намеренно без SDK: обычный HTTP-клиент с Basic Auth. Так проще
контролировать таймауты, ретраи и то, что мы доверяем только ответу API,
а не телу вебхука.
"""

from __future__ import annotations

import logging
from decimal import Decimal, InvalidOperation

import httpx

from app.providers.base import ProviderError, ProviderPayment

logger = logging.getLogger(__name__)


def to_kopecks(value: str) -> int:
    """'100.00' -> 10000. Округление вниз до копейки, без float."""
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ProviderError(f"invalid amount: {value!r}") from exc
    return int((amount * 100).to_integral_value())


class YooKassaProvider:
    def __init__(
        self,
        shop_id: str,
        secret_key: str,
        api_url: str = "https://api.yookassa.ru/v3",
        timeout: float = 10.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._api_url = api_url.rstrip("/")
        self._timeout = timeout
        self._client = client or httpx.AsyncClient(
            base_url=self._api_url,
            auth=(shop_id, secret_key),
            timeout=timeout,
        )

    async def fetch_payment(self, payment_id: str) -> ProviderPayment | None:
        try:
            response = await self._client.get(f"/payments/{payment_id}")
        except httpx.HTTPError as exc:
            logger.warning("yookassa request failed: %s", exc)
            raise ProviderError("provider is unavailable") from exc

        if response.status_code == 404:
            # Вебхук пришёл по платежу, которого у провайдера нет:
            # это либо подделка, либо чужой shop_id. Обрабатывать нечего.
            return None
        if response.status_code >= 400:
            logger.warning(
                "yookassa returned %s: %s", response.status_code, response.text[:200]
            )
            raise ProviderError(f"provider responded {response.status_code}")

        data = response.json()
        amount = data.get("amount") or {}
        return ProviderPayment(
            id=data["id"],
            status=data.get("status", "unknown"),
            amount_kopecks=to_kopecks(amount.get("value", "0")),
            currency=amount.get("currency", "RUB"),
            metadata={str(k): str(v) for k, v in (data.get("metadata") or {}).items()},
        )

    async def aclose(self) -> None:
        await self._client.aclose()
