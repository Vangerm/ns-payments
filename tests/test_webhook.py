"""Тесты вебхука: happy path, идемпотентность и защита от подделок."""

from __future__ import annotations

import pytest
from sqlalchemy import func, select

from app.db.models import Payment, Receipt
from app.providers.base import ProviderPayment
from tests.conftest import FailingProvider, UnknownPaymentProvider, make_notification


async def count(sessionmaker, model) -> int:
    async with sessionmaker() as session:
        return await session.scalar(select(func.count()).select_from(model))


class TestHappyPath:
    async def test_payment_is_stored_and_event_published(self, harness):
        response = await harness.client.post(
            "/webhooks/yookassa", json=make_notification()
        )

        assert response.status_code == 200
        assert response.json() == {"status": "processed"}
        assert await count(harness.sessionmaker, Payment) == 1
        assert await count(harness.sessionmaker, Receipt) == 1
        assert len(harness.publisher.events) == 1

        event = harness.publisher.events[0]
        assert event.provider_payment_id == "pay_123"
        assert event.amount_kopecks == 10000
        assert event.receipt_url

    async def test_payload_amount_is_not_trusted(self, harness_factory):
        """В вебхуке сумма 100.00, у провайдера — 50.00. Храним данные провайдера."""
        from app.providers.fake import FakePaymentProvider

        harness = await harness_factory(provider=FakePaymentProvider(amount_kopecks=5000))

        response = await harness.client.post(
            "/webhooks/yookassa", json=make_notification(amount="100.00")
        )

        assert response.status_code == 200
        async with harness.sessionmaker() as session:
            payment = await session.scalar(select(Payment))
        assert payment is not None
        assert payment.amount_kopecks == 5000

    async def test_receipt_uses_provider_amount(self, harness):
        await harness.client.post("/webhooks/yookassa", json=make_notification())

        assert harness.fiscal.calls == [(10000, "Оплата услуг")]

    async def test_payment_card(self, harness):
        await harness.client.post("/webhooks/yookassa", json=make_notification())

        response = await harness.client.get("/payments/pay_123")

        assert response.status_code == 200
        body = response.json()
        assert body["amount_kopecks"] == 10000
        assert body["receipt"]["status"] == "registered"


class TestIdempotency:
    async def test_repeated_webhook_is_stored_once(self, harness):
        first = await harness.client.post(
            "/webhooks/yookassa", json=make_notification()
        )
        second = await harness.client.post(
            "/webhooks/yookassa", json=make_notification()
        )

        assert first.json() == {"status": "processed"}
        assert second.status_code == 200
        assert second.json() == {"status": "duplicate", "reason": "already_processed"}

        assert await count(harness.sessionmaker, Payment) == 1
        assert await count(harness.sessionmaker, Receipt) == 1
        assert len(harness.publisher.events) == 1, "событие не должно дублироваться"
        assert len(harness.fiscal.calls) == 1, "чек не должен пробиваться дважды"


class TestIgnored:
    @pytest.mark.parametrize(
        "event",
        ["payment.canceled", "payment.waiting_for_capture"],
    )
    async def test_not_succeeded_event(self, harness, event):
        response = await harness.client.post(
            "/webhooks/yookassa",
            json=make_notification(event=event),
        )

        assert response.status_code == 202
        assert response.json()["status"] == "ignored"
        assert await count(harness.sessionmaker, Payment) == 0

    async def test_provider_does_not_know_payment(self, harness_factory):
        harness = await harness_factory(provider=UnknownPaymentProvider())

        response = await harness.client.post(
            "/webhooks/yookassa", json=make_notification(payment_id="fake_1")
        )

        assert response.status_code == 202
        assert response.json()["reason"] == "payment_not_found"
        assert await count(harness.sessionmaker, Payment) == 0

    async def test_missing_user_ref(self, harness):
        harness.provider.payments["pay_no_user"] = ProviderPayment(
            id="pay_no_user", status="succeeded", amount_kopecks=10000, metadata={}
        )

        response = await harness.client.post(
            "/webhooks/yookassa", json=make_notification(payment_id="pay_no_user")
        )

        assert response.status_code == 202
        assert response.json()["reason"] == "no_user_ref"
        assert await count(harness.sessionmaker, Payment) == 0


class TestFailures:
    async def test_provider_is_down_returns_502(self, harness_factory):
        harness = await harness_factory(provider=FailingProvider())

        response = await harness.client.post(
            "/webhooks/yookassa", json=make_notification()
        )

        assert response.status_code == 502
        assert await count(harness.sessionmaker, Payment) == 0

    async def test_malformed_json_returns_400(self, harness):
        response = await harness.client.post(
            "/webhooks/yookassa",
            content=b"not a json",
            headers={"Content-Type": "application/json"},
        )

        assert response.status_code == 400
        assert response.json()["detail"] == "invalid json"

    async def test_payload_without_object_returns_400(self, harness):
        response = await harness.client.post(
            "/webhooks/yookassa", json={"event": "payment.succeeded"}
        )

        assert response.status_code == 400

    async def test_fiscal_failure_does_not_block_payment(self, harness_factory):
        """Чек не пробился — деньги всё равно зачислены, чек помечен failed."""
        from tests.conftest import FailingFiscal

        harness = await harness_factory(fiscal=FailingFiscal())

        response = await harness.client.post(
            "/webhooks/yookassa", json=make_notification()
        )

        assert response.status_code == 200
        async with harness.sessionmaker() as session:
            receipt = await session.scalar(select(Receipt))
        assert receipt is not None
        assert receipt.status == "failed"
        assert "lknpd" in (receipt.error or "")
