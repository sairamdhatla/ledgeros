from decimal import Decimal
import json
from unittest.mock import MagicMock, patch

import httpx
import pytest

from app.services.razorpay.client import (
    RazorpayAuthError,
    RazorpayClient,
    RazorpayError,
    RazorpayNetworkError,
    RazorpayNotFoundError,
)
from app.services.razorpay.config import (
    RazorpayConfig,
    is_razorpay_configured,
    load_razorpay_config,
)
from tests.fixtures.razorpay_fixtures import (
    SAMPLE_ORDER_PAYLOAD,
    SAMPLE_PAYMENT_PAYLOAD,
    SAMPLE_PAYMENTS_LIST_PAYLOAD,
    SAMPLE_RECON_PAYLOAD,
    SAMPLE_SETTLEMENT_PAYLOAD,
    SAMPLE_SETTLEMENTS_LIST_PAYLOAD,
)


@pytest.fixture
def dummy_config() -> RazorpayConfig:
    return RazorpayConfig(
        key_id="rzp_test_1234567890",
        key_secret="dummy_secret_key_abcdef",
        base_url="https://api.razorpay.com/v1",
    )


@pytest.fixture
def razorpay_client(dummy_config: RazorpayConfig) -> RazorpayClient:
    return RazorpayClient(dummy_config)


def test_config_masks_keys(dummy_config: RazorpayConfig) -> None:
    assert dummy_config.masked_key_id() == "rzp_test***"
    assert "dummy_secret_key_abcdef" not in dummy_config.masked_key_id()


def test_load_config_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RAZORPAY_KEY_ID", "rzp_test_testkey123")
    monkeypatch.setenv("RAZORPAY_KEY_SECRET", "test_secret_456")
    config = load_razorpay_config()
    assert config is not None
    assert config.key_id == "rzp_test_testkey123"
    assert config.key_secret == "test_secret_456"
    assert is_razorpay_configured() is True


def test_load_config_missing_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("RAZORPAY_KEY_ID", raising=False)
    monkeypatch.delenv("RAZORPAY_KEY_SECRET", raising=False)
    assert load_razorpay_config() is None
    assert is_razorpay_configured() is False


def test_client_get_payment(razorpay_client: RazorpayClient) -> None:
    with patch("httpx.Client.get") as mock_get:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = SAMPLE_PAYMENT_PAYLOAD
        mock_get.return_value = mock_response

        payment = razorpay_client.get_payment("pay_TEST0000000001")

        assert payment.id == "pay_TEST0000000001"
        assert payment.amount == 500000
        assert payment.amount_inr == Decimal("5000.00")
        assert payment.fee_inr == Decimal("100.00")
        assert payment.tax_inr == Decimal("18.00")
        assert payment.total_deduction_inr == Decimal("118.00")
        assert payment.net_amount_inr == Decimal("4882.00")
        assert payment.status == "captured"
        assert payment.method == "card"
        assert mock_get.call_args[0][0] == "https://api.razorpay.com/v1/payments/pay_TEST0000000001"


def test_client_list_payments(razorpay_client: RazorpayClient) -> None:
    with patch("httpx.Client.get") as mock_get:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = SAMPLE_PAYMENTS_LIST_PAYLOAD
        mock_get.return_value = mock_response

        payments = razorpay_client.list_payments(count=2)

        assert len(payments) == 2
        assert payments[0].id == "pay_TEST0000000001"
        assert payments[1].id == "pay_TEST0000000002"
        assert payments[1].amount_inr == Decimal("2500.00")
        assert payments[1].fee_inr == Decimal("0.00")


def test_client_get_settlement(razorpay_client: RazorpayClient) -> None:
    with patch("httpx.Client.get") as mock_get:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = SAMPLE_SETTLEMENT_PAYLOAD
        mock_get.return_value = mock_response

        settlement = razorpay_client.get_settlement("setl_TEST0000000001")

        assert settlement.id == "setl_TEST0000000001"
        assert settlement.amount_inr == Decimal("4882.00")
        assert settlement.fees_inr == Decimal("100.00")
        assert settlement.tax_inr == Decimal("18.00")
        assert settlement.utr == "UTRTEST987654321"
        assert settlement.status == "processed"


