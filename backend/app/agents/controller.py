"""Batch Finance Controller orchestration over deterministic reconciliation and investigation."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
from time import perf_counter

from pydantic import BaseModel, ConfigDict

from app.reconciliation.engine import reconcile_records
from app.reconciliation.matcher import TransactionRecords, match_records
from app.reconciliation.models import (
    BankSettlement,
    GatewayTransaction,
    Invoice,
    ReconciliationResult,
    ReconciliationStatus,
)
from app.reconciliation.normalizer import load_bank_settlements, load_gateway_transactions, load_invoices

from .investigator import build_context, investigate_exception
from .models import InvestigationResult
from .provider import InvestigationProvider

GENERATED_DATA = Path(__file__).resolve().parents[3] / "data" / "generated"
REVIEW_STATUSES = {ReconciliationStatus.NEEDS_REVIEW, ReconciliationStatus.UNRESOLVED}
DEFAULT_MAX_AI_INVESTIGATIONS = 10


@dataclass(frozen=True)
class CaseBundle:
    records: TransactionRecords
    result: ReconciliationResult


class ControllerCaseReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str
    deterministic_status: ReconciliationStatus
    deterministic_reason: str
    deterministic_rule: str
    evidence_ids: tuple[str, ...]
    requires_human_review: bool
    investigation: InvestigationResult | None = None


class ControllerRunResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    total_records_processed: int
    matched_count: int
    auto_resolved_count: int
    needs_review_count: int
    unresolved_count: int
    match_rate: float
    auto_resolution_rate: float
    total_resolved_count: int
    resolved_rate: float
    processing_time_ms: float
    total_exception_count: int
    ai_investigations_attempted: int
    ai_investigations_successfully_completed: int
    ai_fallbacks: int
    ai_investigations_skipped: int
    unresolved_exceptions: tuple[ControllerCaseReport, ...]
    human_review_cases: tuple[ControllerCaseReport, ...]
    skipped_ai_cases: tuple[ControllerCaseReport, ...]
    audit_cases: tuple[ControllerCaseReport, ...]


def load_cases() -> list[CaseBundle]:
    invoices = load_invoices(GENERATED_DATA / "invoices.csv")
    gateways = load_gateway_transactions(GENERATED_DATA / "gateway_transactions.csv")
    banks = load_bank_settlements(GENERATED_DATA / "bank_settlements.csv")
    records = match_records(invoices, gateways, banks)
    results = reconcile_records(invoices, gateways, banks)
    return [CaseBundle(record, result) for record, result in zip(records, results, strict=True)]


def _case_report(bundle: CaseBundle, investigation: InvestigationResult | None) -> ControllerCaseReport:
    result = bundle.result
    requires_review = result.requires_review or bool(investigation and investigation.requires_human_review)
    return ControllerCaseReport(
        case_id=result.transaction_id,
        deterministic_status=result.status,
        deterministic_reason=result.explanation,
        deterministic_rule=result.rule_applied,
        evidence_ids=result.evidence_ids,
        requires_human_review=requires_review,
        investigation=investigation,
    )


def run_controller(
    provider: InvestigationProvider | None = None,
    bundles: list[CaseBundle] | None = None,
    max_ai_investigations: int | None = None,
) -> ControllerRunResult:
    """Run deterministic reconciliation for the full batch and investigate review cases."""
    started = perf_counter()
    case_bundles = bundles if bundles is not None else load_cases()
    results = [bundle.result for bundle in case_bundles]
    counts = {status: sum(result.status == status for result in results) for status in ReconciliationStatus}
    review_cases: list[ControllerCaseReport] = []
    attempted = 0
    successful = 0
    fallbacks = 0
    skipped_cases: list[ControllerCaseReport] = []
    configured_limit = os.getenv("CONTROLLER_MAX_AI_INVESTIGATIONS")
    if max_ai_investigations is None:
        try:
            max_ai_investigations = int(configured_limit) if configured_limit else DEFAULT_MAX_AI_INVESTIGATIONS
        except ValueError:
            max_ai_investigations = DEFAULT_MAX_AI_INVESTIGATIONS
    if max_ai_investigations < 0:
        raise ValueError("max_ai_investigations must be non-negative")

    for bundle in case_bundles:
        if bundle.result.status not in REVIEW_STATUSES:
            continue
        if attempted >= max_ai_investigations:
            skipped_cases.append(_case_report(bundle, None))
            continue
        attempted += 1
        context = build_context(bundle.records.invoice, bundle.records.gateways, bundle.records.banks, bundle.result)
        investigation = investigate_exception(bundle.result.transaction_id, context, provider=provider)
        successful += int(investigation.ai_generated)
        fallbacks += int(not investigation.ai_generated)
        review_cases.append(_case_report(bundle, investigation))

    all_review_cases = tuple(review_cases + skipped_cases)
    unresolved = tuple(case for case in all_review_cases if case.deterministic_status == ReconciliationStatus.UNRESOLVED)
    total = len(results)
    resolved = counts[ReconciliationStatus.MATCHED] + counts[ReconciliationStatus.AUTO_RESOLVED]
    return ControllerRunResult(
        total_records_processed=total,
        matched_count=counts[ReconciliationStatus.MATCHED],
        auto_resolved_count=counts[ReconciliationStatus.AUTO_RESOLVED],
        needs_review_count=counts[ReconciliationStatus.NEEDS_REVIEW],
        unresolved_count=counts[ReconciliationStatus.UNRESOLVED],
        match_rate=counts[ReconciliationStatus.MATCHED] / total if total else 0.0,
        auto_resolution_rate=counts[ReconciliationStatus.AUTO_RESOLVED] / total if total else 0.0,
        total_resolved_count=resolved,
        resolved_rate=resolved / total if total else 0.0,
        processing_time_ms=round((perf_counter() - started) * 1000, 3),
        total_exception_count=len(all_review_cases),
        ai_investigations_attempted=attempted,
        ai_investigations_successfully_completed=successful,
        ai_fallbacks=fallbacks,
        ai_investigations_skipped=len(skipped_cases),
        unresolved_exceptions=unresolved,
        human_review_cases=all_review_cases,
        skipped_ai_cases=tuple(skipped_cases),
        audit_cases=all_review_cases,
    )
