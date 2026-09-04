"""Optional LLM provider boundary for investigation explanations."""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Mapping
from typing import Any, Protocol

from .models import InvestigationContext

DEFAULT_OPENROUTER_MODEL = "google/gemma-4-26b-a4b-it"
DEFAULT_TIMEOUT_SECONDS = 30.0
CONFIDENCE_THRESHOLD = 0.85
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
logger = logging.getLogger(__name__)

INVESTIGATION_JSON_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "case_id", "conclusion", "discrepancy_type", "confidence", "evidence_ids",
        "evidence_summary", "recommended_action", "requires_human_review", "ai_generated",
        "guardrail_flags",
    ],
    "properties": {
        "case_id": {"type": "string"},
        "conclusion": {"type": "string"},
        "discrepancy_type": {"type": "string", "enum": [
            "NONE", "GATEWAY_FEE", "SETTLEMENT_TIMING", "PARTIAL_PAYMENT",
            "DUPLICATE_TRANSACTION", "MISSING_BANK_SETTLEMENT", "UNEXPLAINED_DISCREPANCY",
        ]},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "evidence_ids": {"type": "array", "items": {"type": "string"}, "minItems": 1},
        "evidence_summary": {"type": "string"},
        "recommended_action": {"type": "string", "enum": [
            "NO_ACTION", "REVIEW_SOURCE_RECORDS", "VERIFY_SETTLEMENT", "VERIFY_PAYMENT",
            "INVESTIGATE_DUPLICATE", "ESCALATE",
        ]},
        "requires_human_review": {"type": "boolean"},
        "ai_generated": {"type": "boolean"},
        "guardrail_flags": {"type": "array", "items": {"type": "string"}},
    },
}

SYSTEM_INSTRUCTION = """You are an investigation assistant for a finance reconciliation system.

Financial truth comes from deterministic reconciliation code, not from your reasoning.
You may explain discrepancies using the supplied evidence.
You must never invent evidence.
You must never invent transaction IDs, amounts, dates, settlements, fees, or payment events.
You must never modify financial records.
You must never change the deterministic reconciliation status.
If evidence conflicts or is insufficient, explicitly say so and recommend human review.
Use only supplied evidence.
Return only valid JSON with every required field: case_id, conclusion, discrepancy_type,
confidence, evidence_ids, evidence_summary, recommended_action, requires_human_review,
ai_generated, and guardrail_flags. The case_id and evidence_ids must come from the supplied
context. discrepancy_type must be one of NONE, GATEWAY_FEE, SETTLEMENT_TIMING, PARTIAL_PAYMENT,
DUPLICATE_TRANSACTION, MISSING_BANK_SETTLEMENT, or UNEXPLAINED_DISCREPANCY. recommended_action
must be one of NO_ACTION, REVIEW_SOURCE_RECORDS, VERIFY_SETTLEMENT, VERIFY_PAYMENT,
INVESTIGATE_DUPLICATE, or ESCALATE. Set ai_generated to true only for this response.
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


def _message_content(response: Any) -> Any:
    try:
        content = response.choices[0].message.content
    except (AttributeError, IndexError, TypeError) as error:
        raise ProviderError("OpenRouter response did not contain assistant content") from error
    if isinstance(content, str):
        return content
    if isinstance(content, Mapping):
        return dict(content)
    if isinstance(content, list):
        text_parts = [
            part.get("text", "") if isinstance(part, dict) else getattr(part, "text", "")
            for part in content
        ]
        return "".join(text_parts)
    raise ProviderError("OpenRouter assistant content had an unsupported format")


class OpenRouterProvider:
    """Lazy OpenRouter adapter using the OpenAI-compatible SDK."""

    def __init__(self, api_key: str, model: str, timeout: float = DEFAULT_TIMEOUT_SECONDS) -> None:
        self.api_key = api_key
        self.model = model
        self.timeout = timeout

    def investigate(self, context: InvestigationContext) -> Any:
        try:
            from openai import OpenAI
        except ImportError as error:
            raise ProviderError("OpenAI SDK is not installed") from error

        try:
            client = OpenAI(api_key=self.api_key, base_url=OPENROUTER_BASE_URL, timeout=self.timeout)
            response = client.chat.completions.create(
                model=self.model,
                temperature=0,
                response_format={
                    "type": "json_schema",
                    "json_schema": {
                        "name": "ledgeros_investigation",
                        "strict": True,
                        "schema": INVESTIGATION_JSON_SCHEMA,
                    },
                },
                messages=[
                    {"role": "system", "content": SYSTEM_INSTRUCTION},
                    {"role": "user", "content": json.dumps(_context_payload(context))},
                ],
            )
            content = _message_content(response)
            if not content:
                raise ProviderError("OpenRouter returned an empty response")
            logger.info("OpenRouter investigation completed with model=%s", self.model)
            return content
        except ProviderError:
            raise
        except Exception as error:
            raise ProviderError(f"OpenRouter investigation failed: {error}") from error


def configured_provider() -> InvestigationProvider | None:
    api_key = os.getenv("OPENROUTER_API_KEY", "").strip()
    if not api_key:
        return None
    return OpenRouterProvider(
        api_key=api_key,
        model=os.getenv("OPENROUTER_MODEL", DEFAULT_OPENROUTER_MODEL).strip() or DEFAULT_OPENROUTER_MODEL,
        timeout=float(os.getenv("OPENROUTER_TIMEOUT_SECONDS", str(DEFAULT_TIMEOUT_SECONDS))),
    )