"""Контракты внешних систем: провайдер платежей и фискализация.

Сервис зависит от протоколов, а не от конкретных SDK: в тестах вместо
сети подставляются фейки, в проде — реальные клиенты.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


class ProviderError(Exception):
    """Провайдер недоступен или ответил ошибкой — запрос можно повторить."""


@dataclass(frozen=True)
class ProviderPayment:
    """Платёж в терминах провайдера. Сумма — в копейках."""

    id: str
    status: str
    amount_kopecks: int
    currency: str = "RUB"
    metadata: dict[str, str] = field(default_factory=dict)

    @property
    def is_succeeded(self) -> bool:
        return self.status == "succeeded"


class PaymentProvider(Protocol):
    """Платёжный провайдер: умеет отдавать платёж по id."""

    async def fetch_payment(self, payment_id: str) -> ProviderPayment | None:
        """Вернуть платёж или None, если такого платежа у провайдера нет."""
        ...


@dataclass(frozen=True)
class FiscalReceipt:
    id: str | None
    url: str | None
    status: str


class FiscalProvider(Protocol):
    """Фискализация: регистрация дохода (чек)."""

    async def register_income(
        self, amount_kopecks: int, description: str
    ) -> FiscalReceipt:
        ...
