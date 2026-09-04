import csv
from pathlib import Path

from app.utils.generate_data import generate_dataset


def _read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as input_file:
        return list(csv.DictReader(input_file))


def test_generate_dataset_creates_four_reproducible_csv_files(tmp_path: Path) -> None:
    first_paths = generate_dataset(tmp_path)
    first_contents = {path.name: path.read_bytes() for path in first_paths}

    second_paths = generate_dataset(tmp_path)
    second_contents = {path.name: path.read_bytes() for path in second_paths}

    assert {path.name for path in first_paths} == {
        "invoices.csv",
        "gateway_transactions.csv",
        "bank_settlements.csv",
        "ground_truth.csv",
    }
    assert first_contents == second_contents


def test_ground_truth_has_500_cases_and_all_scenarios(tmp_path: Path) -> None:
    generate_dataset(tmp_path)

    ground_truth = _read_rows(tmp_path / "ground_truth.csv")
    invoices = _read_rows(tmp_path / "invoices.csv")
    gateway_transactions = _read_rows(tmp_path / "gateway_transactions.csv")
    bank_settlements = _read_rows(tmp_path / "bank_settlements.csv")

    assert len(ground_truth) == 500
    assert len(invoices) == 500
    assert len(gateway_transactions) > 500
    assert len(bank_settlements) < 500
    assert {row["scenario"] for row in ground_truth} == {
        "exact_match",
        "gateway_fee_deduction",
        "settlement_timing_difference",
        "partial_payment",
        "duplicate_transaction",
        "missing_bank_settlement",
        "unexplained_discrepancy",
    }
    assert len({row["transaction_id"] for row in ground_truth}) == 500
    assert all(row["expected_outcome"] for row in ground_truth)