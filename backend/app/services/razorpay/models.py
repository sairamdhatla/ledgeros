"""Pydantic schemas and normalized models for official Razorpay entities."""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.reconciliation.models import BankSettlement, GatewayTransaction


class RazorpayPayment(BaseModel):
    """Represents a Razorpay payment entity returned from /v1/payments."""

    model_config = ConfigDict(extra="ignore")

    id: str = Field(min_length=1)
    entity: str = "payment"
    amount: int = Field(ge=0, description="Amount in currency subunits (paise)")
    currency: str = "INR"
    status: str
    order_id: str | None = None
    invoice_id: str | None = None
    method: str | None = None
    amount_refunded: int = 0
    refund_status: str | None = None
    captured: bool = False
    description: str | None = None
    bank: str | None = None
    wallet: str | None = None
    vpa: str | None = None
    email: str | None = None
    contact: str | None = None
    fee: int = Field(default=0, ge=0, description="Platform processing fee in paise")
    tax: int = Field(default=0, ge=0, description="Tax on fee in paise")
    error_code: str | None = None
    error_description: str | None = None
    created_at: int = Field(description="Unix timestamp (seconds)")

    @property
    def amount_inr(self) -> Decimal:
        return Decimal(self.amount) / Decimal(100)

    @property
    def fee_inr(self) -> Decimal:
        return Decimal(self.fee) / Decimal(100)

    @property
    def tax_inr(self) -> Decimal:
        return Decimal(self.tax) / Decimal(100)

    @property
    def total_deduction_inr(self) -> Decimal:
        """Total gateway deduction = platform fee + tax on fee. No hardcoded rates."""
        return (Decimal(self.fee) + Decimal(self.tax)) / Decimal(100)

    @property
    def net_amount_inr(self) -> Decimal:
        return self.amount_inr - self.total_deduction_inr

    @property
    def created_date(self) -> date:
        return datetime.fromtimestamp(self.created_at, tz=timezone.utc).date()


class RazorpaySettlement(BaseModel):
    """Represents an aggregate Razorpay settlement batch returned from /v1/settlements.

    NOTE: An aggregate settlement payout can contain multiple transactions.
    It represents the bank deposit batch, not an individual transaction reconciliation.
    """

    model_config = ConfigDict(extra="ignore")

    id: str = Field(min_length=1)
    entity: str = "settlement"
    amount: int = Field(ge=0, description="Total settled amount in paise for the payout batch")
    status: str
    fees: int = Field(default=0, ge=0, description="Total fees in paise for the payout batch")
    tax: int = Field(default=0, ge=0, description="Total tax in paise for the payout batch")
    utr: str | None = None
    created_at: int = Field(description="Unix timestamp (seconds)")

    @property
    def amount_inr(self) -> Decimal:
        return Decimal(self.amount) / Decimal(100)

    @property
    def fees_inr(self) -> Decimal:
        return Decimal(self.fees) / Decimal(100)

    @property
    def tax_inr(self) -> Decimal:
        return Decimal(self.tax) / Decimal(100)

    @property
    def settled_date(self) -> date:
        return datetime.fromtimestamp(self.created_at, tz=timezone.utc).date()


