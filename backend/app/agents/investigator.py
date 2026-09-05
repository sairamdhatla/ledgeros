"""Evidence-first exception investigation with safe deterministic fallback."""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from typing import Any

from pydantic import ValidationError

from app.reconciliation.models import BankSettlement, GatewayTransaction, Invoice, ReconciliationResult, ReconciliationStatus

from .models import (
    BankEvidence,
    DiscrepancyType,
    GatewayEvidence,
    InvestigationContext,
    InvestigationResult,
    InvoiceEvidence,
    ReconciliationEvidence,
    RecommendedAction,
    RootCause,
)
from .provider import CONFIDENCE_THRESHOLD, InvestigationProvider, ProviderError, configured_provider


def build_context(
    invoice: Invoice,
    gateways: list[GatewayTransaction],
    banks: list[BankSettlement],
    reconciliation: ReconciliationResult,
) -> InvestigationContext:
    """Build a compact context from only the records for one reconciliation case."""
    if invoice.transaction_id != reconciliation.transaction_id:
        raise ValueError("invoice and reconciliation case IDs do not match")
    if any(record.transaction_id != invoice.transaction_id for record in gateways + banks):
        raise ValueError("source record does not belong to the requested case")

    gateway_evidence = tuple(
        GatewayEvidence(
            transaction_id=record.gateway_transaction_id,
            invoice_reference_id=record.transaction_id,
            gross_amount_inr=record.amount_inr,
            fee_inr=record.fee_inr,
            net_amount_inr=record.amount_inr - record.fee_inr,
            transaction_date=record.transaction_date,
        )
        for record in gateways
    )
    bank_evidence = tuple(
        BankEvidence(
            settlement_id=record.bank_settlement_id,
            reference_id=record.transaction_id,
            amount_inr=record.amount_inr,
            settlement_date=record.settlement_date,
        )
        for record in banks
    )
    evidence_ids = tuple(reconciliation.evidence_ids)
    known_ids = {invoice.transaction_id, *(record.gateway_transaction_id for record in gateways), *(record.bank_settlement_id for record in banks)}
    if not set(evidence_ids).issubset(known_ids):
        raise ValueError("reconciliation evidence contains an unknown source ID")
    return InvestigationContext(
        case_id=invoice.transaction_id,
        invoice=InvoiceEvidence(invoice_id=invoice.transaction_id, amount_inr=invoice.amount_inr, invoice_date=invoice.invoice_date),
        gateway=gateway_evidence,
        bank=bank_evidence,
        reconciliation=ReconciliationEvidence(
            case_id=reconciliation.transaction_id,
            deterministic_rule=reconciliation.rule_applied,
            deterministic_status=reconciliation.status.value,
            deterministic_reason=reconciliation.explanation,
            deterministic_discrepancy=_discrepancy_text(reconciliation),
            evidence_ids=evidence_ids,
            evidence_consistent=reconciliation.status not in {ReconciliationStatus.NEEDS_REVIEW, ReconciliationStatus.UNRESOLVED} or reconciliation.rule_applied != "UNEXPLAINED_DISCREPANCY",
        ),
    )


def _discrepancy_text(result: ReconciliationResult) -> str:
    if result.variance is None:
        return "Settlement amount is unavailable."
    return f"Settlement variance is {result.variance} INR."


def _fallback_discrepancy(context: InvestigationContext) -> DiscrepancyType:
    mapping = {
        "GATEWAY_FEE_DEDUCTION": DiscrepancyType.GATEWAY_FEE,
        "SETTLEMENT_TIMING_DIFFERENCE": DiscrepancyType.SETTLEMENT_TIMING,
        "PARTIAL_PAYMENT": DiscrepancyType.PARTIAL_PAYMENT,
        "DUPLICATE_GATEWAY_TRANSACTION": DiscrepancyType.DUPLICATE_TRANSACTION,
        "MISSING_BANK_SETTLEMENT": DiscrepancyType.MISSING_BANK_SETTLEMENT,
        "UNEXPLAINED_DISCREPANCY": DiscrepancyType.UNEXPLAINED_DISCREPANCY,
    }
    return mapping.get(context.reconciliation.deterministic_rule, DiscrepancyType.NONE)


def _fallback_root_cause(context: InvestigationContext) -> RootCause:
    mapping = {
        "EXACT_MATCH": RootCause.EXACT_MATCH,
        "GATEWAY_FEE_DEDUCTION": RootCause.GATEWAY_FEE,
        "SETTLEMENT_TIMING_DIFFERENCE": RootCause.SETTLEMENT_TIMING,
        "PARTIAL_PAYMENT": RootCause.PARTIAL_PAYMENT,
        "DUPLICATE_GATEWAY_TRANSACTION": RootCause.DUPLICATE_TRANSACTION,
        "MISSING_BANK_SETTLEMENT": RootCause.MISSING_BANK_SETTLEMENT,
        "UNEXPLAINED_DISCREPANCY": RootCause.UNEXPLAINED_DISCREPANCY,
    }
    return mapping.get(context.reconciliation.deterministic_rule, RootCause.UNEXPLAINED_DISCREPANCY)


