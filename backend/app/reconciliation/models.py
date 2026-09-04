"""Internal records and reconciliation result models."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import Enum


class ReconciliationStatus(str, Enum):
    MATCHED = "MATCHED"
    AUTO_RESOLVED = "AUTO_RESOLVED"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    UNRESOLVED = "UNRESOLVED"


@dataclass(frozen=True)
class Invoice:
    transaction_id: str
    invoice_date: date
    amount_inr: Decimal
    currency: str


@dataclass(frozen=True)
class GatewayTransaction:
    transaction_id: str
    gateway_transaction_id: str
    transaction_date: date
    amount_inr: Decimal
    fee_inr: Decimal
    currency: str


@dataclass(frozen=True)
class BankSettlement:
    transaction_id: str
    bank_settlement_id: str
    settlement_date: date
    amount_inr: Decimal
    currency: str


@dataclass(frozen=True)
class ReconciliationResult:
    transaction_id: str
    status: ReconciliationStatus
    invoice_amount: Decimal
    gateway_amount: Decimal | None
    gateway_fee: Decimal
    expected_settlement: Decimal | None
    actual_settlement: Decimal | None
    variance: Decimal | None
    rule_applied: str
    evidence_ids: tuple[str, ...]
    confidence: str
    requires_review: bool
    explanation: str
