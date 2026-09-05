from __future__ import annotations

from typing import Any
from unittest.mock import Mock, patch

import pytest
from fastapi.testclient import TestClient

from app.agents.controller import (
    ControllerRunResult,
    load_cases,
    load_cases_by_mode,
    run_controller,
    _infer_invoices_from_gateways,
)
from app.agents.models import InvestigationContext
from app.agents.provider import InvestigationProvider
from app.main import app
from app.reconciliation.models import GatewayTransaction
from app.services.razorpay import RazorpayError
from datetime import date
from decimal import Decimal

from tests.fixtures.razorpay_fixtures import MockRazorpayProvider, sample_recon_items


class ValidProvider:
    def investigate(self, context: InvestigationContext) -> dict[str, Any]:
        return {
            "case_id": context.case_id,
            "conclusion": "The deterministic exception requires evidence review.",
            "discrepancy_type": "UNEXPLAINED_DISCREPANCY",
            "root_cause": "UNEXPLAINED_DISCREPANCY",
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
            "root_cause": "UNEXPLAINED_DISCREPANCY",
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
    # Patch at the routes level since that's where the endpoint is
    monkeypatch.setattr("app.api.routes.run_controller", lambda *args, **kwargs: expected)

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


def test_run_controller_razorpay_mode_mocked_provider() -> None:
    """Test run_controller in razorpay mode with mocked provider (C)."""
    recon_items = sample_recon_items()
    mock_provider = MockRazorpayProvider(recon_items=recon_items)

    with patch("app.agents.controller.configured_razorpay_client") as mock_client:
        mock_client.return_value = mock_provider
        with patch("app.agents.controller.load_razorpay_config") as mock_config:
            mock_config.return_value = Mock(key_id="test", key_secret="test")
            report = run_controller(
                provider=ValidProvider(),
                max_ai_investigations=5,
                mode="razorpay",
                year=2025,
                month=1,
            )

    assert report.total_records_processed == 2  # Two payment records


def test_run_controller_razorpay_mode_normalizes_data() -> None:
    """Test run_controller razorpay mode successfully normalizes provider data (D)."""
    recon_items = sample_recon_items()
    mock_provider = MockRazorpayProvider(recon_items=recon_items)

    with patch("app.agents.controller.configured_razorpay_client") as mock_client:
        mock_client.return_value = mock_provider
        with patch("app.agents.controller.load_razorpay_config") as mock_config:
            mock_config.return_value = Mock(key_id="test", key_secret="test")
            report = run_controller(
                provider=ValidProvider(),
                max_ai_investigations=5,
                mode="razorpay",
                year=2025,
                month=1,
            )

    assert report.total_records_processed == 2
    # Should have MATCHED or AUTO_RESOLVED statuses since amounts reconcile
    assert report.matched_count + report.auto_resolved_count == 2


def test_run_controller_razorpay_missing_credentials() -> None:
    """Test run_controller razorpay mode with missing credentials (E)."""
    with patch("app.agents.controller.load_razorpay_config", return_value=None):
        with pytest.raises(RazorpayError, match="not configured"):
            run_controller(mode="razorpay", year=2025, month=1)


def test_run_controller_razorpay_api_failure() -> None:
    """Test run_controller razorpay mode handles API failure (F)."""
    mock_provider = MockRazorpayProvider(should_fail=True, error=RazorpayError("API error"))

    with patch("app.agents.controller.configured_razorpay_client") as mock_client:
        mock_client.return_value = mock_provider
        with patch("app.agents.controller.load_razorpay_config") as mock_config:
            mock_config.return_value = Mock(key_id="test", key_secret="test")
            with pytest.raises(RazorpayError, match="API error"):
                run_controller(mode="razorpay", year=2025, month=1)


def test_run_controller_razorpay_timeout() -> None:
    """Test run_controller razorpay mode handles timeout (G)."""
    from httpx import TimeoutException
    mock_provider = MockRazorpayProvider(should_fail=True, error=TimeoutException("Request timed out"))

    with patch("app.agents.controller.configured_razorpay_client") as mock_client:
        mock_client.return_value = mock_provider
        with patch("app.agents.controller.load_razorpay_config") as mock_config:
            mock_config.return_value = Mock(key_id="test", key_secret="test")
            with pytest.raises(RazorpayError, match="Razorpay data fetch failed"):
                run_controller(mode="razorpay", year=2025, month=1)


def test_run_controller_razorpay_no_credentials_exposed() -> None:
    """Test run_controller razorpay mode does not expose credentials in output (H)."""
    recon_items = sample_recon_items()
    mock_provider = MockRazorpayProvider(recon_items=recon_items)

    with patch("app.agents.controller.configured_razorpay_client") as mock_client:
        mock_client.return_value = mock_provider
        with patch("app.agents.controller.load_razorpay_config") as mock_config:
            mock_config.return_value = Mock(key_id="rzp_test_1234567890", key_secret="super_secret_xyz")
            report = run_controller(mode="razorpay", year=2025, month=1)

    # Check that secrets don't appear in the report
    report_json = report.model_dump_json()
    assert "super_secret_xyz" not in report_json
    assert "rzp_test_1234567890" not in report_json


def test_load_cases_by_mode_default_synthetic() -> None:
    """Test explicit synthetic mode loads 500 cases."""
    bundles = load_cases_by_mode(mode="synthetic")
    assert len(bundles) == 500


def test_load_cases_by_mode_synthetic_rejects_year_month() -> None:
    """Test synthetic mode rejects year/month parameters."""
    with pytest.raises(ValueError, match="does not accept year/month"):
        load_cases_by_mode(mode="synthetic", year=2025, month=1)


def test_load_cases_by_mode_razorpay_requires_year_month() -> None:
    """Test razorpay mode requires year and month."""
    with pytest.raises(ValueError, match="requires year and month"):
        load_cases_by_mode(mode="razorpay")


def test_load_cases_by_mode_unknown_mode() -> None:
    """Test unknown mode raises error."""
    with pytest.raises(ValueError, match="Unknown mode"):
        load_cases_by_mode(mode="unknown")


def test_infer_invoices_from_gateways() -> None:
    """Test inferring invoices from gateway transactions."""
    gateways = [
        GatewayTransaction(
            transaction_id="INV-001",
            gateway_transaction_id="pay_001",
            transaction_date=date(2025, 1, 15),
            amount_inr=Decimal("1000.00"),
            fee_inr=Decimal("20.00"),
            currency="INR",
        ),
        GatewayTransaction(
            transaction_id="INV-002",
            gateway_transaction_id="pay_002",
            transaction_date=date(2025, 1, 16),
            amount_inr=Decimal("2000.00"),
            fee_inr=Decimal("40.00"),
            currency="INR",
        ),
        GatewayTransaction(
            transaction_id="INV-001",  # Duplicate
            gateway_transaction_id="pay_003",
            transaction_date=date(2025, 1, 17),
            amount_inr=Decimal("500.00"),
            fee_inr=Decimal("10.00"),
            currency="INR",
        ),
    ]
    invoices = _infer_invoices_from_gateways(gateways)
    assert len(invoices) == 2
    assert invoices[0].transaction_id == "INV-001"
    assert invoices[0].amount_inr == Decimal("1000.00")
    assert invoices[1].transaction_id == "INV-002"
    assert invoices[1].amount_inr == Decimal("2000.00")


def test_run_controller_default_synthetic_mode() -> None:
    """Test run_controller defaults to synthetic mode (A)."""
    report = run_controller(provider=ValidProvider(), max_ai_investigations=5)
    assert report.total_records_processed == 500


def test_run_controller_explicit_synthetic_mode() -> None:
    """Test run_controller with explicit synthetic mode (B)."""
    report = run_controller(provider=ValidProvider(), max_ai_investigations=5, mode="synthetic")
    assert report.total_records_processed == 500


def test_run_controller_razorpay_mode_mocked_provider() -> None:
    """Test run_controller in razorpay mode with mocked provider (C)."""
    recon_items = sample_recon_items()
    mock_provider = MockRazorpayProvider(recon_items=recon_items)

    with patch("app.agents.controller.configured_razorpay_client") as mock_client:
        mock_client.return_value = mock_provider
        with patch("app.agents.controller.load_razorpay_config") as mock_config:
            mock_config.return_value = Mock(key_id="test", key_secret="test")
            report = run_controller(
                provider=ValidProvider(),
                max_ai_investigations=5,
                mode="razorpay",
                year=2025,
                month=1,
            )

    assert report.total_records_processed == 2  # Two payment records


def test_run_controller_razorpay_mode_normalizes_data() -> None:
    """Test run_controller razorpay mode successfully normalizes provider data (D)."""
    recon_items = sample_recon_items()
    mock_provider = MockRazorpayProvider(recon_items=recon_items)

    with patch("app.agents.controller.configured_razorpay_client") as mock_client:
        mock_client.return_value = mock_provider
        with patch("app.agents.controller.load_razorpay_config") as mock_config:
            mock_config.return_value = Mock(key_id="test", key_secret="test")
            report = run_controller(
                provider=ValidProvider(),
                max_ai_investigations=5,
                mode="razorpay",
                year=2025,
                month=1,
            )

    assert report.total_records_processed == 2
    # Should have MATCHED or AUTO_RESOLVED statuses since amounts reconcile
    assert report.matched_count + report.auto_resolved_count == 2


def test_run_controller_razorpay_missing_credentials() -> None:
    """Test run_controller razorpay mode with missing credentials (E)."""
    with patch("app.agents.controller.load_razorpay_config", return_value=None):
        with pytest.raises(RazorpayError, match="not configured"):
            run_controller(mode="razorpay", year=2025, month=1)


def test_run_controller_razorpay_api_failure() -> None:
    """Test run_controller razorpay mode handles API failure (F)."""
    mock_provider = MockRazorpayProvider(should_fail=True, error=RazorpayError("API error"))

    with patch("app.agents.controller.configured_razorpay_client") as mock_client:
        mock_client.return_value = mock_provider
        with patch("app.agents.controller.load_razorpay_config") as mock_config:
            mock_config.return_value = Mock(key_id="test", key_secret="test")
            with pytest.raises(RazorpayError, match="API error"):
                run_controller(mode="razorpay", year=2025, month=1)


def test_run_controller_razorpay_timeout() -> None:
    """Test run_controller razorpay mode handles timeout (G)."""
    from httpx import TimeoutException
    mock_provider = MockRazorpayProvider(should_fail=True, error=TimeoutException("Request timed out"))

    with patch("app.agents.controller.configured_razorpay_client") as mock_client:
        mock_client.return_value = mock_provider
        with patch("app.agents.controller.load_razorpay_config") as mock_config:
            mock_config.return_value = Mock(key_id="test", key_secret="test")
            with pytest.raises(RazorpayError, match="Razorpay data fetch failed"):
                run_controller(mode="razorpay", year=2025, month=1)


def test_run_controller_razorpay_no_credentials_exposed() -> None:
    """Test run_controller razorpay mode does not expose credentials in output (H)."""
    recon_items = sample_recon_items()
    mock_provider = MockRazorpayProvider(recon_items=recon_items)

    with patch("app.agents.controller.configured_razorpay_client") as mock_client:
        mock_client.return_value = mock_provider
        with patch("app.agents.controller.load_razorpay_config") as mock_config:
            mock_config.return_value = Mock(key_id="rzp_test_1234567890", key_secret="super_secret_xyz")
            report = run_controller(mode="razorpay", year=2025, month=1)

    # Check that secrets don't appear in the report
    report_json = report.model_dump_json()
    assert "super_secret_xyz" not in report_json
    assert "rzp_test_1234567890" not in report_json


def test_synthetic_benchmark_unchanged() -> None:
    """Test synthetic benchmark remains unchanged (I)."""
    report = run_controller(mode="synthetic")
    assert report.total_records_processed == 500
    assert report.matched_count == 72
    assert report.auto_resolved_count == 144
    assert report.needs_review_count == 213
    assert report.unresolved_count == 71
    assert report.total_resolved_count == 216


def test_razorpay_mode_no_synthetic_fallback() -> None:
    """Test no synthetic fallback occurs when Razorpay mode fails (J)."""
    mock_provider = MockRazorpayProvider(should_fail=True, error=RazorpayError("Network error"))

    with patch("app.agents.controller.configured_razorpay_client") as mock_client:
        mock_client.return_value = mock_provider
        with patch("app.agents.controller.load_razorpay_config") as mock_config:
            mock_config.return_value = Mock(key_id="test", key_secret="test")
            with pytest.raises(RazorpayError, match="Network error"):
                run_controller(mode="razorpay", year=2025, month=1)

    # Verify synthetic data was NOT loaded as fallback
    # If fallback happened, it would return 500 records
    # The exception confirms no fallback
