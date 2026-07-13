from __future__ import annotations

import re
from datetime import UTC, datetime

import httpx
from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.documents import verify_evidence
from app.domain import CaseStatus, can_transition
from app.model_gateway import get_model_gateway
from app.models import (
    AuditEvent,
    Document,
    ExtractionResult,
    IntakeCase,
    ModelRun,
    ProcessingJob,
    ReviewDecision,
    ValidationIssue,
)
from app.schemas import IntakeRecord, ReviewRequest

REQUIRED_FIELDS = {
    "case_reference",
    "member_identifier",
    "requesting_organization",
    "requesting_contact",
    "service_code",
    "requested_start_date",
}


class WorkflowError(ValueError):
    pass


def now() -> datetime:
    return datetime.now(UTC)


def get_case_or_raise(session: Session, case_id: str) -> IntakeCase:
    case = session.get(IntakeCase, case_id)
    if case is None:
        raise WorkflowError("Intake case not found.")
    return case


def add_event(
    session: Session,
    case: IntakeCase,
    event_type: str,
    actor: str,
    correlation_id: str,
    details: dict | None = None,
) -> AuditEvent:
    event = AuditEvent(
        case_id=case.id,
        event_type=event_type,
        actor=actor,
        correlation_id=correlation_id,
        details=details,
    )
    session.add(event)
    return event


def transition_case(
    session: Session,
    case: IntakeCase,
    target: CaseStatus,
    actor: str,
    correlation_id: str,
    reason: str,
) -> None:
    current = CaseStatus(case.status)
    if not can_transition(current, target):
        raise WorkflowError(f"Case cannot transition from {current.value} to {target.value}.")
    case.status = target.value
    add_event(
        session,
        case,
        "case_status_changed",
        actor,
        correlation_id,
        {"from": current.value, "to": target.value, "reason": reason},
    )


def _latest_record(session: Session, case: IntakeCase) -> IntakeRecord | None:
    if not case.latest_extraction_id:
        return None
    result = session.get(ExtractionResult, case.latest_extraction_id)
    return IntakeRecord.model_validate(result.normalized_record) if result else None


def _list_case_documents(session: Session, case_id: str) -> list[Document]:
    return list(session.scalars(select(Document).where(Document.case_id == case_id).order_by(Document.created_at)))


def _find_replay_event(
    session: Session, case_id: str, event_type: str, key: str
) -> AuditEvent | None:
    events = session.scalars(
        select(AuditEvent).where(AuditEvent.case_id == case_id, AuditEvent.event_type == event_type)
    )
    for event in events:
        if event.details and event.details.get("idempotency_key") == key:
            return event
    return None


def request_processing(session: Session, case_id: str, idempotency_key: str, correlation_id: str) -> bool:
    case = get_case_or_raise(session, case_id)
    if _find_replay_event(session, case.id, "processing_requested", idempotency_key):
        return False
    current = CaseStatus(case.status)
    if current not in {CaseStatus.RECEIVED, CaseStatus.MISSING_INFORMATION, CaseStatus.FAILED}:
        raise WorkflowError(f"Case in {current.value} cannot be processed.")
    if not _list_case_documents(session, case.id):
        raise WorkflowError("Upload at least one PDF before processing.")
    transition_case(session, case, CaseStatus.QUEUED, "api", correlation_id, "processing requested")
    job = ProcessingJob(
        case_id=case.id,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
    )
    session.add(job)
    add_event(
        session,
        case,
        "processing_requested",
        "api",
        correlation_id,
        {"idempotency_key": idempotency_key},
    )
    session.commit()
    if get_settings().async_processing:
        from app.tasks import process_intake_job

        process_intake_job.send(case.id, correlation_id, job.id)
    else:
        process_case(session, case.id, correlation_id, job.id)
    return True


