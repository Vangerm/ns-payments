"""Фискализация через API ЛК «Мой налог» (НПД).

Библиотека `nalogovich` — опциональная зависимость: импортируется лениво,
чтобы сервис можно было запускать и тестировать без неё.
"""

from __future__ import annotations

import logging

from app.providers.base import FiscalReceipt

logger = logging.getLogger(__name__)


class NalogFiscalProvider:
    def __init__(self, inn: str, password: str, description: str) -> None:
        self._inn = inn
        self._password = password
        self._description = description

    async def register_income(
        self, amount_kopecks: int, description: str | None = None
    ) -> FiscalReceipt:
        try:
            from nalogovich.enums import PaymentType
            from nalogovich.lknpd import NpdClient
        except ImportError as exc:  # pragma: no cover - защита от отсутствия extra
            raise RuntimeError(
                "nalogovich is not installed: pip install '.[fiscal]'"
            ) from exc

        amount = amount_kopecks / 100
        async with NpdClient(inn=self._inn, password=self._password) as client:
            await client.auth()
            income = await client.create_check(
                name=description or self._description,
                amount=amount,
                payment_type=PaymentType.WIRE,
            )
            receipt_id = income.approved_receipt_uuid
            logger.info("nalog receipt created: %s", receipt_id)
            return FiscalReceipt(
                id=str(receipt_id),
                url=f"https://lknpd.nalog.ru/api/v1/receipt/{self._inn}/{receipt_id}/print",
                status="registered",
            )
