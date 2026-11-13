"""Тесты провайдеров: разбор суммы и HTTP-клиент на MockTransport."""

from __future__ import annotations

from decimal import Decimal

import httpx
import pytest

from app.providers.base import ProviderError
from app.providers.yookassa import YooKassaProvider, to_kopecks


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("100.00", 10000),
        ("0.01", 1),
        ("1499.90", 149990),
        ("2", 200),
    ],
)
def test_to_kopecks(raw, expected):
    assert to_kopecks(raw) == expected


def test_to_kopecks_has_no_float_drift():
    # 0.1 + 0.2 во float даёт 0.30000000000000004 — здесь этого не происходит.
    assert to_kopecks(Decimal("0.1") + Decimal("0.2")) == 30


def test_invalid_amount():
    with pytest.raises(ProviderError):
        to_kopecks("сто рублей")


def _provider(handler) -> YooKassaProvider:
    client = httpx.AsyncClient(
        base_url="https://api.yookassa.ru/v3",
        transport=httpx.MockTransport(handler),
    )
    return YooKassaProvider("shop", "secret", client=client)


class TestFetchPayment:
    async def test_success(self):
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/v3/payments/pay_1"
            return httpx.Response(
                200,
                json={
                    "id": "pay_1",
                    "status": "succeeded",
                    "amount": {"value": "1499.90", "currency": "RUB"},
                    "metadata": {"user_ref": 42},
                },
            )

        payment = await _provider(handler).fetch_payment("pay_1")

        assert payment is not None
        assert payment.amount_kopecks == 149990
        assert payment.metadata == {"user_ref": "42"}
        assert payment.is_succeeded

    async def test_not_found(self):
        provider = _provider(lambda request: httpx.Response(404, json={}))

        assert await provider.fetch_payment("missing") is None

    async def test_server_error_raises(self):
        provider = _provider(lambda request: httpx.Response(500, json={}))

        with pytest.raises(ProviderError):
            await provider.fetch_payment("pay_1")

    async def test_network_error_raises(self):
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectTimeout("timeout")

        with pytest.raises(ProviderError):
            await _provider(handler).fetch_payment("pay_1")