class RazorpayReconItem(BaseModel):
    """Official Razorpay settlement reconciliation record from GET /v1/settlements/recon/combined.

    Preserves all official fields representing the transaction-level allocation within
    a settlement batch.
    """

    model_config = ConfigDict(extra="ignore")

    entity_id: str = Field(min_length=1, description="Unique ID of the transaction (pay_xxx, rfnd_xxx)")
    type: str = Field(description="Transaction type: payment, refund, adjustment, transfer")
    debit: int = Field(default=0, ge=0, description="Debit amount in paise")
    credit: int = Field(default=0, ge=0, description="Credit amount in paise")
    amount: int = Field(default=0, ge=0, description="Gross transaction amount in paise")
    currency: str = "INR"
    fee: int = Field(default=0, ge=0, description="Platform fee in paise")
    tax: int = Field(default=0, ge=0, description="Tax on fee in paise")
    on_hold: bool = False
    settled: bool = False
    created_at: int = Field(description="Transaction creation unix timestamp")
    settled_at: int | None = Field(default=None, description="Settlement unix timestamp")
    settlement_id: str | None = Field(default=None, description="Settlement batch identifier (setl_xxx)")
    description: str | None = None
    notes: Any = None
    payment_id: str | None = Field(default=None, description="Associated payment ID for refunds/adjustments")
    settlement_utr: str | None = Field(default=None, description="Bank UTR reference for the settlement batch")
    order_id: str | None = Field(default=None, description="Razorpay order identifier")
    order_receipt: str | None = Field(default=None, description="Merchant invoice or internal reference")
    method: str | None = None
    card_network: str | None = None
    card_issuer: str | None = None
    card_type: str | None = None
    dispute_id: str | None = None

    @property
    def amount_inr(self) -> Decimal:
        return Decimal(self.amount) / Decimal(100)

    @property
    def fee_inr(self) -> Decimal:
        return Decimal(self.fee) / Decimal(100)

    @property
    def tax_inr(self) -> Decimal:
        return Decimal(self.tax) / Decimal(100)

    @property
    def total_deduction_inr(self) -> Decimal:
        """Total deduction = actual fee + actual tax from Razorpay fields."""
        return (Decimal(self.fee) + Decimal(self.tax)) / Decimal(100)

    @property
    def debit_inr(self) -> Decimal:
        return Decimal(self.debit) / Decimal(100)

    @property
    def credit_inr(self) -> Decimal:
        return Decimal(self.credit) / Decimal(100)

    @property
    def created_date(self) -> date:
        return datetime.fromtimestamp(self.created_at, tz=timezone.utc).date()

    @property
    def settled_date(self) -> date | None:
        if self.settled_at is None:
            return None
        return datetime.fromtimestamp(self.settled_at, tz=timezone.utc).date()


class RazorpayOrder(BaseModel):
    """Represents a Razorpay order entity returned from /v1/orders/{id}."""

    model_config = ConfigDict(extra="ignore")

    id: str = Field(min_length=1)
    entity: str = "order"
    amount: int = Field(ge=0)
    currency: str = "INR"
    receipt: str | None = None
    status: str
    created_at: int

    @property
    def amount_inr(self) -> Decimal:
        return Decimal(self.amount) / Decimal(100)


class NormalizedReconRecord(BaseModel):
    """Internal normalized representation of a transaction linked to its settlement batch.

    Maintains the relationship between an individual payment/refund and the aggregate settlement,
    ensuring that 1 payment does not equal the entire multi-transaction settlement batch.
    """

    model_config = ConfigDict(extra="forbid")

    entity_id: str
    transaction_id: str
    settlement_id: str | None = None
    settlement_utr: str | None = None
    record_type: str
    gross_amount_inr: Decimal
    fee_inr: Decimal
    tax_inr: Decimal
    total_deduction_inr: Decimal
    credit_inr: Decimal
    debit_inr: Decimal
    currency: str = "INR"
    settled: bool = False
    created_date: date
    settled_date: date | None = None
    order_id: str | None = None
    order_receipt: str | None = None
    payment_id: str | None = None
    method: str | None = None
    card_network: str | None = None
    dispute_id: str | None = None

    @property
    def is_payment(self) -> bool:
        return self.record_type == "payment"

    @property
    def is_refund(self) -> bool:
        return self.record_type == "refund"

    @property
    def is_adjustment(self) -> bool:
        return self.record_type == "adjustment"

    def to_gateway_transaction(self) -> GatewayTransaction:
        """Convert a payment record to a typed GatewayTransaction.

        Refunds and adjustments are not ordinary payments and must not be coerced.
        """
        if not self.is_payment:
            raise ValueError(f"Cannot convert non-payment record ({self.record_type}) to GatewayTransaction")
        return GatewayTransaction(
            transaction_id=self.transaction_id,
            gateway_transaction_id=self.entity_id,
            transaction_date=self.created_date,
            amount_inr=self.gross_amount_inr,
            fee_inr=self.total_deduction_inr,
            currency=self.currency,
        )

    def to_bank_settlement(self) -> BankSettlement:
        """Convert a settled payment record to a typed BankSettlement.

        The bank settlement amount is the net credit amount allocated to THIS transaction,
        preserving the relationship to the settlement UTR/batch ID.
        """
        if not self.is_payment:
            raise ValueError(f"Cannot convert non-payment record ({self.record_type}) to BankSettlement")
        if not self.settled or self.settled_date is None:
            raise ValueError(f"Cannot convert unsettled record {self.entity_id} to BankSettlement")
        bank_id = self.settlement_utr or self.settlement_id or self.entity_id
        return BankSettlement(
            transaction_id=self.transaction_id,
            bank_settlement_id=bank_id,
            settlement_date=self.settled_date,
            amount_inr=self.credit_inr,
            currency=self.currency,
        )
