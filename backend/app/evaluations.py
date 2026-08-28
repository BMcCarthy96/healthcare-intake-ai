from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.documents import verify_evidence
from app.domain import CaseStatus
from app.model_gateway import ModelGateway, get_model_gateway
from app.models import EvalCaseResult, EvalRun
from app.schemas import IntakeRecord
from app.services import REQUIRED_FIELDS, validate_record


class IngestionRejection(ValueError):
    """Raised when a dataset case would be rejected at document upload time."""


def evaluate_dataset(dataset_name: str = "development") -> dict:
    root = Path(__file__).resolve().parents[2] / "evals" / "datasets" / dataset_name
    cases = sorted(root.glob("*.json"))
    gateway = get_model_gateway()
    results = [
        _run_case(json.loads(path.read_text(encoding="utf-8")), gateway) for path in cases
    ]
    matched = sum(1 for result in results if result["matched"])
    fields_matched = sum(result["fields_matched"] for result in results)
    fields_compared = sum(result["fields_compared"] for result in results)
    routing_macro_f1 = _macro_f1(
        [result["expected_status"] for result in results],
        [result["actual_status"] for result in results],
    )
    field_macro_f1 = _field_macro_f1(results)
    false_ready_count = sum(
        1
        for result in results
        if result["actual_status"] == CaseStatus.READY_FOR_EXPORT.value
        and result["expected_status"] != CaseStatus.READY_FOR_EXPORT.value
    )
    evidence_validity = (
        sum(1 for result in results if result["evidence_valid"]) / len(results) if results else 0.0
    )
    category_metrics: dict[str, dict[str, float]] = {}
    for category in sorted({result["category"] for result in results}):
        subset = [result for result in results if result["category"] == category]
        category_metrics[category] = {
            "cases": float(len(subset)),
            "routing_accuracy": sum(1 for result in subset if result["matched"]) / len(subset),
            "field_accuracy": sum(result["fields_matched"] for result in subset)
            / max(1, sum(result["fields_compared"] for result in subset)),
            "false_ready_count": float(
                sum(
                    1
                    for result in subset
                    if result["actual_status"] == CaseStatus.READY_FOR_EXPORT.value
                    and result["expected_status"] != CaseStatus.READY_FOR_EXPORT.value
                )
            ),
        }
    return {
        "dataset": dataset_name,
        "total_cases": len(results),
        "matched_cases": matched,
        "routing_accuracy": matched / len(results) if results else 0.0,
        "field_accuracy": fields_matched / fields_compared if fields_compared else 0.0,
        "routing_macro_f1": routing_macro_f1,
        "field_macro_f1": field_macro_f1,
        "false_ready_count": false_ready_count,
        "evidence_validity": evidence_validity,
        "category_metrics": category_metrics,
        "results": results,
    }


def _run_case(payload: dict, gateway: ModelGateway) -> dict:
    """Run one dataset case through the same extraction and routing path as processing."""
    expected = payload["expected_status"]
    issues: list[str] = []
    fields_matched = 0
    fields_compared = 0
    mismatched: list[str] = []
    evidence_valid = True
    # Ingestion failures have no extraction fields to score. They still count
    # toward routing and false-ready metrics, but are excluded from field F1.
    field_values: dict[str, dict[str, str]] = {}
    try:
        pages = _ingest_pages(payload["documents"])
        result = gateway.extract(pages)
        _, route = validate_record(result.record, pages)
        actual = route.value
        fields_matched, fields_compared, mismatched = _score_fields(
            result.record, payload["ground_truth"]
        )
        field_values = {
            field_name: {
                "expected": (payload["ground_truth"].get(field_name) or "").strip(),
                "actual": (getattr(result.record, field_name, None) or "").strip(),
            }
            for field_name in sorted(REQUIRED_FIELDS)
        }
        evidence_valid = all(
            verify_evidence(pages, field.evidence.page_number, field.evidence.quote)
            for field in result.record.fields
            if field.evidence
        )
        if mismatched:
            issues.append(f"field mismatch: {', '.join(mismatched)}")
    except IngestionRejection as rejection:
        actual = CaseStatus.FAILED.value
        issues.append(str(rejection))
    except Exception as error:  # Mirrors process_case: unexpected errors fail the case.
        actual = CaseStatus.FAILED.value
        issues.append(f"processing error: {error}")
    matched = expected == actual
    if not matched:
        issues.insert(0, "routing mismatch")
    return {
        "case_id": payload["id"],
        "category": payload.get("category", "unknown"),
        "expected_status": expected,
        "actual_status": actual,
        "matched": matched,
        "issue": "; ".join(issues) or None,
        "fields_matched": fields_matched,
        "fields_compared": fields_compared,
        "evidence_valid": evidence_valid,
        "field_mismatches": mismatched,
        "field_values": field_values,
    }


def _macro_f1(expected: list[str], actual: list[str]) -> float:
    labels = sorted(set(expected) | set(actual))
    if not labels:
        return 0.0
    scores: list[float] = []
    for label in labels:
        true_positive = sum(1 for exp, got in zip(expected, actual, strict=True) if exp == label and got == label)
        false_positive = sum(1 for exp, got in zip(expected, actual, strict=True) if exp != label and got == label)
        false_negative = sum(1 for exp, got in zip(expected, actual, strict=True) if exp == label and got != label)
        precision = true_positive / (true_positive + false_positive) if true_positive + false_positive else 0.0
        recall = true_positive / (true_positive + false_negative) if true_positive + false_negative else 0.0
        scores.append(2 * precision * recall / (precision + recall) if precision + recall else 0.0)
    return sum(scores) / len(scores)