def _fallback_action(discrepancy: DiscrepancyType) -> RecommendedAction:
    return {
        DiscrepancyType.GATEWAY_FEE: RecommendedAction.REVIEW_SOURCE_RECORDS,
        DiscrepancyType.SETTLEMENT_TIMING: RecommendedAction.VERIFY_SETTLEMENT,
        DiscrepancyType.PARTIAL_PAYMENT: RecommendedAction.VERIFY_PAYMENT,
        DiscrepancyType.DUPLICATE_TRANSACTION: RecommendedAction.INVESTIGATE_DUPLICATE,
        DiscrepancyType.MISSING_BANK_SETTLEMENT: RecommendedAction.VERIFY_SETTLEMENT,
        DiscrepancyType.UNEXPLAINED_DISCREPANCY: RecommendedAction.ESCALATE,
        DiscrepancyType.NONE: RecommendedAction.NO_ACTION,
    }[discrepancy]


def _fallback(context: InvestigationContext, flags: tuple[str, ...]) -> InvestigationResult:
    discrepancy = _fallback_discrepancy(context)
    root_cause = _fallback_root_cause(context)
    requires_review = context.reconciliation.deterministic_status in {"NEEDS_REVIEW", "UNRESOLVED"} or bool(flags) or not context.reconciliation.evidence_consistent
    evidence_ids = context.reconciliation.evidence_ids
    return InvestigationResult(
        case_id=context.case_id,
        conclusion=context.reconciliation.deterministic_reason,
        discrepancy_type=discrepancy,
        root_cause=root_cause,
        confidence=1.0 if context.reconciliation.evidence_consistent else 0.5,
        evidence_ids=evidence_ids,
        evidence_summary=f"Deterministic reconciliation evidence: {', '.join(evidence_ids)}.",
        recommended_action=_fallback_action(discrepancy),
        requires_human_review=requires_review,
        ai_generated=False,
        guardrail_flags=tuple(dict.fromkeys(("DETERMINISTIC_FALLBACK", *flags))),
    )


def _parse_provider_json(raw: str) -> Any:
    content = raw.strip()
    if content.startswith("```") and content.endswith("```"):
        lines = content.splitlines()
        if len(lines) < 3:
            raise ValueError("provider returned an empty code fence")
        fence = lines[0].strip().lower()
        if fence not in {"```", "```json"}:
            raise ValueError("provider returned an unsupported code fence")
        content = "\n".join(lines[1:-1]).strip()

    try:
        return json.loads(content)
    except json.JSONDecodeError:
        decoder = json.JSONDecoder()
        candidates: list[Any] = []
        position = 0
        while position < len(content):
            start = content.find("{", position)
            if start < 0:
                break
            try:
                candidate, end = decoder.raw_decode(content, start)
            except json.JSONDecodeError:
                position = start + 1
                continue
            if not isinstance(candidate, dict):
                raise ValueError("provider JSON object was not an object")
            candidates.append(candidate)
            if len(candidates) > 1:
                raise ValueError("provider response contained multiple JSON objects")
            position = end
        if len(candidates) != 1:
            raise ValueError("provider response did not contain one JSON object")
        return candidates[0]


def _validate_provider_result(raw: Any, context: InvestigationContext, confidence_threshold: float) -> InvestigationResult:
    if isinstance(raw, str):
        raw = _parse_provider_json(raw)
    result = InvestigationResult.model_validate(raw)
    allowed_ids = set(context.reconciliation.evidence_ids)
    if result.case_id != context.case_id:
        raise ValueError("provider case ID does not match requested case")
    if not set(result.evidence_ids).issubset(allowed_ids):
        raise ValueError("provider returned an unknown evidence ID")
    flags = set(result.guardrail_flags)
    if not context.reconciliation.evidence_consistent:
        flags.add("CONFLICTING_EVIDENCE")
    requires_review = result.requires_human_review
    requires_review = requires_review or result.confidence < confidence_threshold or bool(flags)
    requires_review = requires_review or context.reconciliation.deterministic_status in {"NEEDS_REVIEW", "UNRESOLVED"}
    return result.model_copy(update={"requires_human_review": requires_review, "ai_generated": True, "guardrail_flags": tuple(sorted(flags))})


def investigate_exception(
    case_id: str,
    context: InvestigationContext,
    provider: InvestigationProvider | None = None,
    confidence_threshold: float = CONFIDENCE_THRESHOLD,
) -> InvestigationResult:
    """Investigate one deterministic exception without changing financial truth."""
    if case_id != context.case_id:
        raise ValueError("requested case ID does not match investigation context")
    if not 0 <= confidence_threshold <= 1:
        raise ValueError("confidence threshold must be between 0 and 1")
    provider = provider if provider is not None else configured_provider()
    if provider is None:
        return _fallback(context, ("AI_PROVIDER_UNAVAILABLE",))
    try:
        return _validate_provider_result(provider.investigate(context), context, confidence_threshold)
    except (ProviderError, ValueError, TypeError, json.JSONDecodeError, ValidationError) as error:
        return _fallback(context, ("AI_OUTPUT_REJECTED", type(error).__name__))