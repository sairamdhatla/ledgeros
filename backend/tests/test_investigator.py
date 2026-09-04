from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from app.agents.investigator import build_context, investigate_exception
from app.agents.models import DiscrepancyType, InvestigationResult
from app.reconciliation.models import BankSettlement, GatewayTransaction, Invoice, ReconciliationResult, ReconciliationStatus


def case() -> tuple[Invoice, list[GatewayTransaction], list[BankSettlement], ReconciliationResult]:
    invoice = Invoice("TXN-TEST", date(2025, 1, 1), Decimal("50000"), "INR")
    gateway = GatewayTransaction("TXN-TEST", "GW-TEST", invoice.invoice_date, Decimal("50000"), Decimal("750"), "INR")
    bank = BankSettlement("TXN-TEST", "BNK-TEST", invoice.invoice_date + timedelta(days=1), Decimal("49250"), "INR")
    reconciliation = ReconciliationResult(
        "TXN-TEST", ReconciliationStatus.AUTO_RESOLVED, Decimal("50000"), Decimal("50000"), Decimal("750"), Decimal("49250"), Decimal("49250"), Decimal("0"), "GATEWAY_FEE_DEDUCTION", ("TXN-TEST", "GW-TEST", "BNK-TEST"), "HIGH", False, "Fee explains settlement.",
    )
    return invoice, [gateway], [bank], reconciliation


class MockProvider:
    def __init__(self, payload: object) -> None:
        self.payload = payload

    def investigate(self, context: object) -> object:
        return self.payload


def valid_payload() -> dict[str, object]:
    return {
        "case_id": "TXN-TEST",
        "conclusion": "The recorded gateway fee explains the settlement amount.",
        "discrepancy_type": "GATEWAY_FEE",
        "confidence": 0.95,
        "evidence_ids": ["TXN-TEST", "GW-TEST", "BNK-TEST"],
        "evidence_summary": "Invoice, gateway, and bank records support the fee explanation.",
        "recommended_action": "REVIEW_SOURCE_RECORDS",
        "requires_human_review": False,
        "ai_generated": True,
        "guardrail_flags": [],
    }


def investigation_context():
    return build_context(*case())


def test_valid_investigation_result_is_structured() -> None:
    result = investigate_exception("TXN-TEST", investigation_context(), MockProvider(valid_payload()))
    assert isinstance(result, InvestigationResult)
    assert result.ai_generated is True
    assert result.discrepancy_type == DiscrepancyType.GATEWAY_FEE


def test_missing_api_key_uses_deterministic_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    result = investigate_exception("TXN-TEST", investigation_context())
    assert result.ai_generated is False
    assert "AI_PROVIDER_UNAVAILABLE" in result.guardrail_flags
    assert result.discrepancy_type == DiscrepancyType.GATEWAY_FEE


@pytest.mark.parametrize("payload", ["not-json", {"case_id": "TXN-TEST", "confidence": 2}])
def test_malformed_or_invalid_provider_output_falls_back(payload: object) -> None:
    result = investigate_exception("TXN-TEST", investigation_context(), MockProvider(payload))
    assert result.ai_generated is False
    assert "AI_OUTPUT_REJECTED" in result.guardrail_flags


def test_unknown_evidence_and_mismatched_case_fall_back() -> None:
    payload = valid_payload()
    payload["evidence_ids"] = ["NOT-SUPPLIED"]
    result = investigate_exception("TXN-TEST", investigation_context(), MockProvider(payload))
    assert result.ai_generated is False
    assert "AI_OUTPUT_REJECTED" in result.guardrail_flags

    with pytest.raises(ValueError):
        investigate_exception("TXN-OTHER", investigation_context())


def test_low_confidence_and_conflicting_evidence_force_review() -> None:
    payload = valid_payload()
    payload["confidence"] = 0.2
    low = investigate_exception("TXN-TEST", investigation_context(), MockProvider(payload))
    assert low.requires_human_review is True

    invoice, gateways, banks, reconciliation = case()
    conflicting = ReconciliationResult(
        reconciliation.transaction_id, ReconciliationStatus.UNRESOLVED, reconciliation.invoice_amount,
        reconciliation.gateway_amount, reconciliation.gateway_fee, reconciliation.expected_settlement,
        reconciliation.actual_settlement, reconciliation.variance, "UNEXPLAINED_DISCREPANCY",
        reconciliation.evidence_ids, "LOW", True, "Evidence is insufficient.",
    )
    conflict_context = build_context(invoice, gateways, banks, conflicting)
    conflict = investigate_exception("TXN-TEST", conflict_context, MockProvider(valid_payload()))
    assert conflict.requires_human_review is True
    assert "CONFLICTING_EVIDENCE" in conflict.guardrail_flags


def test_fallback_is_deterministic_and_does_not_fabricate_ids() -> None:
    first = investigate_exception("TXN-TEST", investigation_context(), provider=None)
    second = investigate_exception("TXN-TEST", investigation_context(), provider=None)
    assert first == second
    assert set(first.evidence_ids) == {"TXN-TEST", "GW-TEST", "BNK-TEST"}
    assert "NOT-SUPPLIED" not in first.evidence_ids


def test_agents_do_not_reference_restricted_evaluation_files() -> None:
    source = "\n".join(path.read_text(encoding="utf-8") for path in Path(__file__).parents[1].glob("app/agents/*.py"))
    assert "ground_truth.csv" not in source
    assert "results.json" not in source