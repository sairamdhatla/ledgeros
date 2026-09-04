"""Match normalized records by their stable transaction identifier."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from .models import BankSettlement, GatewayTransaction, Invoice


@dataclass(frozen=True)
class TransactionRecords:
    invoice: Invoice
    gateways: list[GatewayTransaction]
    banks: list[BankSettlement]


def match_records(
    invoices: list[Invoice],
    gateways: list[GatewayTransaction],
    banks: list[BankSettlement],
) -> list[TransactionRecords]:
    gateways_by_id: dict[str, list[GatewayTransaction]] = defaultdict(list)
    banks_by_id: dict[str, list[BankSettlement]] = defaultdict(list)
    for gateway in gateways:
        gateways_by_id[gateway.transaction_id].append(gateway)
    for bank in banks:
        banks_by_id[bank.transaction_id].append(bank)

    records: list[TransactionRecords] = []
    for invoice in invoices:
        records.append(
            TransactionRecords(
                invoice=invoice,
                gateways=gateways_by_id[invoice.transaction_id],
                banks=banks_by_id[invoice.transaction_id],
            )
        )
    return records
