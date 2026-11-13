"""Настройки приложения: читаются из переменных окружения и .env."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Конфигурация сервиса.

    Секреты хранятся в ``SecretStr``: они не попадают в логи и repr.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: Literal["local", "test", "prod"] = "local"
    log_level: str = "INFO"

    database_url: str = (
        "postgresql+asyncpg://payments:payments@localhost:5432/payments"
    )

    # Очередь необязательна: без NATS сервис работает, события уходят в лог.
    nats_url: str | None = None
    events_subject: str = "payments.succeeded"

    # YooKassa: shop_id + secret_key. Для демо по умолчанию sandbox-заглушка.
    yookassa_shop_id: str = "demo-shop"
    yookassa_secret_key: SecretStr = SecretStr("demo-secret")
    yookassa_api_url: str = "https://api.yookassa.ru/v3"
    yookassa_timeout: float = 10.0

    # Фискализация: fake — локальная заглушка, nalog — реальный ЛК НПД.
    fiscal_mode: Literal["fake", "nalog"] = "fake"
    fiscal_inn: SecretStr | None = None
    fiscal_password: SecretStr | None = None

    # Сколько ждать БД при проверке /healthz.
    healthcheck_timeout: float = 2.0


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
