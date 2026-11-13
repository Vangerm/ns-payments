"""Служебные и демонстрационные эндпоинты."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy import select

from app.db.models import Payment

router = APIRouter(tags=["service"])


@router.get("/healthz")
async def healthz(request: Request):
    """Проверка живости: приложение + БД."""
    engine = request.app.state.engine
    timeout = request.app.state.settings.healthcheck_timeout
    try:
        async with asyncio.timeout(timeout):
            async with engine.connect() as conn:
                await conn.execute(select(1))
    except Exception as exc:  # noqa: BLE001 - любой сбой = not ready
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"status": "degraded", "detail": str(exc)[:200]},
        )
    return {"status": "ok"}


@router.get("/payments/{provider_payment_id}")
async def get_payment(provider_payment_id: str, request: Request):
    """Карточка платежа — удобно смотреть результат после curl-а."""
    sessionmaker = request.app.state.sessionmaker
    async with sessionmaker() as session:
        payment = await session.scalar(
            select(Payment).where(
                Payment.provider_payment_id == provider_payment_id
            )
        )
        if payment is None:
            return JSONResponse(
                status_code=status.HTTP_404_NOT_FOUND,
                content={"detail": "payment not found"},
            )
        receipt = payment.receipt
        return {
            "id": str(payment.id),
            "provider_payment_id": payment.provider_payment_id,
            "user_ref": payment.user_ref,
            "amount_kopecks": payment.amount_kopecks,
            "currency": payment.currency,
            "status": payment.status,
            "paid_at": payment.paid_at.isoformat(),
            "receipt": (
                {
                    "status": receipt.status,
                    "fiscal_id": receipt.fiscal_id,
                    "url": receipt.url,
                    "error": receipt.error,
                }
                if receipt
                else None
            ),
        }
