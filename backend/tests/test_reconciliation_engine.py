from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.reconciliation.engine import reconcile_records
from app.reconciliation.models import BankSettlement, GatewayTransaction, Invoice, ReconciliationStatus
from app.reconciliation.normalizer import normalize_invoice


def records(
    *,
    invoice_amount: str = "50000",
    gateway_amount: str = "50000",
    fee: str = "0",
    bank_amount: str | None = "50000",
    days_after: int = 2,
    gateway_count: int = 1,
) -> tuple[list[Invoice], list[GatewayTransaction], list[BankSettlement]]:
    transaction_id = "TXN-TEST-001"
    invoice_date = date(2025, 1, 1)
    invoice = Invoice(transaction_id, invoice_date, Decimal(invoice_amount), "INR")
    gateways = [
        GatewayTransaction(
            transaction_id,
            f"GW-TEST-{index}",
            invoice_date,
            Decimal(gateway_amount),
            Decimal(fee),
            "INR",
        )
        for index in range(gateway_count)
    ]
    banks = [] if bank_amount is None else [
        BankSettlement(
            transaction_id,
            "BNK-TEST-001",
            invoice_date + timedelta(days=days_after),
            Decimal(bank_amount),
            "INR",
        )
    ]
    return [invoice], gateways, banks


@pytest.mark.parametrize(
    ("kwargs", "status", "rule"),
    [
        ({}, ReconciliationStatus.MATCHED, "EXACT_MATCH"),
        ({"fee": "750", "bank_amount": "49250"}, ReconciliationStatus.AUTO_RESOLVED, "GATEWAY_FEE_DEDUCTION"),
        ({"days_after": 10}, ReconciliationStatus.AUTO_RESOLVED, "SETTLEMENT_TIMING_DIFFERENCE"),
        ({"gateway_amount": "45000", "bank_amount": "45000"}, ReconciliationStatus.NEEDS_REVIEW, "PARTIAL_PAYMENT"),
        ({"gateway_count": 2}, ReconciliationStatus.NEEDS_REVIEW, "DUPLICATE_GATEWAY_TRANSACTION"),
        ({"bank_amount": None}, ReconciliationStatus.NEEDS_REVIEW, "MISSING_BANK_SETTLEMENT"),
        ({"bank_amount": "49000"}, ReconciliationStatus.UNRESOLVED, "UNEXPLAINED_DISCREPANCY"),
    ],
)
def test_reconciliation_rules(kwargs: dict[str, object], status: ReconciliationStatus, rule: str) -> None:
    result = reconcile_records(*records(**kwargs))[0]
    assert result.status == status
    assert result.rule_applied == rule


def test_fee_calculation_and_evidence_are_deterministic() -> None:
    result = reconcile_records(*records(fee="750", bank_amount="49250"))[0]
    assert result.expected_settlement == Decimal("49250")
    assert result.actual_settlement == Decimal("49250")
    assert result.variance == Decimal("0")
    assert result.evidence_ids == ("TXN-TEST-001", "GW-TEST-0", "BNK-TEST-001")
    assert result.confidence == "HIGH"
    assert result.requires_review is False

    assert result == reconcile_records(*records(fee="750", bank_amount="49250"))[0]


@pytest.mark.parametrize("amount", ["0", "-1", "not-a-number"])
def test_invalid_or_zero_invoice_amounts_are_rejected(amount: str) -> None:
    with pytest.raises(ValueError):
        normalize_invoice(
            {
                "transaction_id": "TXN-TEST-001",
                "invoice_date": "2025-01-01",
                "amount_inr": amount,
                "currency": "INR",
            }
        )


def test_missing_required_invoice_value_is_rejected() -> None:
    with pytest.raises(ValueError):
        normalize_invoice(
            {
                "transaction_id": "TXN-TEST-001",
                "invoice_date": "2025-01-01",
                "amount_inr": "50000",
                "currency": "",
            }
        )
