from decimal import Decimal
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.reconciliation.models import ReconciliationResult, ReconciliationStatus
from evaluation.metrics import evaluate


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

    metrics = evaluate(results, ground_truth, reconciliation_path=tmp_path)

    assert metrics.total_cases == 4
    assert metrics.exact_status_accuracy == 0.75
    assert metrics.status_precision["AUTO_RESOLVED"] == 0.5
    assert metrics.false_auto_resolution_count == 1
    assert metrics.false_auto_resolution_rate == 0.5
    assert metrics.unresolved_case_count == 1
    assert metrics.scenario_accuracy["partial_payment"] == 0.0
    assert metrics.confusion_matrix["NEEDS_REVIEW"]["AUTO_RESOLVED"] == 1
    assert len(metrics.mismatches) == 1


def test_integrity_checks_detect_missing_and_duplicate_results(tmp_path: Path) -> None:
    results = [result("TXN-1", ReconciliationStatus.MATCHED), result("TXN-1", ReconciliationStatus.MATCHED)]
    metrics = evaluate(
        results,
        [truth("TXN-1", "exact_match", "matched"), truth("TXN-2", "exact_match", "matched")],
        reconciliation_path=tmp_path,
    )

    assert metrics.integrity_checks.missing_transaction_ids == ("TXN-2",)
    assert metrics.integrity_checks.duplicate_result_ids == ("TXN-1",)
    assert metrics.integrity_checks.passed is False