def _field_macro_f1(results: list[dict]) -> float:
    """Calculate exact-value F1 independently for each required field.

    A missing expected value is a negative example; a differing non-empty value
    counts as both a false positive and false negative. This keeps the proof
    metric honest instead of relabeling a micro-accuracy ratio as macro-F1.
    """
    counts = {
        field_name: {"tp": 0, "fp": 0, "fn": 0}
        for field_name in sorted(REQUIRED_FIELDS)
    }
    for result in results:
        for field_name, values in result.get("field_values", {}).items():
            expected = values.get("expected")
            actual = values.get("actual")
            if expected and actual and expected == actual:
                counts[field_name]["tp"] += 1
            elif expected and actual:
                counts[field_name]["fp"] += 1
                counts[field_name]["fn"] += 1
            elif expected:
                counts[field_name]["fn"] += 1
            elif actual:
                counts[field_name]["fp"] += 1
    scores: list[float] = []
    for field_counts in counts.values():
        tp, fp, fn = field_counts["tp"], field_counts["fp"], field_counts["fn"]
        scores.append(2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else 1.0)
    return sum(scores) / len(scores) if scores else 0.0


def _ingest_pages(documents: list[dict]) -> list[str]:
    # Mirrors the upload-time ingestion contract (app.documents / app.main): a PDF with no
    # extractable text is rejected, and identical content on one case is a duplicate conflict.
    # These deterministic checks run before any model call, exactly as in the live API.
    seen_content: set[str] = set()
    pages: list[str] = []
    for document in documents:
        document_pages = [str(page) for page in document.get("pages", [])]
        if not document_pages or not any(page.strip() for page in document_pages):
            raise IngestionRejection("document has no extractable text")
        content = "\n".join(document_pages)
        if content in seen_content:
            raise IngestionRejection("duplicate document content")
        seen_content.add(content)
        pages.extend(document_pages)
    return pages


def _score_fields(record: IntakeRecord, ground_truth: dict) -> tuple[int, int, list[str]]:
    mismatched: list[str] = []
    for field_name in sorted(REQUIRED_FIELDS):
        expected_value = (ground_truth.get(field_name) or "").strip()
        actual_value = (getattr(record, field_name) or "").strip()
        if expected_value != actual_value:
            mismatched.append(field_name)
    compared = len(REQUIRED_FIELDS)
    return compared - len(mismatched), compared, mismatched


def run_and_persist_evaluation(session: Session, dataset_name: str) -> EvalRun:
    payload = evaluate_dataset(dataset_name)
    evaluation = EvalRun(
        dataset=payload["dataset"],
        total_cases=payload["total_cases"],
        matched_cases=payload["matched_cases"],
        routing_accuracy=payload["routing_accuracy"],
        field_accuracy=payload["field_accuracy"],
        routing_macro_f1=payload["routing_macro_f1"],
        field_macro_f1=payload["field_macro_f1"],
        false_ready_count=payload["false_ready_count"],
        evidence_validity=payload["evidence_validity"],
        category_metrics=payload["category_metrics"],
    )
    session.add(evaluation)
    session.flush()
    for result in payload["results"]:
        session.add(
            EvalCaseResult(
                eval_run_id=evaluation.id,
                case_id=result["case_id"],
                category=result.get("category", "unknown"),
                expected_status=result["expected_status"],
                actual_status=result["actual_status"],
                matched=result["matched"],
                issue=result["issue"],
                fields_matched=result["fields_matched"],
                fields_compared=result["fields_compared"],
                evidence_valid=result.get("evidence_valid", False),
            )
        )
    session.commit()
    session.refresh(evaluation)
    return evaluation


def get_evaluation_payload(session: Session, evaluation: EvalRun) -> dict:
    results = list(
        session.scalars(
            select(EvalCaseResult)
            .where(EvalCaseResult.eval_run_id == evaluation.id)
            .order_by(EvalCaseResult.case_id)
        )
    )
    return {
        "id": evaluation.id,
        "dataset": evaluation.dataset,
        "total_cases": evaluation.total_cases,
        "matched_cases": evaluation.matched_cases,
        "routing_accuracy": evaluation.routing_accuracy,
        "field_accuracy": evaluation.field_accuracy,
        "routing_macro_f1": evaluation.routing_macro_f1,
        "field_macro_f1": evaluation.field_macro_f1,
        "false_ready_count": evaluation.false_ready_count,
        "evidence_validity": evaluation.evidence_validity,
        "category_metrics": evaluation.category_metrics or {},
        "results": [
            {
                "case_id": result.case_id,
                "category": result.category,
                "expected_status": result.expected_status,
                "actual_status": result.actual_status,
                "matched": result.matched,
                "issue": result.issue,
                "fields_matched": result.fields_matched,
                "fields_compared": result.fields_compared,
                "evidence_valid": result.evidence_valid,
            }
            for result in results
        ],
    }