def process_case(session: Session, case_id: str, correlation_id: str, job_id: str) -> None:
    case = get_case_or_raise(session, case_id)
    job = session.get(ProcessingJob, job_id)
    if job is None:
        raise WorkflowError("Processing job not found.")
    if CaseStatus(case.status) != CaseStatus.QUEUED:
        raise WorkflowError("Only queued cases may start processing.")
    job.status = "running"
    transition_case(session, case, CaseStatus.PROCESSING, "worker", correlation_id, "document extraction started")
    session.commit()
    try:
        documents = _list_case_documents(session, case.id)
        pages: list[str] = []
        for document in documents:
            pages.extend((document.extracted_pages or {}).get("pages", []))
        result = get_model_gateway().extract(pages)
        model_run = ModelRun(
            case_id=case.id,
            provider=result.provider,
            model=result.model,
            route_tier=result.route_tier,
            prompt_version="v1",
            schema_version="v1",
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            duration_ms=result.duration_ms,
            status="success",
            raw_response=result.raw_response,
        )
        session.add(model_run)
        session.flush()
        issues, route = validate_record(result.record, pages)
        extraction = ExtractionResult(
            case_id=case.id,
            model_run_id=model_run.id,
            normalized_record=result.record.model_dump(mode="json"),
            validation_status="valid" if not issues else "issues_found",
        )
        session.add(extraction)
        session.flush()
        case.latest_extraction_id = extraction.id
        for issue in issues:
            session.add(
                ValidationIssue(
                    case_id=case.id,
                    code=issue["code"],
                    severity=issue["severity"],
                    field_name=issue.get("field_name"),
                    message=issue["message"],
                    evidence=issue.get("evidence"),
                )
            )
        transition_case(session, case, route, "workflow", correlation_id, "deterministic validation route")
        add_event(
            session,
            case,
            "extraction_completed",
            "worker",
            correlation_id,
            {"model_run_id": model_run.id, "issue_count": len(issues), "route": route.value},
        )
        job.status = "completed"
        job.completed_at = now()
        session.commit()
    except Exception as error:
        session.rollback()
        case = get_case_or_raise(session, case_id)
        job = session.get(ProcessingJob, job_id)
        if job:
            job.status = "failed"
            job.error_message = str(error)
            job.completed_at = now()
        if CaseStatus(case.status) == CaseStatus.PROCESSING:
            transition_case(session, case, CaseStatus.FAILED, "worker", correlation_id, "processing failure")
        session.add(
            ModelRun(
                case_id=case.id,
                provider="internal",
                model="workflow",
                route_tier="none",
                prompt_version="v1",
                schema_version="v1",
                status="error",
                error_message=str(error),
            )
        )
        add_event(session, case, "processing_failed", "worker", correlation_id, {"error": str(error)})
        session.commit()
        raise


def validate_record(record: IntakeRecord, page_texts: list[str]) -> tuple[list[dict], CaseStatus]:
    issues: list[dict] = []
    field_map = {field.name: field for field in record.fields}
    for field_name in REQUIRED_FIELDS:
        value = getattr(record, field_name)
        if not value:
            issues.append(
                {
                    "code": "missing_required_field",
                    "severity": "warning",
                    "field_name": field_name,
                    "message": f"Required administrative field '{field_name}' is missing.",
                }
            )
            continue
        extracted = field_map.get(field_name)
        if not extracted or not extracted.evidence:
            issues.append(
                {
                    "code": "missing_evidence",
                    "severity": "error",
                    "field_name": field_name,
                    "message": f"Field '{field_name}' has no page-level evidence.",
                }
            )
        elif not verify_evidence(page_texts, extracted.evidence.page_number, extracted.evidence.quote):
            issues.append(
                {
                    "code": "unsupported_evidence",
                    "severity": "error",
                    "field_name": field_name,
                    "message": f"Evidence for '{field_name}' does not match document text.",
                    "evidence": extracted.evidence.model_dump(),
                }
            )
    full_text = "\n".join(page_texts)
    if re.search(r"ignore (?:previous|all) instructions|system prompt|developer message", full_text, re.I):
        issues.append(
            {
                "code": "untrusted_instruction_detected",
                "severity": "error",
                "field_name": None,
                "message": "Document contains instruction-like text and requires human review.",
            }
        )
    values_by_label: dict[str, set[str]] = {}
    for label, value in re.findall(r"(?im)^(Member ID|Service Code|Case Reference):\s*(.+)$", full_text):
        values_by_label.setdefault(label.lower(), set()).add(value.strip())
    contradictions = {label: values for label, values in values_by_label.items() if len(values) > 1}
    if contradictions:
        issues.append(
            {
                "code": "contradictory_document_values",
                "severity": "error",
                "field_name": None,
                "message": "Document contains conflicting administrative values.",
                "evidence": {label: sorted(values) for label, values in contradictions.items()},
            }
        )
    if any(issue["code"] == "missing_required_field" for issue in issues):
        return issues, CaseStatus.MISSING_INFORMATION
    if issues:
        return issues, CaseStatus.REVIEW_REQUIRED
    return issues, CaseStatus.READY_FOR_EXPORT


