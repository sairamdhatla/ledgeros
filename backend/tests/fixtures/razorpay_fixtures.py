"""Official Razorpay API mock payloads and shared test fixtures."""

from decimal import Decimal
from typing import Any

from app.services.razorpay import RazorpayError
from app.services.razorpay.models import RazorpayReconItem

SAMPLE_PAYMENT_PAYLOAD = {
    "id": "pay_TEST0000000001",
    "entity": "payment",
    "amount": 500000,
    "currency": "INR",
    "status": "captured",
    "order_id": "order_TEST0000000001",
    "invoice_id": "inv_TEST0000000001",
    "international": False,
    "method": "card",
    "amount_refunded": 0,
    "refund_status": None,
    "captured": True,
    "description": "Subscription invoice",
    "card_id": "card_TEST0000000001",
    "bank": "HDFC",
    "wallet": None,
    "vpa": None,
    "email": "finance@example.com",
    "contact": "+919876543210",
    "fee": 10000,
    "tax": 1800,
    "error_code": None,
    "error_description": None,
    "created_at": 1735689600,
}

SAMPLE_PAYMENTS_LIST_PAYLOAD = {
    "entity": "collection",
    "count": 2,
    "items": [
        SAMPLE_PAYMENT_PAYLOAD,
        {
            "id": "pay_TEST0000000002",
            "entity": "payment",
            "amount": 250000,
            "currency": "INR",
            "status": "captured",
            "order_id": "order_TEST0000000002",
            "invoice_id": None,
            "international": False,
            "method": "upi",
            "amount_refunded": 0,
            "refund_status": None,
            "captured": True,
            "description": "UPI payment",
            "card_id": None,
            "bank": None,
            "wallet": None,
            "vpa": "user@upi",
            "email": "user@example.com",
            "contact": "+919123456780",
            "fee": 0,
            "tax": 0,
            "error_code": None,
            "error_description": None,
            "created_at": 1735776000,
        },
    ],
}

SAMPLE_SETTLEMENT_PAYLOAD = {
    "id": "setl_TEST0000000001",
    "entity": "settlement",
    "amount": 488200,
    "status": "processed",
    "fees": 10000,
    "tax": 1800,
    "utr": "UTRTEST987654321",
    "created_at": 1735862400,
}

SAMPLE_SETTLEMENTS_LIST_PAYLOAD = {
    "entity": "collection",
    "count": 1,
    "items": [SAMPLE_SETTLEMENT_PAYLOAD],
}

SAMPLE_RECON_PAYLOAD = {
    "entity": "collection",
    "count": 3,
    "items": [
        {
            "entity_id": "pay_TEST0000000001",
            "type": "payment",
            "debit": 0,
            "credit": 488200,
            "amount": 500000,
            "currency": "INR",
            "fee": 10000,
            "tax": 1800,
            "on_hold": False,
            "settled": True,
            "created_at": 1735689600,
            "settled_at": 1735862400,
            "settlement_id": "setl_BATCH00000001",
            "description": "Payment for subscription",
            "notes": {"client": "Acme Corp"},
            "payment_id": None,
            "settlement_utr": "UTRTEST987654321",
            "order_id": "order_TEST0000000001",
            "order_receipt": "INV-2025-001",
            "method": "card",
            "card_network": "MasterCard",
            "card_issuer": "HDFC",
            "card_type": "credit",
            "dispute_id": None,
        },
        {
            "entity_id": "pay_TEST0000000002",
            "type": "payment",
            "debit": 0,
            "credit": 244100,
            "amount": 250000,
            "currency": "INR",
            "fee": 5000,
            "tax": 900,
            "on_hold": False,
            "settled": True,
            "created_at": 1735776000,
            "settled_at": 1735862400,
            "settlement_id": "setl_BATCH00000001",
            "description": "UPI Payment for invoice",
            "notes": None,
            "payment_id": None,
            "settlement_utr": "UTRTEST987654321",
            "order_id": "order_TEST0000000002",
            "order_receipt": "INV-2025-002",
            "method": "upi",
            "card_network": None,
            "card_issuer": None,
            "card_type": None,
            "dispute_id": None,
        },
        {
            "entity_id": "rfnd_TEST0000000001",
            "type": "refund",
            "debit": 50000,
            "credit": 0,
            "amount": 50000,
            "currency": "INR",
            "fee": 0,
            "tax": 0,
            "on_hold": False,
            "settled": True,
            "created_at": 1735800000,
            "settled_at": 1735862400,
            "settlement_id": "setl_BATCH00000001",
            "description": "Partial refund",
            "notes": "Customer returned item",
            "payment_id": "pay_TEST0000000001",
            "settlement_utr": "UTRTEST987654321",
            "order_id": "order_TEST0000000001",
            "order_receipt": "INV-2025-001",
            "method": "card",
            "card_network": "MasterCard",
            "card_issuer": "HDFC",
            "card_type": "credit",
            "dispute_id": None,
        },
    ],
}

SAMPLE_ORDER_PAYLOAD = {
    "id": "order_TEST0000000001",
    "entity": "order",
    "amount": 500000,
    "currency": "INR",
    "receipt": "RCP-TEST-001",
    "status": "paid",
    "created_at": 1735686000,
}


class MockRazorpayProvider:
    """Mock Razorpay provider for testing."""

    def __init__(
        self,
        recon_items: list[RazorpayReconItem] | None = None,
        should_fail: bool = False,
        error: Exception | None = None,
    ) -> None:
        self.recon_items = recon_items or []
        self.should_fail = should_fail
        self.error = error

    def get_settlement_recon(self, **kwargs: Any) -> list[RazorpayReconItem]:
        if self.should_fail:
            if self.error:
                raise self.error
            raise RazorpayError("Mock Razorpay error")
        return self.recon_items


def sample_recon_items() -> list[RazorpayReconItem]:
    """Create sample recon items for testing."""
    return [
        RazorpayReconItem(
            entity_id="pay_TEST0000000001",
            type="payment",
            debit=0,
            credit=488200,
            amount=500000,
            currency="INR",
            fee=10000,
            tax=1800,
            on_hold=False,
            settled=True,
            created_at=1735689600,
            settled_at=1735862400,
            settlement_id="setl_BATCH00000001",
            description="Payment for subscription",
            notes={},
            payment_id=None,
            settlement_utr="UTRTEST987654321",
            order_id="order_TEST0000000001",
            order_receipt="INV-2025-001",
            method="card",
            card_network="MasterCard",
            card_issuer="HDFC",
            card_type="credit",
            dispute_id=None,
        ),
        RazorpayReconItem(
            entity_id="pay_TEST0000000002",
            type="payment",
            debit=0,
            credit=244100,
            amount=250000,
            currency="INR",
            fee=5000,
            tax=900,
            on_hold=False,
            settled=True,
            created_at=1735776000,
            settled_at=1735862400,
            settlement_id="setl_BATCH00000001",
            description="UPI Payment",
            notes=None,
            payment_id=None,
            settlement_utr="UTRTEST987654321",
            order_id="order_TEST0000000002",
            order_receipt="INV-2025-002",
            method="upi",
            card_network=None,
            card_issuer=None,
            card_type=None,
            dispute_id=None,
        ),
    ]
