"""Приём уведомлений платёжного провайдера."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, ValidationError

from app.providers.base import ProviderError

logger = logging.getLogger(__name__)
router = APIRouter(tags=["webhooks"])


class PaymentObject(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    status: str | None = None
    metadata: dict[str, Any] = {}


class Notification(BaseModel):
    model_config = ConfigDict(extra="allow")

    type: str | None = None
    event: str | None = None
    object: PaymentObject


@router.post("/webhooks/yookassa")
async def yookassa_webhook(request: Request):
    """Обработка вебхука YooKassa.

    Коды ответа:
    * 200 — платёж обработан (или уже был обработан ранее);
    * 202 — событие не про успешный платёж, обрабатывать нечего;
    * 400 — тело запроса не разобрать;
    * 502 — провайдер недоступен, пусть повторит доставку.
    """
    try:
        payload = Notification.model_validate(await request.json())
    except ValidationError as exc:
        logger.warning("malformed webhook: %s", exc.errors()[:1])
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"detail": "malformed notification"},
        )
    except Exception:  # noqa: BLE001 - битый JSON
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"detail": "invalid json"},
        )

    if payload.event != "payment.succeeded":
        # Нас интересует только успешная оплата; остальные события
        # подтверждаем, чтобы провайдер не повторял доставку.
        return JSONResponse(
            status_code=status.HTTP_202_ACCEPTED,
            content={"status": "ignored", "event": payload.event},
        )

    service = request.app.state.payment_service
    publisher = request.app.state.publisher

    try:
        result = await service.process(payload.object.id)
    except ProviderError:
        logger.warning("provider unavailable, asking for retry")
        return JSONResponse(
            status_code=status.HTTP_502_BAD_GATEWAY,
            content={"detail": "provider unavailable"},
        )

    if result.event is not None:
        # Публикуем после коммита: подписчики не получат событие
        # о платеже, который откатился.
        await publisher.publish(result.event)

    body = {"status": result.status}
    if result.reason:
        body["reason"] = result.reason
    code = (
        status.HTTP_202_ACCEPTED
        if result.status == "ignored"
        else status.HTTP_200_OK
    )
    return JSONResponse(status_code=code, content=body)