def submit_review(
    session: Session, case_id: str, request: ReviewRequest, correlation_id: str
) -> IntakeCase:
    case = get_case_or_raise(session, case_id)
    current = CaseStatus(case.status)
    if current not in {CaseStatus.REVIEW_REQUIRED, CaseStatus.READY_FOR_EXPORT}:
        raise WorkflowError("Only reviewable cases may receive a reviewer decision.")
    record = _latest_record(session, case)
    if record is None:
        raise WorkflowError("No extracted record is available for review.")
    if request.corrections:
        updated = record.model_copy(update=request.corrections)
        latest = session.get(ExtractionResult, case.latest_extraction_id)
        if latest:
            latest.normalized_record = updated.model_dump(mode="json")
        record = updated
    if request.action == "request_information":
        target = CaseStatus.MISSING_INFORMATION
    else:
        missing = [field for field in REQUIRED_FIELDS if not getattr(record, field)]
        if missing:
            raise WorkflowError("Reviewer approval requires all required administrative fields.")
        target = CaseStatus.READY_FOR_EXPORT
    if current != target:
        transition_case(session, case, target, request.reviewer, correlation_id, request.action)
    session.add(
        ReviewDecision(
            case_id=case.id,
            action=request.action,
            reviewer=request.reviewer,
            reason=request.reason,
            corrections=request.corrections or None,
        )
    )
    add_event(
        session,
        case,
        "review_decision_recorded",
        request.reviewer,
        correlation_id,
        {"action": request.action, "corrected_fields": sorted(request.corrections)},
    )
    session.commit()
    session.refresh(case)
    return case


def submit_mock_export(case: IntakeCase) -> None:
    settings = get_settings()
    if not settings.mock_export_url:
        return
    try:
        response = httpx.post(
            settings.mock_export_url,
            json={"case_id": case.id, "external_reference": case.external_reference},
            headers={"X-Mock-Export-Mode": settings.mock_export_mode},
            timeout=1.0,
        )
    except httpx.TimeoutException as error:
        raise WorkflowError("Mock downstream export timed out.") from error
    except httpx.HTTPError as error:
        raise WorkflowError("Mock downstream export could not be reached.") from error
    if response.status_code == 429:
        raise WorkflowError("Mock downstream export is rate limited; retry with a new idempotency key.")
    if response.status_code >= 400:
        raise WorkflowError(f"Mock downstream export rejected the record ({response.status_code}).")


def export_case(session: Session, case_id: str, idempotency_key: str, correlation_id: str) -> bool:
    case = get_case_or_raise(session, case_id)
    if _find_replay_event(session, case.id, "export_requested", idempotency_key):
        return False
    if CaseStatus(case.status) != CaseStatus.READY_FOR_EXPORT:
        raise WorkflowError("Only reviewer-approved cases can be exported.")
    approval = session.scalar(
        select(ReviewDecision)
        .where(ReviewDecision.case_id == case.id, ReviewDecision.action.in_(["approve", "correct"]))
        .order_by(ReviewDecision.created_at.desc())
    )
    if approval is None:
        raise WorkflowError("A reviewer must approve or correct the record before export.")
    try:
        submit_mock_export(case)
    except WorkflowError as error:
        add_event(
            session,
            case,
            "export_failed",
            "mock-downstream",
            correlation_id,
            {"error": str(error)},
        )
        session.commit()
        raise
    add_event(
        session,
        case,
        "export_requested",
        "reviewer",
        correlation_id,
        {"idempotency_key": idempotency_key, "destination": "mock-downstream"},
    )
    transition_case(session, case, CaseStatus.COMPLETED, "mock-downstream", correlation_id, "mock export accepted")
    add_event(session, case, "export_completed", "mock-downstream", correlation_id, {"result": "accepted"})
    session.commit()
    return True


def case_query() -> Select[tuple[IntakeCase]]:
    return select(IntakeCase).order_by(IntakeCase.updated_at.desc(), IntakeCase.created_at.desc())
