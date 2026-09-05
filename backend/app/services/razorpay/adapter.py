"""Adapter normalizing Razorpay entities into LedgerOS deterministic reconciliation models."""

from __future__ import annotations

from decimal import Decimal
from typing import Sequence

from app.reconciliation.models import BankSettlement, GatewayTransaction
from .client import RazorpayDataProvider
from .models import (
    NormalizedReconRecord,
    RazorpayPayment,
    RazorpayReconItem,
    RazorpaySettlement,
)


class RazorpayAdapter:
    """Normalizes official Razorpay data into typed LedgerOS reconciliation inputs."""

    @staticmethod
    def payment_to_gateway_transaction(payment: RazorpayPayment) -> GatewayTransaction:
        """Map a RazorpayPayment to an internal GatewayTransaction.

        CRITICAL: Fee deduction is the sum of Razorpay's actual fee and tax fields.
        No tax rate or percentage is hardcoded.
        """
        transaction_id = payment.order_id or payment.invoice_id or payment.id
        return GatewayTransaction(
            transaction_id=transaction_id,
            gateway_transaction_id=payment.id,
            transaction_date=payment.created_date,
            amount_inr=payment.amount_inr,
            fee_inr=payment.total_deduction_inr,
            currency=payment.currency,
        )

    @staticmethod
    def recon_item_to_normalized_record(item: RazorpayReconItem) -> NormalizedReconRecord:
        """Normalize an official GET /v1/settlements/recon/combined item.

        Preserves the crucial link between the individual transaction (entity_id, payment_id),
        the order/receipt reference, and the settlement batch (settlement_id, settlement_utr).
        No tax rates are hardcoded; actual fee and tax fields are preserved.
        """
        transaction_id = item.order_receipt or item.order_id or item.entity_id
        return NormalizedReconRecord(
            entity_id=item.entity_id,
            transaction_id=transaction_id,
            settlement_id=item.settlement_id,
            settlement_utr=item.settlement_utr,
            record_type=item.type,
            gross_amount_inr=item.amount_inr,
            fee_inr=item.fee_inr,
            tax_inr=item.tax_inr,
            total_deduction_inr=item.total_deduction_inr,
            credit_inr=item.credit_inr,
            debit_inr=item.debit_inr,
            currency=item.currency,
            settled=item.settled,
            created_date=item.created_date,
            settled_date=item.settled_date,
            order_id=item.order_id,
            order_receipt=item.order_receipt,
            payment_id=item.payment_id,
            method=item.method,
            card_network=item.card_network,
            dispute_id=item.dispute_id,
        )

    @classmethod
    def recon_items_to_normalized_records(
        cls,
        items: Sequence[RazorpayReconItem],
    ) -> list[NormalizedReconRecord]:
        return [cls.recon_item_to_normalized_record(item) for item in items]

    @classmethod
    def recon_items_to_reconciliation_records(
        cls,
        items: Sequence[RazorpayReconItem],
    ) -> tuple[list[GatewayTransaction], list[BankSettlement]]:
        """Extract gateway and bank records from transaction-level settlement-recon records.

        - Correctly maps multiple payments belonging to the same settlement batch.
        - Preserves the transaction's allocated net credit as the bank settlement amount.
        - Excludes refunds and adjustments from ordinary payment gateway transactions.
        """
        normalized_records = cls.recon_items_to_normalized_records(items)
        gateways: list[GatewayTransaction] = []
        banks: list[BankSettlement] = []

        for record in normalized_records:
            if not record.is_payment:
                # Refunds, adjustments, or transfers must not be coerced into ordinary payments
                continue
            gateways.append(record.to_gateway_transaction())
            if record.settled and record.settled_date is not None:
                banks.append(record.to_bank_settlement())

        return gateways, banks

    @staticmethod
    def settlement_to_bank_settlement(
        settlement: RazorpaySettlement,
        transaction_id: str | None = None,
    ) -> BankSettlement:
        """Map an aggregate RazorpaySettlement to an internal BankSettlement.

        IMPORTANT ARCHITECTURAL NOTE:
        RazorpaySettlement is an aggregate payout batch covering multiple transactions.
        Do NOT map aggregate settlements directly into individual transaction reconciliation
        without an explicit 1:1 transaction linkage. Use `recon_items_to_reconciliation_records`
        for transaction-level reconciliation with settlement allocations.
        """
        ref_id = transaction_id or settlement.utr or settlement.id
        settlement_id = settlement.utr or settlement.id
        return BankSettlement(
            transaction_id=ref_id,
            bank_settlement_id=settlement_id,
            settlement_date=settlement.settled_date,
            amount_inr=settlement.amount_inr,
            currency="INR",
        )

    @classmethod
    def payments_to_gateway_transactions(
        cls,
        payments: Sequence[RazorpayPayment],
    ) -> list[GatewayTransaction]:
        return [cls.payment_to_gateway_transaction(payment) for payment in payments]

    @classmethod
    def settlements_to_bank_settlements(
        cls,
        settlements: Sequence[RazorpaySettlement],
    ) -> list[BankSettlement]:
        return [cls.settlement_to_bank_settlement(settlement) for settlement in settlements]

    @classmethod
    def fetch_and_normalize_recon(
        cls,
        provider: RazorpayDataProvider,
        year: int,
        month: int,
        day: int | None = None,
        count: int = 50,
        skip: int = 0,
    ) -> tuple[list[GatewayTransaction], list[BankSettlement]]:
        """Fetch settlement reconciliation items from a provider and normalize them."""
        recon_items = provider.get_settlement_recon(
            year=year,
            month=month,
            day=day,
            count=count,
            skip=skip,
        )
        return cls.recon_items_to_reconciliation_records(recon_items)
