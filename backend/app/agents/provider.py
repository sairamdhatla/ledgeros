"""Optional LLM provider boundary for investigation explanations."""

from __future__ import annotations

import json
import os
from typing import Any, Protocol

from .models import InvestigationContext

DEFAULT_OPENAI_MODEL = "gpt-4o-mini"
DEFAULT_TIMEOUT_SECONDS = 30.0
CONFIDENCE_THRESHOLD = 0.85

SYSTEM_INSTRUCTION = """You are an investigation assistant for a finance reconciliation system.

Financial truth comes from deterministic reconciliation code, not from your reasoning.
You may explain discrepancies using the supplied evidence.
You must never invent evidence.
You must never invent transaction IDs, amounts, dates, settlements, fees, or payment events.
You must never modify financial records.
You must never change the deterministic reconciliation status.
If evidence conflicts or is insufficient, explicitly say so and recommend human review.
Use only supplied evidence.
Return valid structured JSON.
Every factual claim must be traceable to one or more supplied evidence IDs.

Prefer human review when evidence conflicts, duplicate records are involved, settlement is missing,
amounts cannot be explained, or confidence is below the configured threshold.
"""


class ProviderError(RuntimeError):
    """Raised when an optional model provider cannot produce a response."""


class InvestigationProvider(Protocol):
    def investigate(self, context: InvestigationContext) -> Any:
        """Return an untrusted structured response from the provider."""


def _context_payload(context: InvestigationContext) -> dict[str, Any]:
    return context.model_dump(mode="json")


class OpenAIProvider:
    """Lazy OpenAI adapter; importing this class never requires the SDK."""

    def __init__(self, api_key: str, model: str = DEFAULT_OPENAI_MODEL, timeout: float = DEFAULT_TIMEOUT_SECONDS) -> None:
        self.api_key = api_key
        self.model = model
        self.timeout = timeout

    def investigate(self, context: InvestigationContext) -> Any:
        try:
            from openai import OpenAI
        except ImportError as error:
            raise ProviderError("OpenAI SDK is not installed") from error

        try:
            client = OpenAI(api_key=self.api_key, timeout=self.timeout)
            response = client.chat.completions.create(
                model=self.model,
                temperature=0,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": SYSTEM_INSTRUCTION},
                    {"role": "user", "content": json.dumps(_context_payload(context))},
                ],
            )
            content = response.choices[0].message.content
            if not content:
                raise ProviderError("OpenAI returned an empty response")
            return content
        except ProviderError:
            raise
        except Exception as error:
            raise ProviderError(f"OpenAI investigation failed: {error}") from error


def configured_provider() -> InvestigationProvider | None:
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        return None
    return OpenAIProvider(
        api_key=api_key,
        model=os.getenv("OPENAI_MODEL", DEFAULT_OPENAI_MODEL),
        timeout=float(os.getenv("OPENAI_TIMEOUT_SECONDS", str(DEFAULT_TIMEOUT_SECONDS))),
    )