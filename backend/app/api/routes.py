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
from app.services.razorpay import (
    RazorpayError,
    configured_razorpay_client,
    load_razorpay_config,
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


@router.get("/api/razorpay/status")
def razorpay_status() -> dict[str, Any]:
    config = load_razorpay_config()
    return {
        "configured": config is not None,
        "masked_key_id": config.masked_key_id() if config else "",
        "read_only": True,
    }


@router.get("/api/razorpay/payments")
def razorpay_payments(
    count: int = Query(default=10, ge=1, le=100),
    skip: int = Query(default=0, ge=0),
) -> list[dict[str, Any]]:
    client = configured_razorpay_client()
    if client is None:
        raise HTTPException(
            status_code=503,
            detail="Razorpay API credentials not configured. Please set RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET in backend/.env",
        )
    try:
        payments = client.list_payments(count=count, skip=skip)
        return [payment.model_dump(mode="json") for payment in payments]
    except RazorpayError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error


@router.get("/api/razorpay/settlements")
def razorpay_settlements(
    count: int = Query(default=10, ge=1, le=100),
    skip: int = Query(default=0, ge=0),
) -> list[dict[str, Any]]:
    client = configured_razorpay_client()
    if client is None:
        raise HTTPException(
            status_code=503,
            detail="Razorpay API credentials not configured. Please set RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET in backend/.env",
        )
    try:
        settlements = client.list_settlements(count=count, skip=skip)
        return [settlement.model_dump(mode="json") for settlement in settlements]
    except RazorpayError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error


@router.get("/api/razorpay/recon")
def razorpay_recon(
    year: int = Query(ge=2020, le=2030),
    month: int = Query(ge=1, le=12),
    day: int | None = Query(default=None, ge=1, le=31),
    count: int = Query(default=50, ge=1, le=100),
    skip: int = Query(default=0, ge=0),
) -> list[dict[str, Any]]:
    client = configured_razorpay_client()
    if client is None:
        raise HTTPException(
            status_code=503,
            detail="Razorpay API credentials not configured. Please set RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET in backend/.env",
        )
    try:
        recon_items = client.get_settlement_recon(year=year, month=month, day=day, count=count, skip=skip)
        return [item.model_dump(mode="json") for item in recon_items]
    except RazorpayError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error