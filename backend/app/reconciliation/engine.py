"""Deterministic reconciliation engine for the three operational sources."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from .matcher import TransactionRecords, match_records
from .models import BankSettlement, GatewayTransaction, Invoice, ReconciliationResult, ReconciliationStatus
from .normalizer import load_bank_settlements, load_gateway_transactions, load_invoices
from .rules import (
    RuleDecision,
    duplicate_gateway_rule,
    exact_match_rule,
    gateway_fee_rule,
    missing_bank_rule,
    partial_payment_rule,
    timing_difference_rule,
)


def _evidence(records: TransactionRecords) -> tuple[str, ...]:
    ids = [records.invoice.transaction_id]
    ids.extend(gateway.gateway_transaction_id for gateway in records.gateways)
    ids.extend(bank.bank_settlement_id for bank in records.banks)
    return tuple(ids)


def _result(records: TransactionRecords, decision: RuleDecision) -> ReconciliationResult:
    gateway = records.gateways[0] if records.gateways else None
    bank = records.banks[0] if records.banks else None
    expected = gateway.amount_inr - gateway.fee_inr if gateway else None
    actual = bank.amount_inr if bank else None
    variance = actual - expected if actual is not None and expected is not None else None
    return ReconciliationResult(
        transaction_id=records.invoice.transaction_id,
        status=decision.status,
        invoice_amount=records.invoice.amount_inr,
        gateway_amount=gateway.amount_inr if gateway else None,
        gateway_fee=gateway.fee_inr if gateway else Decimal("0"),
        expected_settlement=expected,
        actual_settlement=actual,
        variance=variance,
        rule_applied=decision.rule_applied,
        evidence_ids=_evidence(records),
        confidence=decision.confidence,
        requires_review=decision.requires_review,
        explanation=decision.explanation,
    )


def _unresolved(records: TransactionRecords) -> ReconciliationResult:
    gateway = records.gateways[0] if records.gateways else None
    bank = records.banks[0] if records.banks else None
    expected = gateway.amount_inr - gateway.fee_inr if gateway else None
    actual = bank.amount_inr if bank else None
    variance = actual - expected if actual is not None and expected is not None else None
    return ReconciliationResult(
        transaction_id=records.invoice.transaction_id,
        status=ReconciliationStatus.UNRESOLVED,
        invoice_amount=records.invoice.amount_inr,
        gateway_amount=gateway.amount_inr if gateway else None,
        gateway_fee=gateway.fee_inr if gateway else Decimal("0"),
        expected_settlement=expected,
        actual_settlement=actual,
        variance=variance,
        rule_applied="UNEXPLAINED_DISCREPANCY",
        evidence_ids=_evidence(records),
        confidence="LOW",
        requires_review=True,
        explanation="Available evidence is insufficient to safely resolve the discrepancy.",
    )


def reconcile_transaction(records: TransactionRecords) -> ReconciliationResult:
    """Evaluate one transaction using risk-sensitive, explicit rules."""
    duplicate = duplicate_gateway_rule(records.gateways)
    if duplicate:
        return _result(records, duplicate)

    missing_bank = missing_bank_rule(records.banks)
    if missing_bank:
        return _result(records, missing_bank)

    if not records.gateways:
        return _unresolved(records)

    gateway = records.gateways[0]
    bank = records.banks[0]
    for rule in (
        lambda: partial_payment_rule(records.invoice, gateway, bank),
        lambda: gateway_fee_rule(records.invoice, gateway, bank),
        lambda: timing_difference_rule(records.invoice, gateway, bank),
        lambda: exact_match_rule(records.invoice, gateway, bank),
    ):
        decision = rule()
        if decision:
            return _result(records, decision)
    return _unresolved(records)


def reconcile_records(
    invoices: list[Invoice],
    gateways: list[GatewayTransaction],
    banks: list[BankSettlement],
) -> list[ReconciliationResult]:
    """Reconcile each invoice independently using only operational records."""
    return [reconcile_transaction(records) for records in match_records(invoices, gateways, banks)]


def reconcile_csv_files(
    invoices_path: Path,
    gateways_path: Path,
    banks_path: Path,
) -> list[ReconciliationResult]:
    """Load and reconcile the three operational CSV files."""
    return reconcile_records(
        load_invoices(invoices_path),
        load_gateway_transactions(gateways_path),
        load_bank_settlements(banks_path),
    )
