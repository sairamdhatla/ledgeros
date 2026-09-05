from datetime import date
from decimal import Decimal

import pytest

from app.reconciliation.models import BankSettlement, GatewayTransaction
from app.services.razorpay.adapter import RazorpayAdapter
from app.services.razorpay.models import (
    NormalizedReconRecord,
    RazorpayOrder,
    RazorpayPayment,
    RazorpayReconItem,
    RazorpaySettlement,
)
from tests.fixtures.razorpay_fixtures import (
    SAMPLE_PAYMENT_PAYLOAD,
    SAMPLE_RECON_PAYLOAD,
    SAMPLE_SETTLEMENT_PAYLOAD,
)


class MockRazorpayProvider:
    def __init__(
        self,
        payments: list[RazorpayPayment],
        settlements: list[RazorpaySettlement],
        recon_items: list[RazorpayReconItem] | None = None,
    ) -> None:
        self.payments = payments
        self.settlements = settlements
        self.recon_items = recon_items or []

    def list_payments(self, **kwargs) -> list[RazorpayPayment]:
        return self.payments

    def list_settlements(self, **kwargs) -> list[RazorpaySettlement]:
        return self.settlements

    def get_payment(self, payment_id: str) -> RazorpayPayment:
        return self.payments[0]

    def get_settlement(self, settlement_id: str) -> RazorpaySettlement:
        return self.settlements[0]

    def get_settlement_recon(self, **kwargs) -> list[RazorpayReconItem]:
        return self.recon_items

    def get_order(self, order_id: str) -> RazorpayOrder:
        raise NotImplementedError


def test_payment_to_gateway_transaction() -> None:
    payment = RazorpayPayment.model_validate(SAMPLE_PAYMENT_PAYLOAD)
    gateway = RazorpayAdapter.payment_to_gateway_transaction(payment)

    assert isinstance(gateway, GatewayTransaction)
    assert gateway.gateway_transaction_id == "pay_TEST0000000001"
    assert gateway.transaction_id == "order_TEST0000000001"
    assert gateway.amount_inr == Decimal("5000.00")
    # fee = 10000 paise (100 INR), tax = 1800 paise (18 INR) -> total fee deduction = 118 INR
    assert gateway.fee_inr == Decimal("118.00")
    assert gateway.currency == "INR"
    assert isinstance(gateway.transaction_date, date)


def test_fee_calculation_never_hardcodes_tax_percentage() -> None:
    """Verify that fee_inr strictly uses fee + tax from the payload without hardcoding 18%."""
    custom_fee_payload = {
        **SAMPLE_PAYMENT_PAYLOAD,
        "fee": 5000,   # 50.00 INR
        "tax": 250,    # 2.50 INR (custom non-18% tax, e.g. special category or state tax)
    }
    payment = RazorpayPayment.model_validate(custom_fee_payload)
    gateway = RazorpayAdapter.payment_to_gateway_transaction(payment)

    # 50.00 + 2.50 = 52.50 INR (strictly reflects data, not 50 * 0.18 = 9.00)
    assert gateway.fee_inr == Decimal("52.50")


def test_zero_fee_payment_normalization() -> None:
    zero_fee_payload = {
        **SAMPLE_PAYMENT_PAYLOAD,
        "fee": 0,
        "tax": 0,
    }
    payment = RazorpayPayment.model_validate(zero_fee_payload)
    gateway = RazorpayAdapter.payment_to_gateway_transaction(payment)
    assert gateway.fee_inr == Decimal("0.00")


def test_fallback_transaction_id_when_order_and_invoice_are_none() -> None:
    standalone_payload = {
        **SAMPLE_PAYMENT_PAYLOAD,
        "order_id": None,
        "invoice_id": None,
    }
    payment = RazorpayPayment.model_validate(standalone_payload)
    gateway = RazorpayAdapter.payment_to_gateway_transaction(payment)
    assert gateway.transaction_id == "pay_TEST0000000001"


def test_settlement_to_bank_settlement() -> None:
    settlement = RazorpaySettlement.model_validate(SAMPLE_SETTLEMENT_PAYLOAD)
    bank = RazorpayAdapter.settlement_to_bank_settlement(settlement)

    assert isinstance(bank, BankSettlement)
    assert bank.bank_settlement_id == "UTRTEST987654321"
    assert bank.amount_inr == Decimal("4882.00")
    assert bank.currency == "INR"
    assert isinstance(bank.settlement_date, date)


def test_recon_item_to_normalized_record_preserves_all_fields() -> None:
    items = [RazorpayReconItem.model_validate(raw) for raw in SAMPLE_RECON_PAYLOAD["items"]]
    record = RazorpayAdapter.recon_item_to_normalized_record(items[0])

    assert isinstance(record, NormalizedReconRecord)
    assert record.entity_id == "pay_TEST0000000001"
    assert record.settlement_id == "setl_BATCH00000001"
    assert record.settlement_utr == "UTRTEST987654321"
    assert record.order_receipt == "INV-2025-001"
    assert record.transaction_id == "INV-2025-001"
    assert record.gross_amount_inr == Decimal("5000.00")
    assert record.credit_inr == Decimal("4882.00")
    assert record.debit_inr == Decimal("0.00")
    assert record.fee_inr == Decimal("100.00")
    assert record.tax_inr == Decimal("18.00")
    assert record.total_deduction_inr == Decimal("118.00")
    assert record.card_network == "MasterCard"
    assert record.is_payment is True
    assert record.is_refund is False


