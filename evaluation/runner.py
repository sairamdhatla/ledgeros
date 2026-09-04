"""Run the LedgerOS reconciliation evaluation from the repository root."""

from __future__ import annotations

import csv
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPOSITORY_ROOT / "backend"
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.reconciliation.engine import reconcile_csv_files  # noqa: E402
from evaluation.metrics import evaluate  # noqa: E402
from evaluation.report import write_json, write_markdown  # noqa: E402


def _read_ground_truth(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as input_file:
        return list(csv.DictReader(input_file))


def run_evaluation(repository_root: Path = REPOSITORY_ROOT):
    generated = repository_root / "data" / "generated"
    results = reconcile_csv_files(
        generated / "invoices.csv",
        generated / "gateway_transactions.csv",
        generated / "bank_settlements.csv",
    )
    metrics = evaluate(
        results,
        _read_ground_truth(generated / "ground_truth.csv"),
        reconciliation_path=repository_root / "backend" / "app" / "reconciliation",
    )
    write_json(metrics, repository_root / "evaluation" / "results.json")
    write_markdown(metrics, repository_root / "evaluation" / "results.md")
    return metrics


if __name__ == "__main__":
    evaluation = run_evaluation()
    print(f"Total cases evaluated: {evaluation.total_cases}")
    print(f"Exact status accuracy: {evaluation.exact_status_accuracy:.2%}")
    print(f"False auto-resolution rate: {evaluation.false_auto_resolution_rate:.2%}")
    print(f"Scenario accuracy: {evaluation.scenario_accuracy}")