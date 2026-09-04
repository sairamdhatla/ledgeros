"""Thin API routes over the deterministic reconciliation and investigator services."""

from __future__ import annotations

from time import perf_counter
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.agents.controller import CaseBundle, load_cases, run_controller
from app.agents.investigator import build_context, investigate_exception
from app.agents.models import InvestigationResult
from app.reconciliation.models import (
    BankSettlement,
    GatewayTransaction,
    Invoice,
    ReconciliationResult,
    ReconciliationStatus,
)
router = APIRouter()


_load_cases = load_cases


def _decimal(value: Any) -> str | None:
    return str(value) if value is not None else None


def _source_invoice(invoice: Invoice) -> dict[str, Any]:
    return {
        "invoice_id": invoice.transaction_id,
        "amount_inr": _decimal(invoice.amount_inr),
        "invoice_date": invoice.invoice_date.isoformat(),
        "currency": invoice.currency,
    }


def _source_gateway(gateway: GatewayTransaction) -> dict[str, Any]:
    return {
        "transaction_id": gateway.gateway_transaction_id,
        "invoice_reference_id": gateway.transaction_id,
        "gross_amount_inr": _decimal(gateway.amount_inr),
        "fee_inr": _decimal(gateway.fee_inr),
        "net_amount_inr": _decimal(gateway.amount_inr - gateway.fee_inr),
        "transaction_date": gateway.transaction_date.isoformat(),
        "currency": gateway.currency,
    }


def _source_bank(bank: BankSettlement) -> dict[str, Any]:
    return {
        "settlement_id": bank.bank_settlement_id,
        "reference_id": bank.transaction_id,
        "amount_inr": _decimal(bank.amount_inr),
        "settlement_date": bank.settlement_date.isoformat(),
        "currency": bank.currency,
    }


def _discrepancy_type(result: ReconciliationResult) -> str:
    return {
        "EXACT_MATCH": "NONE",
        "GATEWAY_FEE_DEDUCTION": "GATEWAY_FEE",
        "SETTLEMENT_TIMING_DIFFERENCE": "SETTLEMENT_TIMING",
        "PARTIAL_PAYMENT": "PARTIAL_PAYMENT",
        "DUPLICATE_GATEWAY_TRANSACTION": "DUPLICATE_TRANSACTION",
        "MISSING_BANK_SETTLEMENT": "MISSING_BANK_SETTLEMENT",
        "UNEXPLAINED_DISCREPANCY": "UNEXPLAINED_DISCREPANCY",
    }.get(result.rule_applied, "UNEXPLAINED_DISCREPANCY")


def _result_payload(result: ReconciliationResult) -> dict[str, Any]:
    return {
        "case_id": result.transaction_id,
        "status": result.status.value,
        "invoice_amount_inr": _decimal(result.invoice_amount),
        "gateway_amount_inr": _decimal(result.gateway_amount),
        "gateway_fee_inr": _decimal(result.gateway_fee),
        "expected_settlement_inr": _decimal(result.expected_settlement),
        "actual_settlement_inr": _decimal(result.actual_settlement),
        "variance_inr": _decimal(result.variance),
        "discrepancy_type": _discrepancy_type(result),
        "reason": result.explanation,
        "rule_applied": result.rule_applied,
        "confidence": result.confidence,
        "requires_human_review": result.requires_review,
        "evidence_ids": list(result.evidence_ids),
    }


def _list_item(bundle: CaseBundle) -> dict[str, Any]:
    records = bundle.records
    return {
        "case_id": bundle.result.transaction_id,
        "invoice_id": records.invoice.transaction_id,
        "gateway_transaction_id": records.gateways[0].gateway_transaction_id if records.gateways else None,
        "bank_settlement_id": records.banks[0].bank_settlement_id if records.banks else None,
        "status": bundle.result.status.value,
        "discrepancy_type": _discrepancy_type(bundle.result),
        "reason": bundle.result.explanation,
        "confidence": bundle.result.confidence,
        "requires_human_review": bundle.result.requires_review,
        "evidence_ids": list(bundle.result.evidence_ids),
    }


def _detail(bundle: CaseBundle) -> dict[str, Any]:
    return {
        "case_id": bundle.result.transaction_id,
        "invoice": _source_invoice(bundle.records.invoice),
        "gateway": [_source_gateway(record) for record in bundle.records.gateways],
        "bank": [_source_bank(record) for record in bundle.records.banks],
        "reconciliation": _result_payload(bundle.result),
        "evidence": {evidence_id: "source record supplied to reconciliation" for evidence_id in bundle.result.evidence_ids},
        "deterministic_explanation": bundle.result.explanation,
        "requires_human_review": bundle.result.requires_review,
    }


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/api/summary")
def summary() -> dict[str, Any]:
    started = perf_counter()
    results = [bundle.result for bundle in _load_cases()]
    counts = {status.value.lower(): sum(result.status == status for result in results) for status in ReconciliationStatus}
    total = len(results)
    return {
        "total_cases": total,
        "matched": counts["matched"],
        "auto_resolved": counts["auto_resolved"],
        "needs_review": counts["needs_review"],
        "unresolved": counts["unresolved"],
        "match_rate": counts["matched"] / total if total else 0.0,
        "auto_resolution_rate": counts["auto_resolved"] / total if total else 0.0,
        "processing_time_ms": round((perf_counter() - started) * 1000, 3),
    }


@router.get("/api/cases")
def cases(
    status: ReconciliationStatus | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> list[dict[str, Any]]:
    filtered = [bundle for bundle in _load_cases() if status is None or bundle.result.status == status]
    return [_list_item(bundle) for bundle in filtered[offset : offset + limit]]


@router.get("/api/cases/{case_id}")
def case_detail(case_id: str) -> dict[str, Any]:
    bundle = next((bundle for bundle in _load_cases() if bundle.result.transaction_id == case_id), None)
    if bundle is None:
        raise HTTPException(status_code=404, detail=f"Case {case_id} was not found")
    return _detail(bundle)


@router.post("/api/cases/{case_id}/investigate")
def investigate(case_id: str) -> dict[str, Any]:
    bundle = next((bundle for bundle in _load_cases() if bundle.result.transaction_id == case_id), None)
    if bundle is None:
        raise HTTPException(status_code=404, detail=f"Case {case_id} was not found")
    context = build_context(bundle.records.invoice, bundle.records.gateways, bundle.records.banks, bundle.result)
    investigation: InvestigationResult = investigate_exception(case_id, context)
    return {"case_id": case_id, "investigation": investigation.model_dump(mode="json")}


@router.post("/api/agent/run")
def run_agent() -> dict[str, Any]:
    return run_controller().model_dump(mode="json")