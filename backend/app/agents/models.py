"""Pydantic contracts for evidence-grounded exception investigation."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class RecommendedAction(str, Enum):
    NO_ACTION = "NO_ACTION"
    REVIEW_SOURCE_RECORDS = "REVIEW_SOURCE_RECORDS"
    VERIFY_SETTLEMENT = "VERIFY_SETTLEMENT"
    VERIFY_PAYMENT = "VERIFY_PAYMENT"
    INVESTIGATE_DUPLICATE = "INVESTIGATE_DUPLICATE"
    ESCALATE = "ESCALATE"


class DiscrepancyType(str, Enum):
    NONE = "NONE"
    GATEWAY_FEE = "GATEWAY_FEE"
    SETTLEMENT_TIMING = "SETTLEMENT_TIMING"
    PARTIAL_PAYMENT = "PARTIAL_PAYMENT"
    DUPLICATE_TRANSACTION = "DUPLICATE_TRANSACTION"
    MISSING_BANK_SETTLEMENT = "MISSING_BANK_SETTLEMENT"
    UNEXPLAINED_DISCREPANCY = "UNEXPLAINED_DISCREPANCY"


class RootCause(str, Enum):
    EXACT_MATCH = "EXACT_MATCH"
    GATEWAY_FEE = "GATEWAY_FEE"
    SETTLEMENT_TIMING = "SETTLEMENT_TIMING"
    PARTIAL_PAYMENT = "PARTIAL_PAYMENT"
    DUPLICATE_TRANSACTION = "DUPLICATE_TRANSACTION"
    MISSING_BANK_SETTLEMENT = "MISSING_BANK_SETTLEMENT"
    UNEXPLAINED_DISCREPANCY = "UNEXPLAINED_DISCREPANCY"


class InvoiceEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    invoice_id: str = Field(min_length=1)
    amount_inr: Decimal = Field(gt=0)
    invoice_date: date
    metadata: dict[str, str] = Field(default_factory=dict)


class GatewayEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    transaction_id: str = Field(min_length=1)
    invoice_reference_id: str = Field(min_length=1)
    gross_amount_inr: Decimal = Field(gt=0)
    fee_inr: Decimal = Field(ge=0)
    net_amount_inr: Decimal = Field(gt=0)
    transaction_date: date


class BankEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    settlement_id: str = Field(min_length=1)
    reference_id: str = Field(min_length=1)
    amount_inr: Decimal = Field(gt=0)
    settlement_date: date


class ReconciliationEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str = Field(min_length=1)
    deterministic_rule: str = Field(min_length=1)
    deterministic_status: str = Field(min_length=1)
    deterministic_reason: str = Field(min_length=1)
    deterministic_discrepancy: str = Field(min_length=1)
    evidence_ids: tuple[str, ...] = Field(min_length=1)
    evidence_consistent: bool = True


class InvestigationContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str = Field(min_length=1)
    invoice: InvoiceEvidence
    gateway: tuple[GatewayEvidence, ...] = ()
    bank: tuple[BankEvidence, ...] = ()
    reconciliation: ReconciliationEvidence
    tool_results: dict[str, Any] = Field(default_factory=dict)


class InvestigationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str = Field(min_length=1)
    conclusion: str = Field(min_length=1)
    discrepancy_type: DiscrepancyType
    root_cause: RootCause
    confidence: float = Field(ge=0, le=1)
    evidence_ids: tuple[str, ...] = Field(min_length=1)
    evidence_summary: str = Field(min_length=1)
    recommended_action: RecommendedAction
    requires_human_review: bool
    ai_generated: bool
    guardrail_flags: tuple[str, ...] = ()