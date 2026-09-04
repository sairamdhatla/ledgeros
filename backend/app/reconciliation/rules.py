"""Independent deterministic reconciliation rules."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal

from .models import BankSettlement, GatewayTransaction, Invoice, ReconciliationStatus

NORMAL_SETTLEMENT_DAYS = 3
MAX_SUPPORTED_SETTLEMENT_DAYS = 14


@dataclass(frozen=True)
class RuleDecision:
    status: ReconciliationStatus
    rule_applied: str
    confidence: str
    requires_review: bool
    explanation: str


def _days_after(invoice: Invoice, bank: BankSettlement) -> int:
    return (bank.settlement_date - invoice.invoice_date).days


def duplicate_gateway_rule(gateways: list[GatewayTransaction]) -> RuleDecision | None:
    if len(gateways) <= 1:
        return None
    return RuleDecision(
        ReconciliationStatus.NEEDS_REVIEW,
        "DUPLICATE_GATEWAY_TRANSACTION",
        "HIGH",
        True,
        f"Found {len(gateways)} gateway records for one transaction.",
    )


def missing_bank_rule(banks: list[BankSettlement]) -> RuleDecision | None:
    if banks:
        return None
    return RuleDecision(
        ReconciliationStatus.NEEDS_REVIEW,
        "MISSING_BANK_SETTLEMENT",
        "HIGH",
        True,
        "No bank settlement was found for the transaction.",
    )


def partial_payment_rule(invoice: Invoice, gateway: GatewayTransaction, bank: BankSettlement) -> RuleDecision | None:
    if gateway.amount_inr >= invoice.amount_inr or bank.amount_inr != gateway.amount_inr:
        return None
    return RuleDecision(
        ReconciliationStatus.NEEDS_REVIEW,
        "PARTIAL_PAYMENT",
        "HIGH",
        True,
        "Gateway and bank amounts agree, but the payment is lower than the invoice.",
    )


def gateway_fee_rule(invoice: Invoice, gateway: GatewayTransaction, bank: BankSettlement) -> RuleDecision | None:
    expected = gateway.amount_inr - gateway.fee_inr
    if gateway.amount_inr != invoice.amount_inr or gateway.fee_inr <= 0 or bank.amount_inr != expected:
        return None
    return RuleDecision(
        ReconciliationStatus.AUTO_RESOLVED,
        "GATEWAY_FEE_DEDUCTION",
        "HIGH",
        False,
        "Bank settlement equals the gateway amount after the recorded gateway fee.",
    )


def timing_difference_rule(invoice: Invoice, gateway: GatewayTransaction, bank: BankSettlement) -> RuleDecision | None:
    expected = gateway.amount_inr - gateway.fee_inr
    days_after = _days_after(invoice, bank)
    if (
        gateway.amount_inr != invoice.amount_inr
        or bank.amount_inr != expected
        or days_after <= NORMAL_SETTLEMENT_DAYS
        or days_after > MAX_SUPPORTED_SETTLEMENT_DAYS
    ):
        return None
    return RuleDecision(
        ReconciliationStatus.AUTO_RESOLVED,
        "SETTLEMENT_TIMING_DIFFERENCE",
        "HIGH",
        False,
        f"Amounts reconcile; settlement occurred {days_after} days after the invoice within the supported timing window.",
    )


def exact_match_rule(invoice: Invoice, gateway: GatewayTransaction, bank: BankSettlement) -> RuleDecision | None:
    expected = gateway.amount_inr - gateway.fee_inr
    days_after = _days_after(invoice, bank)
    if (
        gateway.amount_inr != invoice.amount_inr
        or bank.amount_inr != expected
        or gateway.fee_inr != 0
        or days_after < 0
        or days_after > NORMAL_SETTLEMENT_DAYS
    ):
        return None
    return RuleDecision(
        ReconciliationStatus.MATCHED,
        "EXACT_MATCH",
        "HIGH",
        False,
        "Invoice, gateway, and bank amounts reconcile within the normal settlement window.",
    )
