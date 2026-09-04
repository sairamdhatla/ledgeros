"""Normalize operational CSV rows into typed reconciliation records."""

from __future__ import annotations

import csv
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Iterable, Mapping, TypeVar

from .models import BankSettlement, GatewayTransaction, Invoice


Row = Mapping[str, str]
Record = TypeVar("Record")


def _required(row: Row, field: str) -> str:
    value = row.get(field, "").strip()
    if not value:
        raise ValueError(f"Missing required field: {field}")
    return value


def _date(row: Row, field: str) -> date:
    try:
        return date.fromisoformat(_required(row, field))
    except ValueError as error:
        raise ValueError(f"Invalid {field}: {row.get(field, '')!r}") from error


def _amount(row: Row, field: str, *, allow_zero: bool = False) -> Decimal:
    value = _required(row, field)
    try:
        amount = Decimal(value)
    except InvalidOperation as error:
        raise ValueError(f"Invalid {field}: {value!r}") from error
    if amount < 0 or (amount == 0 and not allow_zero):
        raise ValueError(f"{field} must be positive: {value!r}")
    return amount


def normalize_invoice(row: Row) -> Invoice:
    return Invoice(
        transaction_id=_required(row, "transaction_id"),
        invoice_date=_date(row, "invoice_date"),
        amount_inr=_amount(row, "amount_inr"),
        currency=_required(row, "currency"),
    )


def normalize_gateway_transaction(row: Row) -> GatewayTransaction:
    return GatewayTransaction(
        transaction_id=_required(row, "transaction_id"),
        gateway_transaction_id=_required(row, "gateway_transaction_id"),
        transaction_date=_date(row, "transaction_date"),
        amount_inr=_amount(row, "amount_inr"),
        fee_inr=_amount(row, "fee_inr", allow_zero=True),
        currency=_required(row, "currency"),
    )


def normalize_bank_settlement(row: Row) -> BankSettlement:
    return BankSettlement(
        transaction_id=_required(row, "transaction_id"),
        bank_settlement_id=_required(row, "bank_settlement_id"),
        settlement_date=_date(row, "settlement_date"),
        amount_inr=_amount(row, "amount_inr"),
        currency=_required(row, "currency"),
    )


def _read_rows(path: Path) -> Iterable[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as input_file:
        yield from csv.DictReader(input_file)


def load_invoices(path: Path) -> list[Invoice]:
    return [normalize_invoice(row) for row in _read_rows(path)]


def load_gateway_transactions(path: Path) -> list[GatewayTransaction]:
    return [normalize_gateway_transaction(row) for row in _read_rows(path)]


def load_bank_settlements(path: Path) -> list[BankSettlement]:
    return [normalize_bank_settlement(row) for row in _read_rows(path)]
