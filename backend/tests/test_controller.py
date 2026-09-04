from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.agents.controller import ControllerRunResult, load_cases, run_controller
from app.agents.models import InvestigationContext
from app.agents.provider import InvestigationProvider
from app.main import app


class ValidProvider:
    def investigate(self, context: InvestigationContext) -> dict[str, Any]:
        return {
            "case_id": context.case_id,
            "conclusion": "The deterministic exception requires evidence review.",
            "discrepancy_type": "UNEXPLAINED_DISCREPANCY",
            "confidence": 0.9,
            "evidence_ids": list(context.reconciliation.evidence_ids),
            "evidence_summary": "The supplied case evidence was reviewed.",
            "recommended_action": "ESCALATE",
            "requires_human_review": True,
            "ai_generated": True,
            "guardrail_flags": [],
        }


class InvalidProvider:
    def investigate(self, context: InvestigationContext) -> dict[str, Any]:
        return {
            "case_id": context.case_id,
            "conclusion": "Invalid result",
            "discrepancy_type": "UNEXPLAINED_DISCREPANCY",
            "confidence": 0.9,
            "evidence_ids": ["NOT-SUPPLIED"],
            "evidence_summary": "Invalid evidence.",
            "recommended_action": "ESCALATE",
            "requires_human_review": False,
            "ai_generated": True,
            "guardrail_flags": [],
        }


def test_controller_reports_complete_500_record_batch() -> None:
    report = run_controller(provider=ValidProvider(), max_ai_investigations=284)

    assert report.total_records_processed == 500
    assert report.matched_count == 72
    assert report.auto_resolved_count == 144
    assert report.needs_review_count == 213
    assert report.unresolved_count == 71
    assert report.total_resolved_count == 216
    assert report.match_rate == 72 / 500
    assert report.auto_resolution_rate == 144 / 500
    assert report.resolved_rate == 216 / 500
    assert report.ai_investigations_attempted == 284
    assert report.ai_investigations_successfully_completed == 284
    assert report.ai_fallbacks == 0
    assert len(report.unresolved_exceptions) == 71
    assert len(report.human_review_cases) == 284
    assert all(case.investigation is not None for case in report.audit_cases)


def test_provider_unavailable_falls_back_for_all_review_cases(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    report = run_controller(provider=None, max_ai_investigations=284)

    assert report.ai_investigations_attempted == 284
    assert report.ai_investigations_successfully_completed == 0
    assert report.ai_fallbacks == 284
    assert all(case.investigation is not None and not case.investigation.ai_generated for case in report.human_review_cases)


def test_invalid_ai_output_preserves_deterministic_status_and_escalates() -> None:
    report = run_controller(provider=InvalidProvider(), max_ai_investigations=284)
    original = {case.result.transaction_id: case.result for case in load_cases()}

    assert report.ai_investigations_successfully_completed == 0
    assert report.ai_fallbacks == 284
    for case in report.human_review_cases:
        assert case.deterministic_status == original[case.case_id].status
        assert case.deterministic_reason == original[case.case_id].explanation
        assert case.investigation is not None
        assert case.investigation.requires_human_review is True
        assert set(case.investigation.evidence_ids) == set(case.evidence_ids)


def test_controller_endpoint_returns_batch_report(monkeypatch: pytest.MonkeyPatch) -> None:
    expected = run_controller(provider=ValidProvider(), max_ai_investigations=284)
    monkeypatch.setattr("app.api.routes.run_controller", lambda: expected)

    response = TestClient(app).post("/api/agent/run")

    assert response.status_code == 200
    body = response.json()
    assert body["total_records_processed"] == 500
    assert body["matched_count"] == 72
    assert body["auto_resolved_count"] == 144
    assert body["needs_review_count"] == 213
    assert body["unresolved_count"] == 71
    assert body["total_resolved_count"] == 216
    assert body["ai_investigations_attempted"] == 284


def test_controller_default_limit_skips_remaining_cases(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CONTROLLER_MAX_AI_INVESTIGATIONS", raising=False)
    report = run_controller(provider=ValidProvider())

    assert report.total_exception_count == 284
    assert report.ai_investigations_attempted == 5
    assert report.ai_investigations_successfully_completed == 5
    assert report.ai_fallbacks == 0
    assert report.ai_investigations_skipped == 279
    assert len(report.skipped_ai_cases) == 279
    assert all(case.investigation is None for case in report.skipped_ai_cases)
    assert len(report.human_review_cases) == 284


def test_controller_limit_can_be_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CONTROLLER_MAX_AI_INVESTIGATIONS", "2")
    report = run_controller(provider=ValidProvider())

    assert report.ai_investigations_attempted == 2
    assert report.ai_investigations_skipped == 282
