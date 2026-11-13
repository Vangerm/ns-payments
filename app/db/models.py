"""Модели: платёж и фискальный чек.

Деньги хранятся в копейках (int), а не во float: без ошибок округления.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Uuid, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin


class Payment(TimestampMixin, Base):
    __tablename__ = "payments"

    # Один платёж провайдера = одна строка. Уникальный индекс — последняя
    # линия обороны от двойного зачисления при повторной доставке вебхука.
    __table_args__ = (
        Index("uq_payments_provider_payment_id", "provider_payment_id", unique=True),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    provider: Mapped[str] = mapped_column(String(32), nullable=False, default="yookassa")
    provider_payment_id: Mapped[str] = mapped_column(String(128), nullable=False)
    user_ref: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    amount_kopecks: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="RUB")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="succeeded")
    paid_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )

    receipt: Mapped[Receipt | None] = relationship(
        back_populates="payment", lazy="selectin", uselist=False
    )


class Receipt(TimestampMixin, Base):
    __tablename__ = "receipts"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    payment_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("payments.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    provider: Mapped[str] = mapped_column(String(32), nullable=False, default="fake")
    fiscal_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="registered")
    error: Mapped[str | None] = mapped_column(String(512), nullable=True)

    payment: Mapped[Payment] = relationship(back_populates="receipt")
