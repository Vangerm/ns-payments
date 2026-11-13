"""Публикация событий для других сервисов.

Реализации:
* `NatsPublisher` — боевой вариант через NATS;
* `LogPublisher` — локальный, если NATS не настроен;
* `InMemoryPublisher` — для тестов (собирает события в список).
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from typing import Protocol

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PaymentSucceeded:
    payment_id: str
    provider_payment_id: str
    user_ref: str
    amount_kopecks: int
    currency: str
    receipt_url: str | None = None

    def as_dict(self) -> dict:
        return asdict(self)


class EventPublisher(Protocol):
    async def publish(self, event: PaymentSucceeded) -> None: ...


class NatsPublisher:
    """Публикует событие в subject; id платежа — ключ дедупликации."""

    def __init__(self, nc, subject: str) -> None:
        self._nc = nc
        self._subject = subject

    async def publish(self, event: PaymentSucceeded) -> None:
        payload = {
            "event": "payment.succeeded",
            "correlation_id": event.payment_id,
            "data": event.as_dict(),
        }
        await self._nc.publish(
            self._subject, json.dumps(payload, ensure_ascii=False).encode()
        )
        await self._nc.flush()
        logger.info("event published: %s -> %s", event.payment_id, self._subject)


class LogPublisher:
    async def publish(self, event: PaymentSucceeded) -> None:
        logger.info("event (no nats): %s", event.as_dict())


@dataclass
class InMemoryPublisher:
    events: list[PaymentSucceeded] = field(default_factory=list)

    async def publish(self, event: PaymentSucceeded) -> None:
        self.events.append(event)