def test_client_list_settlements(razorpay_client: RazorpayClient) -> None:
    with patch("httpx.Client.get") as mock_get:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = SAMPLE_SETTLEMENTS_LIST_PAYLOAD
        mock_get.return_value = mock_response

        settlements = razorpay_client.list_settlements(count=1)

        assert len(settlements) == 1
        assert settlements[0].id == "setl_TEST0000000001"


def test_client_get_settlement_recon(razorpay_client: RazorpayClient) -> None:
    with patch("httpx.Client.get") as mock_get:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = SAMPLE_RECON_PAYLOAD
        mock_get.return_value = mock_response

        recon_items = razorpay_client.get_settlement_recon(year=2025, month=1, count=50, skip=10)

        assert len(recon_items) == 3
        # Payment 1
        assert recon_items[0].entity_id == "pay_TEST0000000001"
        assert recon_items[0].type == "payment"
        assert recon_items[0].amount_inr == Decimal("5000.00")
        assert recon_items[0].credit_inr == Decimal("4882.00")
        assert recon_items[0].debit_inr == Decimal("0.00")
        assert recon_items[0].fee_inr == Decimal("100.00")
        assert recon_items[0].tax_inr == Decimal("18.00")
        assert recon_items[0].settlement_id == "setl_BATCH00000001"
        assert recon_items[0].settlement_utr == "UTRTEST987654321"
        assert recon_items[0].order_receipt == "INV-2025-001"
        assert recon_items[0].card_network == "MasterCard"
        # Refund
        assert recon_items[2].entity_id == "rfnd_TEST0000000001"
        assert recon_items[2].type == "refund"
        assert recon_items[2].debit_inr == Decimal("500.00")
        assert recon_items[2].credit_inr == Decimal("0.00")
        assert recon_items[2].payment_id == "pay_TEST0000000001"
        assert recon_items[2].settlement_id == "setl_BATCH00000001"

        # Verify count and skip are passed in query params
        params = mock_get.call_args[1]["params"]
        assert params["count"] == 50
        assert params["skip"] == 10
        assert params["year"] == 2025
        assert params["month"] == "01"


def test_client_get_order(razorpay_client: RazorpayClient) -> None:
    with patch("httpx.Client.get") as mock_get:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = SAMPLE_ORDER_PAYLOAD
        mock_get.return_value = mock_response

        order = razorpay_client.get_order("order_TEST0000000001")

        assert order.id == "order_TEST0000000001"
        assert order.receipt == "RCP-TEST-001"
        assert order.amount_inr == Decimal("5000.00")


def test_client_auth_error_on_401(razorpay_client: RazorpayClient) -> None:
    with patch("httpx.Client.get") as mock_get:
        mock_response = MagicMock()
        mock_response.status_code = 401
        mock_get.return_value = mock_response

        with pytest.raises(RazorpayAuthError, match="Invalid Razorpay API credentials"):
            razorpay_client.get_payment("pay_invalid")


def test_client_not_found_on_404(razorpay_client: RazorpayClient) -> None:
    with patch("httpx.Client.get") as mock_get:
        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_get.return_value = mock_response

        with pytest.raises(RazorpayNotFoundError, match="not found"):
            razorpay_client.get_payment("pay_nonexistent")


def test_client_network_error_on_timeout(razorpay_client: RazorpayClient) -> None:
    with patch("httpx.Client.get", side_effect=httpx.TimeoutException("Connection timed out")):
        with pytest.raises(RazorpayNetworkError, match="timed out"):
            razorpay_client.get_payment("pay_timeout")


def test_client_strictly_read_only(razorpay_client: RazorpayClient) -> None:
    """Verify that RazorpayClient does not expose mutating methods."""
    assert not hasattr(razorpay_client, "post")
    assert not hasattr(razorpay_client, "capture_payment")
    assert not hasattr(razorpay_client, "create_refund")
    assert not hasattr(razorpay_client, "update_payment")
    assert not hasattr(razorpay_client, "delete")
