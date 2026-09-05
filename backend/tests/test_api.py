import os
from pathlib import Path
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient

from app.main import app
from app.agents.provider import configured_provider
from app.services.razorpay import RazorpayError
from app.services.razorpay.models import RazorpayReconItem

from tests.fixtures.razorpay_fixtures import MockRazorpayProvider, sample_recon_items

client = TestClient(app)


def test_startup_loads_backend_env_for_openrouter_without_exposing_key() -> None:
    configured = configured_provider()
    assert os.getenv("OPENROUTER_API_KEY")
    assert os.getenv("OPENROUTER_MODEL") == "google/gemma-4-26b-a4b-it"
    assert configured is not None
    assert configured.model == "google/gemma-4-26b-a4b-it"


def test_health_endpoint() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_summary_endpoint_uses_reconciliation_results() -> None:
    response = client.get("/api/summary")
    body = response.json()
    assert response.status_code == 200
    assert body["total_cases"] == 500
    assert body["matched"] == 72
    assert body["auto_resolved"] == 144
    assert body["needs_review"] == 213
    assert body["unresolved"] == 71
    assert body["match_rate"] == 72 / 500
    assert body["auto_resolution_rate"] == 144 / 500
    assert body["processing_time_ms"] >= 0


def test_cases_endpoint_supports_limit_offset_and_expected_shape() -> None:
    response = client.get("/api/cases?limit=2&offset=1")
    body = response.json()
    assert response.status_code == 200
    assert len(body) == 2
    assert body[0]["case_id"] == "TXN-000002"
    assert {"case_id", "invoice_id", "status", "evidence_ids"}.issubset(body[0])


def test_cases_status_filter() -> None:
    response = client.get("/api/cases", params={"status": "UNRESOLVED", "limit": 500})
    body = response.json()
    assert response.status_code == 200
    assert len(body) == 71
    assert {item["status"] for item in body} == {"UNRESOLVED"}


def test_case_detail_contains_source_records_and_result() -> None:
    response = client.get("/api/cases/TXN-000001")
    body = response.json()
    assert response.status_code == 200
    assert body["case_id"] == "TXN-000001"
    assert body["invoice"]["invoice_id"] == "TXN-000001"
    assert body["gateway"][0]["transaction_id"] == "GW-000001"
    assert body["bank"][0]["settlement_id"] == "BNK-000001"
    assert body["reconciliation"]["status"] == "MATCHED"


def test_missing_case_returns_404() -> None:
    response = client.get("/api/cases/TXN-DOES-NOT-EXIST")
    assert response.status_code == 404
    assert "was not found" in response.json()["detail"]


def test_investigation_endpoint_uses_deterministic_fallback_without_key(monkeypatch) -> None:
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    response = client.post("/api/cases/TXN-000006/investigate")
    body = response.json()
    assert response.status_code == 200
    assert body["case_id"] == "TXN-000006"
    assert body["investigation"]["ai_generated"] is False
    assert body["investigation"]["requires_human_review"] is True
    assert "AI_PROVIDER_UNAVAILABLE" in body["investigation"]["guardrail_flags"]


def test_api_source_does_not_reference_restricted_data_files() -> None:
    source = "\n".join(path.read_text(encoding="utf-8") for path in Path(__file__).parents[1].glob("app/api/*.py"))
    assert "ground_truth.csv" not in source
    assert "results.json" not in source


def test_razorpay_status_endpoint_unconfigured(monkeypatch) -> None:
    monkeypatch.delenv("RAZORPAY_KEY_ID", raising=False)
    monkeypatch.delenv("RAZORPAY_KEY_SECRET", raising=False)
    response = client.get("/api/razorpay/status")
    assert response.status_code == 200
    body = response.json()
    assert body["configured"] is False
    assert body["read_only"] is True


def test_razorpay_status_endpoint_configured(monkeypatch) -> None:
    monkeypatch.setenv("RAZORPAY_KEY_ID", "rzp_test_1234567890")
    monkeypatch.setenv("RAZORPAY_KEY_SECRET", "super_secret_xyz")
    response = client.get("/api/razorpay/status")
    assert response.status_code == 200
    body = response.json()
    assert body["configured"] is True
    assert body["masked_key_id"] == "rzp_test***"
    assert "super_secret_xyz" not in response.text


def test_razorpay_payments_unconfigured_returns_503(monkeypatch) -> None:
    monkeypatch.delenv("RAZORPAY_KEY_ID", raising=False)
    monkeypatch.delenv("RAZORPAY_KEY_SECRET", raising=False)
    response = client.get("/api/razorpay/payments")
    assert response.status_code == 503
    assert "not configured" in response.json()["detail"]


def test_razorpay_settlements_unconfigured_returns_503(monkeypatch) -> None:
    monkeypatch.delenv("RAZORPAY_KEY_ID", raising=False)
    monkeypatch.delenv("RAZORPAY_KEY_SECRET", raising=False)
    response = client.get("/api/razorpay/settlements")
    assert response.status_code == 503
    assert "not configured" in response.json()["detail"]


def test_agent_run_default_synthetic_mode() -> None:
    """Test /api/agent/run defaults to synthetic mode."""
    response = client.post("/api/agent/run")
    assert response.status_code == 200
    body = response.json()
    assert body["total_records_processed"] == 500


