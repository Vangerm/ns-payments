"""Сборка FastAPI-приложения.

Зависимости передаются в `create_app` явно: тот же код используется
и в проде (реальные клиенты), и в тестах (фейки, SQLite в памяти).
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api import system, webhooks
from app.config import Settings, get_settings
from app.db.session import create_engine, create_sessionmaker
from app.messaging.publisher import LogPublisher, NatsPublisher
from app.providers.base import FiscalProvider, PaymentProvider
from app.providers.fake import FakeFiscalProvider, FakePaymentProvider
from app.providers.fiscal_nalog import NalogFiscalProvider
from app.providers.yookassa import YooKassaProvider
from app.services.payments import PaymentService

logger = logging.getLogger(__name__)


def build_fiscal_provider(settings: Settings) -> FiscalProvider:
    if settings.fiscal_mode == "nalog":
        if not settings.fiscal_inn or not settings.fiscal_password:
            raise RuntimeError("FISCAL_INN and FISCAL_PASSWORD are required")
        return NalogFiscalProvider(
            inn=settings.fiscal_inn.get_secret_value(),
            password=settings.fiscal_password.get_secret_value(),
            description="Оплата услуг",
        )
    return FakeFiscalProvider()


def build_payment_provider(settings: Settings, mode: str) -> PaymentProvider:
    if mode == "fake":
        return FakePaymentProvider()
    return YooKassaProvider(
        shop_id=settings.yookassa_shop_id,
        secret_key=settings.yookassa_secret_key.get_secret_value(),
        api_url=settings.yookassa_api_url,
        timeout=settings.yookassa_timeout,
    )


def create_app(
    settings: Settings | None = None,
    *,
    provider_mode: str | None = None,
    provider: PaymentProvider | None = None,
    fiscal: FiscalProvider | None = None,
    publisher=None,
    engine=None,
    sessionmaker=None,
) -> FastAPI:
    settings = settings or get_settings()
    logging.basicConfig(
        level=settings.log_level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    engine = engine or create_engine(settings.database_url)
    sessionmaker = sessionmaker or create_sessionmaker(engine)
    provider = provider or build_payment_provider(
        settings, provider_mode or ("fake" if settings.app_env == "local" else "yookassa")
    )
    fiscal = fiscal or build_fiscal_provider(settings)
    publisher = publisher or LogPublisher()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        nc = None
        if settings.nats_url:
            import nats

            nc = await nats.connect(settings.nats_url)
            app.state.publisher = NatsPublisher(nc, settings.events_subject)
            logger.info("nats connected: %s", settings.nats_url)
        try:
            yield
        finally:
            if nc is not None:
                await nc.close()
            if hasattr(provider, "aclose"):
                await provider.aclose()  # type: ignore[attr-defined]
            await engine.dispose()

    app = FastAPI(
        title="ns-payments",
        version="1.0.0",
        description="Приём платежей: вебхук → сверка у провайдера → БД → чек → событие",
        lifespan=lifespan,
    )

    app.state.settings = settings
    app.state.engine = engine
    app.state.sessionmaker = sessionmaker
    app.state.provider = provider
    app.state.fiscal = fiscal
    app.state.publisher = publisher
    app.state.payment_service = PaymentService(sessionmaker, provider, fiscal)

    app.include_router(webhooks.router)
    app.include_router(system.router)
    return app


app = create_app()
