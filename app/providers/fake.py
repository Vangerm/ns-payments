"""Заглушки для локального запуска и тестов.

`FakePaymentProvider` возвращает платёж по детерминированному правилу,
поэтому демо можно прогнать curl-ом без аккаунта YooKassa.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from app.providers.base import FiscalReceipt, ProviderPayment


@dataclass
class FakePaymentProvider:
    """Платёж по id. Сумму и статус можно задать явно."""

    amount_kopecks: int = 10000
    status: str = "succeeded"
    currency: str = "RUB"
    payments: dict[str, ProviderPayment] = field(default_factory=dict)

    async def fetch_payment(self, payment_id: str) -> ProviderPayment | None:
        if payment_id in self.payments:
            return self.payments[payment_id]
        if payment_id.startswith("not_found"):
            return None
        return ProviderPayment(
            id=payment_id,
            status=self.status,
            amount_kopecks=self.amount_kopecks,
            currency=self.currency,
            metadata={"user_ref": "demo-user", "description": "Пополнение баланса"},
        )


@dataclass
class FakeFiscalProvider:
    """Чек с предсказуемым id — удобно проверять в тестах."""

    calls: list[tuple[int, str]] = field(default_factory=list)

    async def register_income(
        self, amount_kopecks: int, description: str
    ) -> FiscalReceipt:
        self.calls.append((amount_kopecks, description))
        fiscal_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{amount_kopecks}:{description}"))
        return FiscalReceipt(
            id=fiscal_id,
            url=f"https://lknpd.example/receipt/{fiscal_id}/print",
            status="registered",
        )