def test_multiple_payments_belonging_to_one_settlement() -> None:
    """Verify that multiple payments in one settlement batch are normalized without conflating amounts."""
    items = [RazorpayReconItem.model_validate(raw) for raw in SAMPLE_RECON_PAYLOAD["items"]]
    gateways, banks = RazorpayAdapter.recon_items_to_reconciliation_records(items)

    # 2 payments (pay_1 and pay_2) are extracted (refund is excluded from standard gateway transactions)
    assert len(gateways) == 2
    assert len(banks) == 2

    # Both share the same settlement UTR
    assert banks[0].bank_settlement_id == "UTRTEST987654321"
    assert banks[1].bank_settlement_id == "UTRTEST987654321"

    # Transaction 1: 5000 gross - 118 fee = 4882 bank credit
    assert gateways[0].transaction_id == "INV-2025-001"
    assert gateways[0].gateway_transaction_id == "pay_TEST0000000001"
    assert gateways[0].amount_inr == Decimal("5000.00")
    assert gateways[0].fee_inr == Decimal("118.00")
    assert banks[0].amount_inr == Decimal("4882.00")

    # Transaction 2: 2500 gross - 59 fee = 2441 bank credit
    assert gateways[1].transaction_id == "INV-2025-002"
    assert gateways[1].gateway_transaction_id == "pay_TEST0000000002"
    assert gateways[1].amount_inr == Decimal("2500.00")
    assert gateways[1].fee_inr == Decimal("59.00")
    assert banks[1].amount_inr == Decimal("2441.00")


def test_refund_adjustment_records_not_treated_as_ordinary_payments() -> None:
    """Verify that refund/adjustment records cannot be coerced into standard payment gateway transactions."""
    items = [RazorpayReconItem.model_validate(raw) for raw in SAMPLE_RECON_PAYLOAD["items"]]
    refund_item = items[2]  # rfnd_TEST0000000001
    refund_record = RazorpayAdapter.recon_item_to_normalized_record(refund_item)

    assert refund_record.is_payment is False
    assert refund_record.is_refund is True
    assert refund_record.debit_inr == Decimal("500.00")
    assert refund_record.credit_inr == Decimal("0.00")
    assert refund_record.payment_id == "pay_TEST0000000001"

    # Refuses conversion to standard GatewayTransaction
    with pytest.raises(ValueError, match="Cannot convert non-payment record"):
        refund_record.to_gateway_transaction()

    # Refuses conversion to standard BankSettlement
    with pytest.raises(ValueError, match="Cannot convert non-payment record"):
        refund_record.to_bank_settlement()


def test_fetch_and_normalize_recon() -> None:
    items = [RazorpayReconItem.model_validate(raw) for raw in SAMPLE_RECON_PAYLOAD["items"]]
    provider = MockRazorpayProvider([], [], recon_items=items)

    gateways, banks = RazorpayAdapter.fetch_and_normalize_recon(provider, year=2025, month=1)
    assert len(gateways) == 2
    assert len(banks) == 2


def test_payment_linked_to_settlement_through_entity_id() -> None:
    """Verify that entity_id accurately maintains the linkage between transaction and settlement batch."""
    item = RazorpayReconItem.model_validate(SAMPLE_RECON_PAYLOAD["items"][0])
    record = RazorpayAdapter.recon_item_to_normalized_record(item)

    assert record.entity_id == "pay_TEST0000000001"
    assert record.settlement_id == "setl_BATCH00000001"
    assert record.settlement_utr == "UTRTEST987654321"

    bank_settlement = record.to_bank_settlement()
    assert bank_settlement.bank_settlement_id == "UTRTEST987654321"
    assert bank_settlement.transaction_id == "INV-2025-001"
    assert bank_settlement.amount_inr == Decimal("4882.00")


def test_recon_item_preserves_arbitrary_non_18_percent_tax() -> None:
    """Verify that recon normalization never imposes an 18% tax rate."""
    custom_tax_recon = {
        **SAMPLE_RECON_PAYLOAD["items"][0],
        "fee": 4000,  # 40.00 INR
        "tax": 200,   # 2.00 INR (5% tax rate)
        "credit": 495800,  # 5000 - 42 = 4958.00 INR
    }
    item = RazorpayReconItem.model_validate(custom_tax_recon)
    record = RazorpayAdapter.recon_item_to_normalized_record(item)

    assert record.fee_inr == Decimal("40.00")
    assert record.tax_inr == Decimal("2.00")
    assert record.total_deduction_inr == Decimal("42.00")
    assert record.credit_inr == Decimal("4958.00")

    gateway = record.to_gateway_transaction()
    assert gateway.fee_inr == Decimal("42.00")
