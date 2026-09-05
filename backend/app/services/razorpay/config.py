"""Configuration and credentials management for the Razorpay API integration."""

from __future__ import annotations

from dataclasses import dataclass
import os

DEFAULT_RAZORPAY_BASE_URL = "https://api.razorpay.com/v1"
DEFAULT_TIMEOUT_SECONDS = 30.0


class RazorpayConfigError(ValueError):
    """Raised when required Razorpay configuration or credentials are missing."""


@dataclass(frozen=True)
class RazorpayConfig:
    key_id: str
    key_secret: str
    base_url: str = DEFAULT_RAZORPAY_BASE_URL
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS

    def masked_key_id(self) -> str:
        if not self.key_id:
            return ""
        if len(self.key_id) <= 8:
            return "***"
        return f"{self.key_id[:8]}***"


def mask_secret(secret: str) -> str:
    """Mask a secret value for safe logging or reporting."""
    if not secret:
        return ""
    return "***"


def load_razorpay_config() -> RazorpayConfig | None:
    """Load Razorpay configuration from environment variables if present."""
    key_id = os.getenv("RAZORPAY_KEY_ID", "").strip()
    key_secret = os.getenv("RAZORPAY_KEY_SECRET", "").strip()
    if not key_id or not key_secret:
        return None

    base_url = os.getenv("RAZORPAY_BASE_URL", DEFAULT_RAZORPAY_BASE_URL).strip() or DEFAULT_RAZORPAY_BASE_URL
    try:
        timeout = float(os.getenv("RAZORPAY_TIMEOUT_SECONDS", str(DEFAULT_TIMEOUT_SECONDS)))
    except ValueError:
        timeout = DEFAULT_TIMEOUT_SECONDS

    return RazorpayConfig(
        key_id=key_id,
        key_secret=key_secret,
        base_url=base_url.rstrip("/"),
        timeout_seconds=timeout,
    )


def is_razorpay_configured() -> bool:
    """Check if valid Razorpay credentials are present in the environment."""
    return load_razorpay_config() is not None
