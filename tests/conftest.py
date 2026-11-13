"""Общие фикстуры: приложение на SQLite в памяти и фейковые провайдеры."""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass

import httpx
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import Settings
from app.db.base import Base
from app.main import create_app
from app.messaging.publisher import InMemoryPublisher
from app.providers.base import FiscalReceipt, ProviderError, ProviderPayment
from app.providers.fake import FakeFiscalProvider, FakePaymentProvider
from app.providers.yookassa import to_kopecks


class FailingProvider:
    """Провайдер недоступен: любой запрос — ProviderError."""

    async def fetch_payment(self, payment_id: str) -> ProviderPayment | None:
        raise ProviderError("provider is down")


class UnknownPaymentProvider:
    """Провайдера такого платежа нет (404)."""

    async def fetch_payment(self, payment_id: str) -> ProviderPayment | None:
        return None


class FailingFiscal:
    async def register_income(
        self, amount_kopecks: int, description: str
    ) -> FiscalReceipt:
        raise RuntimeError("lknpd is unavailable")


@dataclass
class Harness:
    client: httpx.AsyncClient
    publisher: InMemoryPublisher
    sessionmaker: async_sessionmaker
    fiscal: FakeFiscalProvider
    provider: object


def make_notification(
    payment_id: str = "pay_123",
    event: str = "payment.succeeded",
    amount: str = "100.00",
) -> dict:
    return {
        "type": "notification",
        "event": event,
        "object": {
            "id": payment_id,
            "status": "succeeded",
            "amount": {"value": amount, "currency": "RUB"},
            "metadata": {"user_ref": "user-1"},
        },
    }


HarnessFactory = Callable[..., Awaitable[Harness]]


@pytest_asyncio.fixture
async def harness_factory() -> AsyncIterator[HarnessFactory]:
    to_close: list[tuple[httpx.AsyncClient, object]] = []

    async def _make(
        provider=None,
        fiscal=None,
        publisher=None,
    ) -> Harness:
        engine = create_async_engine(
            "sqlite+aiosqlite:///:memory:",
            connect_args={"check_same_thread": False},
        )
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
        provider = provider or FakePaymentProvider()
        fiscal = fiscal or FakeFiscalProvider()
        publisher = publisher or InMemoryPublisher()

        app = create_app(
            Settings(app_env="test", database_url="sqlite+aiosqlite:///:memory:"),
            provider=provider,
            fiscal=fiscal,
            publisher=publisher,
            engine=engine,
            sessionmaker=sessionmaker,
        )

        client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        )
        to_close.append((client, engine))
        return Harness(
            client=client,
            publisher=publisher,
            sessionmaker=sessionmaker,
            fiscal=fiscal,
            provider=provider,
        )

    yield _make

    for client, engine in to_close:
        await client.aclose()
        await engine.dispose()


@pytest_asyncio.fixture
async def harness(harness_factory: HarnessFactory) -> Harness:
    return await harness_factory()


def kopecks(value: str) -> int:
    return to_kopecks(value)
