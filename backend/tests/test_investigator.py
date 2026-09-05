from datetime import date, timedelta
from decimal import Decimal
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

from app.agents.investigator import build_context, investigate_exception
from app.agents.models import DiscrepancyType, InvestigationResult, RootCause
from app.agents.provider import OpenRouterProvider
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
        "root_cause": "GATEWAY_FEE",
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


def test_json_inside_markdown_code_fence_is_validated() -> None:
    fenced = f"```json\n{json.dumps(valid_payload())}\n```"
    result = investigate_exception("TXN-TEST", investigation_context(), MockProvider(fenced))
    assert result.ai_generated is True
    assert result.evidence_ids == ("TXN-TEST", "GW-TEST", "BNK-TEST")


@pytest.mark.parametrize("payload", [
    f"  \n{json.dumps(valid_payload())}\n  ",
    f"Investigation result:\n{json.dumps(valid_payload())}\nEnd.",
])
def test_whitespace_and_one_surrounding_json_object_are_validated(payload: str) -> None:
    result = investigate_exception("TXN-TEST", investigation_context(), MockProvider(payload))
    assert result.ai_generated is True


def test_structured_object_content_is_validated() -> None:
    result = investigate_exception("TXN-TEST", investigation_context(), MockProvider(valid_payload()))
    assert result.ai_generated is True


def test_multiple_json_objects_are_rejected() -> None:
    payload = f"{json.dumps(valid_payload())}\n{json.dumps(valid_payload())}"
    result = investigate_exception("TXN-TEST", investigation_context(), MockProvider(payload))
    assert result.ai_generated is False
    assert "AI_OUTPUT_INVALID" in result.guardrail_flags


def test_missing_api_key_uses_deterministic_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    result = investigate_exception("TXN-TEST", investigation_context())
    assert result.ai_generated is False
    assert "AI_PROVIDER_UNAVAILABLE" in result.guardrail_flags
    assert result.discrepancy_type == DiscrepancyType.GATEWAY_FEE


def test_openrouter_valid_response_is_used_without_exposing_key(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, object]] = []

    class FakeCompletions:
        def create(self, **kwargs: object) -> object:
            calls.append(kwargs)
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(valid_payload())))])

    class FakeOpenAI:
        def __init__(self, **kwargs: object) -> None:
            assert kwargs["api_key"] == "secret"
            assert kwargs["base_url"] == "https://openrouter.ai/api/v1"
            self.chat = SimpleNamespace(completions=FakeCompletions())

    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(OpenAI=FakeOpenAI))
    result = investigate_exception("TXN-TEST", investigation_context(), OpenRouterProvider("secret", "test/model"))

    assert result.ai_generated is True
    assert result.evidence_ids == ("TXN-TEST", "GW-TEST", "BNK-TEST")
    assert calls[0]["model"] == "test/model"
    assert "secret" not in json.dumps(calls[0])


def test_openrouter_failure_uses_deterministic_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    class FailingOpenAI:
        def __init__(self, **kwargs: object) -> None:
            self.chat = SimpleNamespace(completions=SimpleNamespace(create=lambda **_: (_ for _ in ()).throw(RuntimeError("offline"))))

    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(OpenAI=FailingOpenAI))
    result = investigate_exception("TXN-TEST", investigation_context(), OpenRouterProvider("secret", "test/model"))

    assert result.ai_generated is False
    assert "AI_PROVIDER_UNAVAILABLE" in result.guardrail_flags


def test_openrouter_malformed_response_uses_deterministic_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    class MalformedOpenAI:
        def __init__(self, **kwargs: object) -> None:
            response = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="not-json"))])
            self.chat = SimpleNamespace(completions=SimpleNamespace(create=lambda **_: response))

    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(OpenAI=MalformedOpenAI))
    result = investigate_exception("TXN-TEST", investigation_context(), OpenRouterProvider("secret", "test/model"))

    assert result.ai_generated is False
    assert "AI_OUTPUT_INVALID" in result.guardrail_flags