def test_agent_run_explicit_synthetic_mode() -> None:
    """Test /api/agent/run with explicit synthetic mode."""
    response = client.post("/api/agent/run?mode=synthetic")
    assert response.status_code == 200
    body = response.json()
    assert body["total_records_processed"] == 500


def test_agent_run_invalid_mode() -> None:
    """Test /api/agent/run with invalid mode returns 400."""
    response = client.post("/api/agent/run?mode=invalid")
    assert response.status_code == 422  # Validation error


def test_agent_run_razorpay_mode_mocked() -> None:
    """Test /api/agent/run in razorpay mode with mocked provider."""
    recon_items = sample_recon_items()
    mock_provider = MockRazorpayProvider(recon_items=recon_items)

    with patch("app.api.routes.configured_razorpay_client") as route_client:
        route_client.return_value = mock_provider
        with patch("app.api.routes.load_razorpay_config") as route_config:
            route_config.return_value = Mock(key_id="test", key_secret="test")
            with patch("app.agents.controller.configured_razorpay_client") as ctrl_client:
                ctrl_client.return_value = mock_provider
                with patch("app.agents.controller.load_razorpay_config") as ctrl_config:
                    ctrl_config.return_value = Mock(key_id="test", key_secret="test")
                    response = client.post("/api/agent/run?mode=razorpay&year=2025&month=1")

    assert response.status_code == 200
    body = response.json()
    assert body["total_records_processed"] == 2


def test_agent_run_razorpay_mode_missing_credentials() -> None:
    """Test /api/agent/run razorpay mode returns 503 when credentials missing."""
    with patch("app.api.routes.load_razorpay_config", return_value=None):
        response = client.post("/api/agent/run?mode=razorpay&year=2025&month=1")
    assert response.status_code == 503
    assert "not configured" in response.json()["detail"]


def test_agent_run_razorpay_mode_api_failure() -> None:
    """Test /api/agent/run razorpay mode handles API failure."""
    mock_provider = MockRazorpayProvider(should_fail=True, error=RazorpayError("API error"))

    with patch("app.api.routes.configured_razorpay_client") as route_client:
        route_client.return_value = mock_provider
        with patch("app.api.routes.load_razorpay_config") as route_config:
            route_config.return_value = Mock(key_id="test", key_secret="test")
            with patch("app.agents.controller.configured_razorpay_client") as ctrl_client:
                ctrl_client.return_value = mock_provider
                with patch("app.agents.controller.load_razorpay_config") as ctrl_config:
                    ctrl_config.return_value = Mock(key_id="test", key_secret="test")
                    response = client.post("/api/agent/run?mode=razorpay&year=2025&month=1")

    assert response.status_code == 502
    assert "API error" in response.json()["detail"]


def test_agent_run_razorpay_mode_timeout() -> None:
    """Test /api/agent/run razorpay mode handles timeout."""
    from httpx import TimeoutException
    mock_provider = MockRazorpayProvider(should_fail=True, error=TimeoutException("Request timed out"))

    with patch("app.api.routes.configured_razorpay_client") as route_client:
        route_client.return_value = mock_provider
        with patch("app.api.routes.load_razorpay_config") as route_config:
            route_config.return_value = Mock(key_id="test", key_secret="test")
            with patch("app.agents.controller.configured_razorpay_client") as ctrl_client:
                ctrl_client.return_value = mock_provider
                with patch("app.agents.controller.load_razorpay_config") as ctrl_config:
                    ctrl_config.return_value = Mock(key_id="test", key_secret="test")
                    response = client.post("/api/agent/run?mode=razorpay&year=2025&month=1")

    assert response.status_code == 502
    assert "Razorpay data fetch failed" in response.json()["detail"]


def test_agent_run_razorpay_no_credentials_exposed() -> None:
    """Test /api/agent/run razorpay mode does not expose credentials."""
    recon_items = sample_recon_items()
    mock_provider = MockRazorpayProvider(recon_items=recon_items)

    with patch("app.api.routes.configured_razorpay_client") as route_client:
        route_client.return_value = mock_provider
        with patch("app.api.routes.load_razorpay_config") as route_config:
            route_config.return_value = Mock(key_id="rzp_test_1234567890", key_secret="super_secret_xyz")
            with patch("app.agents.controller.configured_razorpay_client") as ctrl_client:
                ctrl_client.return_value = mock_provider
                with patch("app.agents.controller.load_razorpay_config") as ctrl_config:
                    ctrl_config.return_value = Mock(key_id="rzp_test_1234567890", key_secret="super_secret_xyz")
                    response = client.post("/api/agent/run?mode=razorpay&year=2025&month=1")

    assert response.status_code == 200
    response_text = response.text
    assert "super_secret_xyz" not in response_text
    assert "rzp_test_1234567890" not in response_text


def test_agent_run_razorpay_requires_year_month() -> None:
    """Test /api/agent/run razorpay mode requires year and month."""
    response = client.post("/api/agent/run?mode=razorpay")
    assert response.status_code == 400
    assert "requires year and month" in response.json()["detail"]