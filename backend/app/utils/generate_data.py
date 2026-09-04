"""Generate deterministic synthetic finance reconciliation data."""

from __future__ import annotations

import csv
import random
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Iterable


CASE_COUNT = 500
RANDOM_SEED = 20260904
OUTPUT_DIRECTORY = Path(__file__).resolve().parents[3] / "data" / "generated"

SCENARIOS = (
    "exact_match",
    "gateway_fee_deduction",
    "settlement_timing_difference",
    "partial_payment",
    "duplicate_transaction",
    "missing_bank_settlement",
    "unexplained_discrepancy",
)


@dataclass(frozen=True)
class TransactionCase:
    """The ground-truth values used to create one synthetic transaction case."""

    transaction_id: str
    invoice_date: date
    invoice_amount: int
    scenario: str
    gateway_amount: int
    gateway_fee: int
    bank_amount: int | None
    bank_settlement_date: date | None

    @property
    def expected_outcome(self) -> str:
        outcomes = {
            "exact_match": "matched",
            "gateway_fee_deduction": "matched_after_gateway_fee",
            "settlement_timing_difference": "matched_after_timing_difference",
            "partial_payment": "partial_payment",
            "duplicate_transaction": "duplicate_gateway_transaction",
            "missing_bank_settlement": "missing_bank_settlement",
            "unexplained_discrepancy": "unexplained_discrepancy",
        }
        return outcomes[self.scenario]


def _write_csv(path: Path, fieldnames: list[str], rows: Iterable[dict[str, object]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as output_file:
        writer = csv.DictWriter(output_file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _build_cases() -> list[TransactionCase]:
    generator = random.Random(RANDOM_SEED)
    start_date = date(2025, 1, 1)
    cases: list[TransactionCase] = []

    for case_number in range(1, CASE_COUNT + 1):
        scenario = SCENARIOS[(case_number - 1) % len(SCENARIOS)]
        invoice_date = start_date + timedelta(days=generator.randrange(365))
        invoice_amount = generator.randrange(500, 250_000, 50)
        gateway_fee = round(invoice_amount * 0.018) if scenario == "gateway_fee_deduction" else 0
        gateway_amount = invoice_amount
        bank_amount: int | None = invoice_amount - gateway_fee
        bank_settlement_date: date | None = invoice_date + timedelta(days=generator.choice((1, 2, 3)))

        if scenario == "settlement_timing_difference":
            bank_settlement_date = invoice_date + timedelta(days=generator.choice((7, 10, 14)))
        elif scenario == "partial_payment":
            gateway_amount = invoice_amount - generator.randrange(100, min(10_000, invoice_amount // 3), 50)
            bank_amount = gateway_amount
        elif scenario == "duplicate_transaction":
            bank_amount = invoice_amount
        elif scenario == "missing_bank_settlement":
            bank_amount = None
            bank_settlement_date = None
        elif scenario == "unexplained_discrepancy":
            bank_amount = invoice_amount - generator.randrange(100, min(10_000, invoice_amount // 3), 50)

        cases.append(
            TransactionCase(
                transaction_id=f"TXN-{case_number:06d}",
                invoice_date=invoice_date,
                invoice_amount=invoice_amount,
                scenario=scenario,
                gateway_amount=gateway_amount,
                gateway_fee=gateway_fee,
                bank_amount=bank_amount,
                bank_settlement_date=bank_settlement_date,
            )
        )

    return cases


def generate_dataset(output_directory: Path = OUTPUT_DIRECTORY) -> list[Path]:
    """Generate all benchmark CSV files and return their paths."""
    output_directory.mkdir(parents=True, exist_ok=True)
    cases = _build_cases()

    invoices = [
        {
            "transaction_id": case.transaction_id,
            "invoice_date": case.invoice_date.isoformat(),
            "amount_inr": case.invoice_amount,
            "currency": "INR",
        }
        for case in cases
    ]
    gateway_transactions: list[dict[str, object]] = []
    bank_settlements: list[dict[str, object]] = []
    ground_truth: list[dict[str, object]] = []

    for case in cases:
        gateway_row = {
            "transaction_id": case.transaction_id,
            "gateway_transaction_id": f"GW-{case.transaction_id[4:]}",
            "transaction_date": case.invoice_date.isoformat(),
            "amount_inr": case.gateway_amount,
            "fee_inr": case.gateway_fee,
            "currency": "INR",
        }
        gateway_transactions.append(gateway_row)
        if case.scenario == "duplicate_transaction":
            gateway_transactions.append({**gateway_row, "gateway_transaction_id": f"GW-DUP-{case.transaction_id[4:]}"})

        if case.bank_amount is not None and case.bank_settlement_date is not None:
            bank_settlements.append(
                {
                    "transaction_id": case.transaction_id,
                    "bank_settlement_id": f"BNK-{case.transaction_id[4:]}",
                    "settlement_date": case.bank_settlement_date.isoformat(),
                    "amount_inr": case.bank_amount,
                    "currency": "INR",
                }
            )

        ground_truth.append(
            {
                "transaction_id": case.transaction_id,
                "scenario": case.scenario,
                "expected_outcome": case.expected_outcome,
                "expected_invoice_amount_inr": case.invoice_amount,
                "expected_gateway_amount_inr": case.gateway_amount,
                "expected_bank_amount_inr": case.bank_amount or "",
                "expected_gateway_fee_inr": case.gateway_fee,
                "human_review_required": case.scenario in {
                    "partial_payment",
                    "duplicate_transaction",
                    "missing_bank_settlement",
                    "unexplained_discrepancy",
                },
            }
        )

    files = {
        "invoices.csv": (list(invoices[0]), invoices),
        "gateway_transactions.csv": (list(gateway_transactions[0]), gateway_transactions),
        "bank_settlements.csv": (list(bank_settlements[0]), bank_settlements),
        "ground_truth.csv": (list(ground_truth[0]), ground_truth),
    }
    paths: list[Path] = []
    for filename, (fieldnames, rows) in files.items():
        path = output_directory / filename
        _write_csv(path, fieldnames, rows)
        paths.append(path)
    return paths


def main() -> None:
    for path in generate_dataset():
        print(path)


if __name__ == "__main__":
    main()