@pytest.mark.parametrize("payload", [
    "not-json",
    {"case_id": "TXN-TEST", "confidence": 2},
    {**valid_payload(), "recommended_action": "APPROVE_REFUND"},
])
def test_malformed_or_invalid_provider_output_falls_back(payload: object) -> None:
    result = investigate_exception("TXN-TEST", investigation_context(), MockProvider(payload))
    assert result.ai_generated is False
    assert "AI_OUTPUT_INVALID" in result.guardrail_flags


def test_unknown_evidence_and_mismatched_case_fall_back() -> None:
    payload = valid_payload()
    payload["evidence_ids"] = ["NOT-SUPPLIED"]
    result = investigate_exception("TXN-TEST", investigation_context(), MockProvider(payload))
    assert result.ai_generated is False
    assert "AI_OUTPUT_INVALID" in result.guardrail_flags

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


def test_review_status_cannot_be_cleared_by_provider() -> None:
    invoice, gateways, banks, reconciliation = case()
    review_result = ReconciliationResult(
        reconciliation.transaction_id, ReconciliationStatus.NEEDS_REVIEW, reconciliation.invoice_amount,
        reconciliation.gateway_amount, reconciliation.gateway_fee, reconciliation.expected_settlement,
        reconciliation.actual_settlement, reconciliation.variance, reconciliation.rule_applied,
        reconciliation.evidence_ids, "LOW", True, reconciliation.explanation,
    )
    context = build_context(invoice, gateways, banks, review_result)
    result = investigate_exception("TXN-TEST", context, MockProvider(valid_payload()))
    assert result.requires_human_review is True


def test_fallback_is_deterministic_and_does_not_fabricate_ids(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    first = investigate_exception("TXN-TEST", investigation_context(), provider=None)
    second = investigate_exception("TXN-TEST", investigation_context(), provider=None)
    assert first == second
    assert set(first.evidence_ids) == {"TXN-TEST", "GW-TEST", "BNK-TEST"}
    assert "NOT-SUPPLIED" not in first.evidence_ids


def test_agents_do_not_reference_restricted_evaluation_files() -> None:
    source = "\n".join(path.read_text(encoding="utf-8") for path in Path(__file__).parents[1].glob("app/agents/*.py"))
    assert "ground_truth.csv" not in source
    assert "results.json" not in source


def test_frontend_does_not_contain_provider_credentials_or_configuration() -> None:
    frontend_source = "\n".join(path.read_text(encoding="utf-8") for path in Path(__file__).parents[2].glob("frontend/src/**/*" ) if path.is_file())
    assert "OPENROUTER_API_KEY" not in frontend_source
    assert "OPENAI_API_KEY" not in frontend_source


def test_valid_root_cause_is_accepted() -> None:
    payload = valid_payload()
    payload["root_cause"] = "SETTLEMENT_TIMING"
    result = investigate_exception("TXN-TEST", investigation_context(), MockProvider(payload))
    assert result.root_cause == RootCause.SETTLEMENT_TIMING


def test_invalid_root_cause_triggers_fallback() -> None:
    payload = valid_payload()
    payload["root_cause"] = "INVALID_ROOT_CAUSE"
    result = investigate_exception("TXN-TEST", investigation_context(), MockProvider(payload))
    assert result.ai_generated is False
    assert "AI_OUTPUT_INVALID" in result.guardrail_flags


def test_fallback_assigns_root_cause_from_deterministic_rule(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    result = investigate_exception("TXN-TEST", investigation_context(), provider=None)
    assert result.root_cause == RootCause.GATEWAY_FEE


def test_tools_return_expected_evidence() -> None:
    from app.agents.investigator_tools import get_case_evidence, get_related_transactions
    context = investigation_context()
    evidence = get_case_evidence(context)
    assert evidence["invoice"]["invoice_id"] == "TXN-TEST"
    assert len(evidence["gateways"]) == 1
    related = get_related_transactions(context)
    assert related["gateway_transaction_ids"] == ["GW-TEST"]
    assert related["bank_settlement_ids"] == ["BNK-TEST"]