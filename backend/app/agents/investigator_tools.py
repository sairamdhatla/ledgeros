"""Controlled read-only investigator tools."""

from __future__ import annotations

from typing import Any

from app.agents.models import InvestigationContext


def get_case_evidence(context: InvestigationContext) -> dict[str, Any]:
    return {
        "invoice": context.invoice.model_dump(mode="json"),
        "gateways": [gateway.model_dump(mode="json") for gateway in context.gateway],
        "banks": [bank.model_dump(mode="json") for bank in context.bank],
        "reconciliation": context.reconciliation.model_dump(mode="json"),
    }


def get_payment(payment_id: str, client: Any) -> dict[str, Any] | None:
    if client is None:
        return None
    try:
        payment = client.get_payment(payment_id)
        return payment.model_dump(mode="json")
    except Exception:
        return None


def get_settlement_recon(case_id: str, client: Any, context: InvestigationContext) -> list[dict[str, Any]] | None:
    if client is None or not context.bank:
        return None
    try:
        recon_items = client.get_settlement_recon(
            year=context.bank[0].settlement_date.year,
            month=context.bank[0].settlement_date.month,
        )
        related = []
        case_gateway_ids = {g.transaction_id for g in context.gateway}
        for item in recon_items:
            if item.entity_id in case_gateway_ids or item.order_receipt == case_id:
                related.append(item.model_dump(mode="json"))
        return related
    except Exception:
        return None


def get_related_transactions(context: InvestigationContext) -> dict[str, Any]:
    return {
        "gateway_transaction_ids": [gateway.transaction_id for gateway in context.gateway],
        "bank_settlement_ids": [bank.settlement_id for bank in context.bank],
        "evidence_ids": list(context.reconciliation.evidence_ids),
    }
