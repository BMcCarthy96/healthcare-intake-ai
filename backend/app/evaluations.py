from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

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
    return {
        "dataset": dataset_name,
        "total_cases": len(results),
        "matched_cases": matched,
        "routing_accuracy": matched / len(results) if results else 0.0,
        "field_accuracy": fields_matched / fields_compared if fields_compared else 0.0,
        "results": results,
    }


def _run_case(payload: dict, gateway: ModelGateway) -> dict:
    """Run one dataset case through the same extraction and routing path as processing."""
    expected = payload["expected_status"]
    issues: list[str] = []
    fields_matched = 0
    fields_compared = 0
    try:
        pages = _ingest_pages(payload["documents"])
        result = gateway.extract(pages)
        _, route = validate_record(result.record, pages)
        actual = route.value
        fields_matched, fields_compared, mismatched = _score_fields(
            result.record, payload["ground_truth"]
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
        "expected_status": expected,
        "actual_status": actual,
        "matched": matched,
        "issue": "; ".join(issues) or None,
        "fields_matched": fields_matched,
        "fields_compared": fields_compared,
    }


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
    )
    session.add(evaluation)
    session.flush()
    for result in payload["results"]:
        session.add(EvalCaseResult(eval_run_id=evaluation.id, **result))
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
        "results": [
            {
                "case_id": result.case_id,
                "expected_status": result.expected_status,
                "actual_status": result.actual_status,
                "matched": result.matched,
                "issue": result.issue,
                "fields_matched": result.fields_matched,
                "fields_compared": result.fields_compared,
            }
            for result in results
        ],
    }
