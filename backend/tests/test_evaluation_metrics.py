from decimal import Decimal
import csv
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.reconciliation.models import ReconciliationResult, ReconciliationStatus
from app.reconciliation.engine import reconcile_csv_files
from evaluation.metrics import EvaluationIntegrityError, evaluate


def result(transaction_id: str, status: ReconciliationStatus) -> ReconciliationResult:
    return ReconciliationResult(
        transaction_id=transaction_id,
        status=status,
        invoice_amount=Decimal("100"),
        gateway_amount=Decimal("100"),
        gateway_fee=Decimal("0"),
        expected_settlement=Decimal("100"),
        actual_settlement=Decimal("100"),
        variance=Decimal("0"),
        rule_applied="TEST",
        evidence_ids=(transaction_id,),
        confidence="HIGH",
        requires_review=status in {ReconciliationStatus.NEEDS_REVIEW, ReconciliationStatus.UNRESOLVED},
        explanation="controlled test result",
    )


def truth(transaction_id: str, scenario: str, outcome: str) -> dict[str, str]:
    return {"transaction_id": transaction_id, "scenario": scenario, "expected_outcome": outcome}


def test_metrics_calculate_precision_confusion_and_scenario_accuracy(tmp_path: Path) -> None:
    results = [
        result("TXN-1", ReconciliationStatus.MATCHED),
        result("TXN-2", ReconciliationStatus.AUTO_RESOLVED),
        result("TXN-3", ReconciliationStatus.AUTO_RESOLVED),
        result("TXN-4", ReconciliationStatus.UNRESOLVED),
    ]
    ground_truth = [
        truth("TXN-1", "exact_match", "matched"),
        truth("TXN-2", "gateway_fee_deduction", "matched_after_gateway_fee"),
        truth("TXN-3", "partial_payment", "partial_payment"),
        truth("TXN-4", "unexplained_discrepancy", "unexplained_discrepancy"),
    ]

    metrics = evaluate(results, ground_truth, reconciliation_path=tmp_path, expected_case_count=4)

    assert metrics.total_cases == 4
    assert metrics.exact_status_accuracy == 0.75
    assert metrics.status_precision["AUTO_RESOLVED"] == 0.5
    assert metrics.false_auto_resolution_count == 1
    assert metrics.false_auto_resolution_rate == 0.5
    assert metrics.unresolved_case_count == 1
    assert metrics.scenario_accuracy["partial_payment"] == 0.0
    assert metrics.confusion_matrix["NEEDS_REVIEW"]["AUTO_RESOLVED"] == 1
    assert len(metrics.mismatches) == 1


def valid_truth() -> list[dict[str, str]]:
    return [truth(f"TXN-{index}", "exact_match", "matched") for index in range(1, 4)]


@pytest.mark.parametrize(
    ("case_name", "actual_results", "ground_truth_rows", "expected_message"),
    [
        ("missing actual", [result("TXN-1", ReconciliationStatus.MATCHED), result("TXN-2", ReconciliationStatus.MATCHED)], valid_truth(), "missing actual IDs"),
        ("extra actual", [result(f"TXN-{index}", ReconciliationStatus.MATCHED) for index in range(1, 4)] + [result("TXN-EXTRA", ReconciliationStatus.MATCHED)], valid_truth(), "unexpected actual IDs"),
        ("duplicate actual", [result("TXN-1", ReconciliationStatus.MATCHED), result("TXN-1", ReconciliationStatus.MATCHED), result("TXN-2", ReconciliationStatus.MATCHED), result("TXN-3", ReconciliationStatus.MATCHED)], valid_truth(), "duplicate actual IDs"),
        ("duplicate ground truth", [result(f"TXN-{index}", ReconciliationStatus.MATCHED) for index in range(1, 4)], valid_truth() + [truth("TXN-1", "exact_match", "matched")], "duplicate ground-truth IDs"),
        ("mismatched ID", [result("TXN-1", ReconciliationStatus.MATCHED), result("TXN-2", ReconciliationStatus.MATCHED), result("TXN-WRONG", ReconciliationStatus.MATCHED)], valid_truth(), "missing actual IDs"),
    ],
)
def test_integrity_failures_are_loud(
    case_name: str,
    actual_results: list[ReconciliationResult],
    ground_truth_rows: list[dict[str, str]],
    expected_message: str,
    tmp_path: Path,
) -> None:
    del case_name
    with pytest.raises(EvaluationIntegrityError, match=expected_message):
        evaluate(actual_results, ground_truth_rows, reconciliation_path=tmp_path, expected_case_count=len(ground_truth_rows))


def test_valid_small_dataset_calculates_only_after_integrity_passes(tmp_path: Path) -> None:
    metrics = evaluate(
        [result(f"TXN-{index}", ReconciliationStatus.MATCHED) for index in range(1, 4)],
        valid_truth(),
        reconciliation_path=tmp_path,
        expected_case_count=3,
    )
    assert metrics.exact_status_accuracy == 1.0
    assert metrics.integrity_checks.passed is True


def test_valid_generated_dataset_has_exactly_500_cases(tmp_path: Path) -> None:
    repository_root = Path(__file__).resolve().parents[2]
    generated = repository_root / "data" / "generated"
    with (generated / "ground_truth.csv").open(newline="", encoding="utf-8") as input_file:
        ground_truth_rows = list(csv.DictReader(input_file))
    results = reconcile_csv_files(
        generated / "invoices.csv",
        generated / "gateway_transactions.csv",
        generated / "bank_settlements.csv",
    )

    metrics = evaluate(results, ground_truth_rows, reconciliation_path=repository_root / "backend" / "app" / "reconciliation")

    assert metrics.total_cases == 500
    assert metrics.integrity_checks.passed is True