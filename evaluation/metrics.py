"""Metrics and integrity checks for reconciliation evaluation."""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

from backend.app.reconciliation.models import ReconciliationResult, ReconciliationStatus

EXPECTED_OUTCOME_STATUS = {
    "matched": ReconciliationStatus.MATCHED.value,
    "matched_after_gateway_fee": ReconciliationStatus.AUTO_RESOLVED.value,
    "matched_after_timing_difference": ReconciliationStatus.AUTO_RESOLVED.value,
    "partial_payment": ReconciliationStatus.NEEDS_REVIEW.value,
    "duplicate_gateway_transaction": ReconciliationStatus.NEEDS_REVIEW.value,
    "missing_bank_settlement": ReconciliationStatus.NEEDS_REVIEW.value,
    "unexplained_discrepancy": ReconciliationStatus.UNRESOLVED.value,
}

SCENARIO_NAMES = {
    "exact_match": "exact_match",
    "gateway_fee_deduction": "gateway_fee",
    "settlement_timing_difference": "settlement_timing",
    "partial_payment": "partial_payment",
    "duplicate_transaction": "duplicate_transaction",
    "missing_bank_settlement": "missing_bank_settlement",
    "unexplained_discrepancy": "unexplained_discrepancy",
}

STATUS_NAMES = tuple(status.value for status in ReconciliationStatus)


@dataclass(frozen=True)
class CaseComparison:
    transaction_id: str
    scenario: str
    expected_status: str
    actual_status: str
    correct: bool


@dataclass(frozen=True)
class IntegrityChecks:
    expected_case_count: int
    actual_case_count: int
    ground_truth_access_detected: bool
    hardcoded_expected_results_detected: bool
    missing_transaction_ids: tuple[str, ...]
    unexpected_actual_ids: tuple[str, ...]
    duplicate_ground_truth_ids: tuple[str, ...]
    duplicate_result_ids: tuple[str, ...]
    ground_truth_ids_without_values: int
    results_without_transaction_ids: int

    @property
    def passed(self) -> bool:
        return not any(
            (
                self.ground_truth_access_detected,
                self.hardcoded_expected_results_detected,
                self.actual_case_count != self.expected_case_count,
                self.missing_transaction_ids,
                self.unexpected_actual_ids,
                self.duplicate_ground_truth_ids,
                self.duplicate_result_ids,
                self.ground_truth_ids_without_values,
                self.results_without_transaction_ids,
            )
        )


class EvaluationIntegrityError(ValueError):
    """Raised when evaluation inputs do not have one-to-one case identity."""

    def __init__(self, checks: IntegrityChecks) -> None:
        self.checks = checks
        failures = []
        if checks.expected_case_count != 500:
            failures.append(f"expected case count is {checks.expected_case_count}, not 500")
        if checks.actual_case_count != checks.expected_case_count:
            failures.append("actual and expected case counts differ")
        if checks.missing_transaction_ids:
            failures.append(f"missing actual IDs: {checks.missing_transaction_ids}")
        if checks.unexpected_actual_ids:
            failures.append(f"unexpected actual IDs: {checks.unexpected_actual_ids}")
        if checks.duplicate_ground_truth_ids:
            failures.append(f"duplicate ground-truth IDs: {checks.duplicate_ground_truth_ids}")
        if checks.duplicate_result_ids:
            failures.append(f"duplicate actual IDs: {checks.duplicate_result_ids}")
        if checks.ground_truth_ids_without_values:
            failures.append("ground-truth rows contain blank transaction IDs")
        if checks.results_without_transaction_ids:
            failures.append("actual results contain blank transaction IDs")
        super().__init__("Evaluation integrity check failed: " + "; ".join(failures))


@dataclass(frozen=True)
class EvaluationMetrics:
    total_cases: int
    exact_status_accuracy: float
    status_precision: dict[str, float]
    false_auto_resolution_count: int
    false_auto_resolution_rate: float
    unresolved_case_count: int
    scenario_accuracy: dict[str, float]
    confusion_matrix: dict[str, dict[str, int]]
    mismatches: tuple[dict[str, Any], ...]
    integrity_checks: IntegrityChecks


def _precision(comparisons: Iterable[CaseComparison], status: str) -> float:
    selected = [comparison for comparison in comparisons if comparison.actual_status == status]
    if not selected:
        return 0.0
    return sum(comparison.expected_status == status for comparison in selected) / len(selected)


def _confusion_matrix(comparisons: Iterable[CaseComparison]) -> dict[str, dict[str, int]]:
    matrix = {expected: {actual: 0 for actual in STATUS_NAMES} for expected in STATUS_NAMES}
    for comparison in comparisons:
        matrix[comparison.expected_status][comparison.actual_status] += 1
    return matrix


