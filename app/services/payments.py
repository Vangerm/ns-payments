"""Прикладная логика обработки платежа.

Порядок действий:
1. Перепроверяем платёж у провайдера (телу вебхука не доверяем).
2. Проверяем, что он действительно успешный и содержит, кому зачислять.
3. Вставляем платёж в БД; уникальный индекс не даёт зачислить дважды.
4. Регистрируем чек; ошибка фискализации не отменяет платёж.
5. Возвращаем событие — его публикует слой API после коммита.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import Payment, Receipt
from app.db.session import session_scope
from app.messaging.publisher import PaymentSucceeded
from app.providers.base import FiscalProvider, PaymentProvider

logger = logging.getLogger(__name__)

ProcessStatus = Literal["processed", "duplicate", "ignored"]


@dataclass(frozen=True)
class ProcessResult:
    status: ProcessStatus
    reason: str | None = None
    event: PaymentSucceeded | None = None


class PaymentService:
    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        provider: PaymentProvider,
        fiscal: FiscalProvider,
        receipt_description: str = "Оплата услуг",
    ) -> None:
        self._sessionmaker = sessionmaker
        self._provider = provider
        self._fiscal = fiscal
        self._receipt_description = receipt_description

    async def process(self, provider_payment_id: str) -> ProcessResult:
        payment = await self._provider.fetch_payment(provider_payment_id)

        if payment is None:
            logger.warning("unknown payment: %s", provider_payment_id)
            return ProcessResult("ignored", reason="payment_not_found")
        if not payment.is_succeeded:
            return ProcessResult("ignored", reason=f"status={payment.status}")
        if payment.currency != "RUB":
            return ProcessResult("ignored", reason=f"currency={payment.currency}")
        if payment.amount_kopecks <= 0:
            return ProcessResult("ignored", reason="non_positive_amount")

        user_ref = payment.metadata.get("user_ref")
        if not user_ref:
            logger.warning("no user_ref in payment %s", payment.id)
            return ProcessResult("ignored", reason="no_user_ref")

        async with session_scope(self._sessionmaker) as session:
            existing = await session.scalar(
                select(Payment).where(Payment.provider_payment_id == payment.id)
            )
            if existing is not None:
                logger.info("duplicate webhook for %s", payment.id)
                return ProcessResult("duplicate", reason="already_processed")

            row = Payment(
                provider="yookassa",
                provider_payment_id=payment.id,
                user_ref=user_ref,
                amount_kopecks=payment.amount_kopecks,
                currency=payment.currency,
                status="succeeded",
                paid_at=datetime.now(tz=UTC),
            )
            try:
                # Точка сохранения: конфликт по уникальному индексу не должен
                # ломать внешнюю транзакцию.
                async with session.begin_nested():
                    session.add(row)
                    await session.flush()
            except IntegrityError:
                logger.info("race: payment %s is already stored", payment.id)
                return ProcessResult("duplicate", reason="already_processed")

            receipt_url = await self._register_receipt(session, row)

        event = PaymentSucceeded(
            payment_id=str(row.id),
            provider_payment_id=row.provider_payment_id,
            user_ref=row.user_ref,
            amount_kopecks=row.amount_kopecks,
            currency=row.currency,
            receipt_url=receipt_url,
        )
        logger.info("payment processed: %s (%s kop)", row.id, row.amount_kopecks)
        return ProcessResult("processed", event=event)

    async def _register_receipt(self, session: AsyncSession, row: Payment) -> str | None:
        """Чек не должен блокировать зачисление денег.

        Если фискализация недоступна, платёж всё равно сохраняется,
        а чек помечается failed — его дошлёт фоновая проверка.
        """
        try:
            receipt = await self._fiscal.register_income(
                amount_kopecks=row.amount_kopecks,
                description=self._receipt_description,
            )
        except Exception as exc:  # noqa: BLE001 - внешний сервис, логируем и живём
            logger.exception("receipt registration failed for %s", row.id)
            session.add(
                Receipt(
                    payment_id=row.id,
                    provider="nalog",
                    status="failed",
                    error=str(exc)[:500],
                )
            )
            return None

        session.add(
            Receipt(
                payment_id=row.id,
                provider="nalog",
                fiscal_id=receipt.id,
                url=receipt.url,
                status=receipt.status,
            )
        )
        return receipt.url
