"""Strictly read-only Razorpay API client using official REST endpoints."""

from __future__ import annotations

import logging
from typing import Any, Protocol

import httpx

from .config import RazorpayConfig, is_razorpay_configured, load_razorpay_config
from .models import RazorpayOrder, RazorpayPayment, RazorpayReconItem, RazorpaySettlement

logger = logging.getLogger(__name__)


class RazorpayError(RuntimeError):
    """Base error for Razorpay integration issues."""


class RazorpayAuthError(RazorpayError):
    """Raised on 401 Unauthorized errors from Razorpay."""


class RazorpayNotFoundError(RazorpayError):
    """Raised when a requested Razorpay resource is not found (404)."""


class RazorpayNetworkError(RazorpayError):
    """Raised on connection failures or timeouts."""


class RazorpayDataProvider(Protocol):
    """Protocol defining the read-only Razorpay data retrieval interface."""

    def get_payment(self, payment_id: str) -> RazorpayPayment: ...
    def list_payments(
        self,
        count: int = 10,
        skip: int = 0,
        from_epoch: int | None = None,
        to_epoch: int | None = None,
    ) -> list[RazorpayPayment]: ...
    def get_settlement(self, settlement_id: str) -> RazorpaySettlement: ...
    def list_settlements(
        self,
        count: int = 10,
        skip: int = 0,
        from_epoch: int | None = None,
        to_epoch: int | None = None,
    ) -> list[RazorpaySettlement]: ...
    def get_settlement_recon(
        self,
        year: int,
        month: int,
        day: int | None = None,
        count: int = 10,
        skip: int = 0,
    ) -> list[RazorpayReconItem]: ...
    def get_order(self, order_id: str) -> RazorpayOrder: ...


class RazorpayClient:
    """Read-only Razorpay client enforcing strict GET-only access.

    This client NEVER performs mutations (capture, refund, cancel, or modify).
    """

    def __init__(self, config: RazorpayConfig) -> None:
        self.config = config

    def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        url = f"{self.config.base_url}{path}"
        try:
            with httpx.Client(timeout=self.config.timeout_seconds) as client:
                response = client.get(
                    url,
                    auth=(self.config.key_id, self.config.key_secret),
                    params=params,
                    headers={"Accept": "application/json"},
                )
        except httpx.TimeoutException as error:
            raise RazorpayNetworkError(f"Razorpay request timed out: {path}") from error
        except httpx.RequestError as error:
            raise RazorpayNetworkError(f"Razorpay network error on {path}: {error}") from error

        if response.status_code == 401:
            raise RazorpayAuthError("Invalid Razorpay API credentials")
        if response.status_code == 404:
            raise RazorpayNotFoundError(f"Razorpay resource not found: {path}")
        if response.status_code >= 400:
            error_data = response.json().get("error", {}) if response.headers.get("content-type", "").startswith("application/json") else {}
            description = error_data.get("description", response.text)
            raise RazorpayError(f"Razorpay API error ({response.status_code}): {description}")

        return response.json()

    def get_payment(self, payment_id: str) -> RazorpayPayment:
        """Fetch a payment by ID."""
        data = self._get(f"/payments/{payment_id}")
        return RazorpayPayment.model_validate(data)

    def list_payments(
        self,
        count: int = 10,
        skip: int = 0,
        from_epoch: int | None = None,
        to_epoch: int | None = None,
    ) -> list[RazorpayPayment]:
        """Fetch a list of payments."""
        params: dict[str, Any] = {"count": count, "skip": skip}
        if from_epoch is not None:
            params["from"] = from_epoch
        if to_epoch is not None:
            params["to"] = to_epoch
        data = self._get("/payments", params=params)
        items = data.get("items", []) if isinstance(data, dict) else data
        return [RazorpayPayment.model_validate(item) for item in items]

    def get_settlement(self, settlement_id: str) -> RazorpaySettlement:
        """Fetch a settlement by ID."""
        data = self._get(f"/settlements/{settlement_id}")
        return RazorpaySettlement.model_validate(data)

    def list_settlements(
        self,
        count: int = 10,
        skip: int = 0,
        from_epoch: int | None = None,
        to_epoch: int | None = None,
    ) -> list[RazorpaySettlement]:
        """Fetch a list of settlements."""
        params: dict[str, Any] = {"count": count, "skip": skip}
        if from_epoch is not None:
            params["from"] = from_epoch
        if to_epoch is not None:
            params["to"] = to_epoch
        data = self._get("/settlements", params=params)
        items = data.get("items", []) if isinstance(data, dict) else data
        return [RazorpaySettlement.model_validate(item) for item in items]

    def get_settlement_recon(
        self,
        year: int,
        month: int,
        day: int | None = None,
        count: int = 10,
        skip: int = 0,
    ) -> list[RazorpayReconItem]:
        """Fetch consolidated settlement reconciliation data for period with pagination."""
        params: dict[str, Any] = {
            "year": year,
            "month": f"{month:02d}",
            "count": count,
            "skip": skip,
        }
        if day is not None:
            params["day"] = f"{day:02d}"
        data = self._get("/settlements/recon/combined", params=params)
        items = data.get("items", []) if isinstance(data, dict) else data
        return [RazorpayReconItem.model_validate(item) for item in items]

    def get_order(self, order_id: str) -> RazorpayOrder:
        """Fetch an order by ID."""
        data = self._get(f"/orders/{order_id}")
        return RazorpayOrder.model_validate(data)


def configured_razorpay_client() -> RazorpayClient | None:
    """Return a configured RazorpayClient if credentials are set, or None."""
    config = load_razorpay_config()
    if config is None:
        return None
    return RazorpayClient(config)