def _integrity_checks(
    results: list[ReconciliationResult],
    ground_truth_rows: list[Mapping[str, str]],
    reconciliation_path: Path,
) -> IntegrityChecks:
    result_ids = [result.transaction_id for result in results]
    expected_ids = [row.get("transaction_id", "").strip() for row in ground_truth_rows]
    result_counts = Counter(result_ids)
    expected_counts = Counter(expected_ids)
    expected_id_set = set(expected_ids) - {""}
    result_id_set = set(result_ids) - {""}
    source_text = "\n".join(path.read_text(encoding="utf-8") for path in reconciliation_path.glob("*.py"))
    ground_truth_accessed = bool(re.search(r"ground[_ ]truth|expected_outcome", source_text, re.IGNORECASE))
    hardcoded_results = bool(re.search(r"TXN[-_]\d{3,}|expected_(?:status|scenario|outcome)", source_text, re.IGNORECASE))
    return IntegrityChecks(
        expected_case_count=len(ground_truth_rows),
        actual_case_count=len(results),
        ground_truth_access_detected=ground_truth_accessed,
        hardcoded_expected_results_detected=hardcoded_results,
        missing_transaction_ids=tuple(sorted(expected_id_set - result_id_set)),
        unexpected_actual_ids=tuple(sorted(result_id_set - expected_id_set)),
        duplicate_ground_truth_ids=tuple(sorted(transaction_id for transaction_id, count in expected_counts.items() if transaction_id and count > 1)),
        duplicate_result_ids=tuple(sorted(transaction_id for transaction_id, count in result_counts.items() if transaction_id and count > 1)),
        ground_truth_ids_without_values=sum(not transaction_id for transaction_id in expected_ids),
        results_without_transaction_ids=sum(not result.transaction_id for result in results),
    )


def evaluate(
    results: list[ReconciliationResult],
    ground_truth_rows: Iterable[Mapping[str, str]],
    *,
    reconciliation_path: Path,
    expected_case_count: int = 500,
) -> EvaluationMetrics:
    """Compare engine results with ground truth and calculate reproducible metrics."""
    ground_truth_rows = list(ground_truth_rows)
    integrity = _integrity_checks(results, ground_truth_rows, reconciliation_path)
    if integrity.expected_case_count != expected_case_count:
        raise EvaluationIntegrityError(integrity)
    if not integrity.passed:
        raise EvaluationIntegrityError(integrity)

    truth_by_id = {row["transaction_id"]: row for row in ground_truth_rows}
    comparisons: list[CaseComparison] = []
    for result in results:
        truth = truth_by_id.get(result.transaction_id)
        if truth is None:
            continue
        expected_status = EXPECTED_OUTCOME_STATUS[truth["expected_outcome"]]
        comparisons.append(
            CaseComparison(
                transaction_id=result.transaction_id,
                scenario=SCENARIO_NAMES[truth["scenario"]],
                expected_status=expected_status,
                actual_status=result.status.value,
                correct=result.status.value == expected_status,
            )
        )

    total_cases = len(truth_by_id)
    auto_results = [comparison for comparison in comparisons if comparison.actual_status == ReconciliationStatus.AUTO_RESOLVED.value]
    false_auto_count = sum(comparison.expected_status != ReconciliationStatus.AUTO_RESOLVED.value for comparison in auto_results)
    by_scenario: dict[str, list[CaseComparison]] = defaultdict(list)
    for comparison in comparisons:
        by_scenario[comparison.scenario].append(comparison)
    scenario_accuracy = {
        scenario: sum(comparison.correct for comparison in scenario_comparisons) / len(scenario_comparisons)
        for scenario, scenario_comparisons in sorted(by_scenario.items())
        if scenario_comparisons
    }
    mismatches = tuple(asdict(comparison) for comparison in comparisons if not comparison.correct)
    return EvaluationMetrics(
        total_cases=total_cases,
        exact_status_accuracy=sum(comparison.correct for comparison in comparisons) / total_cases if total_cases else 0.0,
        status_precision={status: _precision(comparisons, status) for status in STATUS_NAMES},
        false_auto_resolution_count=false_auto_count,
        false_auto_resolution_rate=false_auto_count / len(auto_results) if auto_results else 0.0,
        unresolved_case_count=sum(result.status.value == ReconciliationStatus.UNRESOLVED.value for result in results),
        scenario_accuracy=scenario_accuracy,
        confusion_matrix=_confusion_matrix(comparisons),
        mismatches=mismatches,
        integrity_checks=integrity,
    )


def metrics_to_dict(metrics: EvaluationMetrics) -> dict[str, Any]:
    return asdict(metrics)