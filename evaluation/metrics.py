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
    ground_truth_access_detected: bool
    hardcoded_expected_results_detected: bool
    missing_transaction_ids: tuple[str, ...]
    duplicate_result_ids: tuple[str, ...]
    results_without_transaction_ids: int

    @property
    def passed(self) -> bool:
        return not any(
            (
                self.ground_truth_access_detected,
                self.hardcoded_expected_results_detected,
                self.missing_transaction_ids,
                self.duplicate_result_ids,
                self.results_without_transaction_ids,
            )
        )


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


def _integrity_checks(results: list[ReconciliationResult], reconciliation_path: Path, expected_ids: set[str]) -> IntegrityChecks:
    result_ids = [result.transaction_id for result in results]
    counts = Counter(result_ids)
    source_text = "\n".join(path.read_text(encoding="utf-8") for path in reconciliation_path.glob("*.py"))
    ground_truth_accessed = bool(re.search(r"ground[_ ]truth|expected_outcome", source_text, re.IGNORECASE))
    hardcoded_results = bool(re.search(r"TXN[-_]\d{3,}|expected_(?:status|scenario|outcome)", source_text, re.IGNORECASE))
    return IntegrityChecks(
        ground_truth_access_detected=ground_truth_accessed,
        hardcoded_expected_results_detected=hardcoded_results,
        missing_transaction_ids=tuple(sorted(expected_ids - set(result_ids))),
        duplicate_result_ids=tuple(sorted(transaction_id for transaction_id, count in counts.items() if transaction_id and count > 1)),
        results_without_transaction_ids=sum(not result.transaction_id for result in results),
    )


def evaluate(
    results: list[ReconciliationResult],
    ground_truth_rows: Iterable[Mapping[str, str]],
    *,
    reconciliation_path: Path,
) -> EvaluationMetrics:
    """Compare engine results with ground truth and calculate reproducible metrics."""
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
    integrity = _integrity_checks(results, reconciliation_path, set(truth_by_id))
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