from __future__ import annotations

import hashlib
import hmac
import json
import re
from datetime import UTC, datetime

import httpx
from sqlalchemy import Select, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.documents import evidence_boxes, verify_evidence
from app.domain import CaseStatus, can_transition
from app.model_gateway import get_model_gateway
from app.models import (
    AuditEvent,
    Document,
    ExportAttempt,
    ExportAttemptRecord,
    ExtractionResult,
    IntakeCase,
    ModelRun,
    ProcessingJob,
    ReviewDecision,
    ValidationIssue,
)
from app.schemas import Evidence, ExtractedField, IntakeRecord, ReviewRequest

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


class ExportWorkflowError(WorkflowError):
    """An export failure with an explicit retry classification."""

    def __init__(self, message: str, *, retryable: bool, response_status: int | None = None) -> None:
        super().__init__(message)
        self.retryable = retryable
        self.response_status = response_status


def now() -> datetime:
    return datetime.now(UTC)


def get_case_or_raise(
    session: Session,
    case_id: str,
    workspace_id: str | None = None,
    *,
    for_update: bool = False,
) -> IntakeCase:
    statement = select(IntakeCase).where(IntakeCase.id == case_id)
    if workspace_id is not None:
        statement = statement.where(IntakeCase.workspace_id == workspace_id)
    case = session.scalar(statement.with_for_update() if for_update else statement)
    # Workspace-owned cases must never become addressable through the legacy
    # unauthenticated local routes. Global local cases remain available for
    # development and backwards-compatible API clients.
    if case is not None and workspace_id is None and case.workspace_id is not None:
        raise WorkflowError("A valid demo session is required for this case.")
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


def _document_page_context(documents: list[Document]) -> tuple[list[str], list[dict]]:
    """Flatten packet pages while preserving each document's local page identity."""
    pages: list[str] = []
    page_metadata: list[dict] = []
    for document in documents:
        pages.extend((document.extracted_pages or {}).get("pages", []))
        for metadata in (document.extracted_pages or {}).get("page_metadata", []):
            page_metadata.append({**metadata, "document_id": document.id})
    return pages, page_metadata


def _find_processing_job(session: Session, case_id: str, key: str) -> ProcessingJob | None:
    statement = select(ProcessingJob).where(
        ProcessingJob.case_id == case_id, ProcessingJob.idempotency_key == key
    )
    return session.scalar(statement.with_for_update())


def request_processing(
    session: Session,
    case_id: str,
    idempotency_key: str,
    correlation_id: str,
    workspace_id: str | None = None,
) -> bool:
    case = get_case_or_raise(session, case_id, workspace_id, for_update=True)
    replay = _find_processing_job(session, case.id, idempotency_key)
    if replay:
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
        stage="queued",
        progress=0,
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
    try:
        session.commit()
    except IntegrityError:
        # A concurrent request may have won the unique (case, idempotency_key) race.
        # Return the persisted job as a replay instead of leaking a 500 to the client.
        session.rollback()
        if _find_processing_job(session, case.id, idempotency_key):
            return False
        raise
    if get_settings().async_processing:
        from app.tasks import process_intake_job

        process_intake_job.send(case.id, correlation_id, job.id)
    else:
        process_case(session, case.id, correlation_id, job.id, workspace_id)
    return True


def process_case(
    session: Session,
    case_id: str,
    correlation_id: str,
    job_id: str,
    workspace_id: str | None = None,
) -> None:
    case = get_case_or_raise(session, case_id, workspace_id, for_update=True)
    job = session.get(ProcessingJob, job_id)
    if job is None:
        raise WorkflowError("Processing job not found.")
    if CaseStatus(case.status) != CaseStatus.QUEUED:
        raise WorkflowError("Only queued cases may start processing.")
    job.status = "running"
    job.stage = "extracting"
    job.progress = 20
    transition_case(session, case, CaseStatus.PROCESSING, "worker", correlation_id, "document extraction started")
    session.commit()
    try:
        documents = _list_case_documents(session, case.id)
        pages, page_metadata = _document_page_context(documents)
        job.stage = "validating"
        job.progress = 70
        result = get_model_gateway().extract(pages)
        result_record = _enrich_evidence(result.record, page_metadata, pages)
        model_run = ModelRun(
            case_id=case.id,
            provider=result.provider,
            model=result.model,
            route_tier=result.route_tier,
            prompt_version="v1",
            schema_version="intake-record/2",
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            duration_ms=result.duration_ms,
            status="success",
            raw_response=result_record.model_dump(mode="json"),
        )
        session.add(model_run)
        session.flush()
        issues, route = validate_record(result_record, pages, page_metadata)
        previous = session.scalar(
            select(ExtractionResult).where(
                ExtractionResult.case_id == case.id, ExtractionResult.is_current.is_(True)
            )
        )
        if previous:
            previous.is_current = False
        extraction = ExtractionResult(
            case_id=case.id,
            model_run_id=model_run.id,
            normalized_record=result_record.model_dump(mode="json"),
            validation_status="valid" if not issues else "issues_found",
            version=(previous.version + 1) if previous else 1,
            is_current=True,
        )
        session.add(extraction)
        session.flush()
        case.latest_extraction_id = extraction.id
        for issue in issues:
            session.add(
                ValidationIssue(
                    case_id=case.id,
                    extraction_id=extraction.id,
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
        job.stage = "completed"
        job.progress = 100
        job.completed_at = now()
        session.commit()
    except Exception as error:
        session.rollback()
        case = get_case_or_raise(session, case_id, workspace_id, for_update=True)
        job = session.get(ProcessingJob, job_id)
        if job:
            job.status = "failed"
            job.stage = "failed"
            job.progress = 100
            job.failure_classification = "provider_or_workflow_error"
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
                schema_version="intake-record/2",
                status="error",
                error_message=str(error),
            )
        )
        add_event(session, case, "processing_failed", "worker", correlation_id, {"error": str(error)})
        session.commit()
        raise


def _enrich_evidence(record: IntakeRecord, page_metadata: list[dict], page_texts: list[str]) -> IntakeRecord:
    fields = []
    for field in record.fields:
        if field.evidence is None:
            fields.append(field)
            continue
        metadata = page_metadata[field.evidence.page_number - 1] if 0 < field.evidence.page_number <= len(page_metadata) else {}
        packet_page_number = field.evidence.page_number
        page_number = int(metadata.get("page_number", packet_page_number))
        page_text = (
            page_texts[packet_page_number - 1]
            if 0 < packet_page_number <= len(page_texts)
            else ""
        )
        start_char = page_text.find(field.evidence.quote)
        enriched = field.evidence.model_copy(
            update={
                "document_id": metadata.get("document_id"),
                "page_number": page_number,
                "boxes": evidence_boxes(
                    page_metadata, packet_page_number, field.evidence.quote
                ),
                "source_mode": metadata.get("source_mode", "native"),
                "source_confidence": metadata.get("source_confidence"),
                "start_char": start_char if start_char >= 0 else None,
                "end_char": (start_char + len(field.evidence.quote)) if start_char >= 0 else None,
            }
        )
        fields.append(field.model_copy(update={"evidence": enriched}))
    return record.model_copy(update={"fields": fields})


def _packet_page_number(evidence: Evidence, page_metadata: list[dict] | None) -> int:
    if evidence.document_id and page_metadata:
        for index, metadata in enumerate(page_metadata, start=1):
            if (
                metadata.get("document_id") == evidence.document_id
                and int(metadata.get("page_number", index)) == evidence.page_number
            ):
                return index
    return evidence.page_number


def _ground_reviewer_value(
    value: str | None, page_texts: list[str], page_metadata: list[dict]
) -> Evidence | None:
    """Ground a reviewer value only when it exactly appears in the source packet."""
    if not value:
        return None
    for packet_page_number, page_text in enumerate(page_texts, start=1):
        for line in page_text.splitlines():
            quote = line.strip()
            if value.casefold() not in quote.casefold():
                continue
            if packet_page_number > len(page_metadata):
                continue
            metadata = page_metadata[packet_page_number - 1]
            start_char = page_text.find(quote)
            return Evidence(
                document_id=metadata.get("document_id"),
                page_number=int(metadata.get("page_number", packet_page_number)),
                quote=quote[:500],
                confidence=1.0,
                provenance="reviewer",
                start_char=start_char if start_char >= 0 else None,
                end_char=(start_char + len(quote)) if start_char >= 0 else None,
                boxes=evidence_boxes(page_metadata, packet_page_number, quote),
                source_mode=metadata.get("source_mode", "native"),
                source_confidence=metadata.get("source_confidence"),
            )
    return None


def _apply_reviewer_corrections(
    record: IntakeRecord,
    corrections: dict[str, str | None],
    page_texts: list[str],
    page_metadata: list[dict],
) -> IntakeRecord:
    fields_by_name = {field.name: field for field in record.fields}
    for name, value in corrections.items():
        fields_by_name[name] = ExtractedField(
            name=name,
            value=value,
            evidence=_ground_reviewer_value(value, page_texts, page_metadata),
        )
    return record.model_copy(
        update={
            **corrections,
            "fields": list(fields_by_name.values()),
        }
    )


def validate_record(record: IntakeRecord, page_texts: list[str], page_metadata: list[dict] | None = None) -> tuple[list[dict], CaseStatus]:
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
        elif not verify_evidence(
            page_texts,
            _packet_page_number(extracted.evidence, page_metadata),
            extracted.evidence.quote,
        ):
            issues.append(
                {
                    "code": "unsupported_evidence",
                    "severity": "error",
                    "field_name": field_name,
                    "message": f"Evidence for '{field_name}' does not match document text.",
                    "evidence": extracted.evidence.model_dump(),
                }
            )
        elif extracted.evidence.source_mode == "ocr" and (extracted.evidence.source_confidence or 0.0) < 0.75:
            issues.append(
                {
                    "code": "low_confidence_ocr",
                    "severity": "warning",
                    "field_name": field_name,
                    "message": f"OCR confidence for '{field_name}' is below the review threshold.",
                    "evidence": extracted.evidence.model_dump(),
                }
            )
    date_fields = {"requested_start_date": record.requested_start_date, "requested_service_date": record.requested_service_date}
    for field_name, value in date_fields.items():
        if value and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            issues.append(
                {
                    "code": "invalid_date_format",
                    "severity": "error",
                    "field_name": field_name,
                    "message": f"{field_name} must use YYYY-MM-DD format.",
                }
            )
    if record.provider_npi and not re.fullmatch(r"\d{10}", record.provider_npi):
        issues.append(
            {
                "code": "invalid_provider_npi",
                "severity": "error",
                "field_name": "provider_npi",
                "message": "Provider NPI must contain exactly 10 digits.",
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
    session: Session, case_id: str, request: ReviewRequest, correlation_id: str,
    workspace_id: str | None = None,
) -> IntakeCase:
    case = get_case_or_raise(session, case_id, workspace_id, for_update=True)
    current = CaseStatus(case.status)
    if current not in {CaseStatus.REVIEW_REQUIRED, CaseStatus.READY_FOR_EXPORT}:
        raise WorkflowError("Only reviewable cases may receive a reviewer decision.")
    latest_extraction = session.get(ExtractionResult, case.latest_extraction_id) if case.latest_extraction_id else None
    if latest_extraction is None or request.extraction_id != latest_extraction.id:
        raise WorkflowError("This review is stale; reload the latest extraction before deciding.")
    record = IntakeRecord.model_validate(latest_extraction.normalized_record) if latest_extraction else None
    if record is None:
        raise WorkflowError("No extracted record is available for review.")
    if request.action == "correct":
        pages, page_metadata = _document_page_context(_list_case_documents(session, case.id))
        updated = _apply_reviewer_corrections(
            record, request.corrections, pages, page_metadata
        )
        if latest_extraction:
            latest_extraction.is_current = False
            replacement = ExtractionResult(
                case_id=case.id,
                model_run_id=latest_extraction.model_run_id,
                normalized_record=updated.model_dump(mode="json"),
                validation_status="reviewer_corrected",
                version=latest_extraction.version + 1,
                is_current=True,
            )
            session.add(replacement)
            session.flush()
            case.latest_extraction_id = replacement.id
            latest_extraction = replacement
        record = updated
    if request.action == "request_information":
        target = CaseStatus.MISSING_INFORMATION
    else:
        for field_name in ("requested_start_date", "requested_service_date"):
            value = getattr(record, field_name)
            if value and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
                raise WorkflowError(f"Reviewer correction for {field_name} must use YYYY-MM-DD format.")
        if record.provider_npi and not re.fullmatch(r"\d{10}", record.provider_npi):
            raise WorkflowError("Reviewer correction for provider_npi must contain exactly 10 digits.")
        missing = [field for field in REQUIRED_FIELDS if not getattr(record, field)]
        if missing:
            raise WorkflowError("Reviewer approval requires all required administrative fields.")
        unresolved_errors = list(
            session.scalars(
                select(ValidationIssue).where(
                    ValidationIssue.case_id == case.id,
                    ValidationIssue.resolved_at.is_(None),
                    ValidationIssue.severity == "error",
                )
            )
        )
        if request.action == "approve" and unresolved_errors and not request.reason:
            raise WorkflowError(
                "Approving a case with error findings requires reviewer rationale."
            )
        target = CaseStatus.READY_FOR_EXPORT
        for issue in session.scalars(
            select(ValidationIssue).where(
                ValidationIssue.case_id == case.id,
                ValidationIssue.resolved_at.is_(None),
            )
        ):
            issue.resolved_at = now()
    if current != target:
        transition_case(session, case, target, request.reviewer, correlation_id, request.action)
    session.add(
        ReviewDecision(
            case_id=case.id,
            extraction_id=latest_extraction.id if latest_extraction else None,
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
        {
            "action": request.action,
            "corrected_fields": sorted(request.corrections),
            "grounded_fields": sorted(
                field.name
                for field in record.fields
                if field.name in request.corrections and field.evidence is not None
            ),
        },
    )
    session.commit()
    session.refresh(case)
    return case


def _export_signature(payload: dict) -> str:
    settings = get_settings()
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hmac.new(settings.downstream_hmac_secret.encode(), canonical, hashlib.sha256).hexdigest()


def submit_mock_export(
    case: IntakeCase,
    idempotency_key: str,
    payload: dict,
    *,
    request_signature: str,
    correlation_id: str,
    force_rate_limit: bool = False,
) -> tuple[int | None, dict | None]:
    settings = get_settings()
    if force_rate_limit:
        raise ExportWorkflowError(
            "Mock downstream export is rate limited; retry with the same idempotency key.",
            retryable=True,
            response_status=429,
        )
    if not settings.mock_export_url:
        record_id = hashlib.sha256(idempotency_key.encode()).hexdigest()[:12]
        return 202, {
            "accepted": True,
            "duplicate": False,
            "mode": "local-noop",
            "record_id": f"downstream-{record_id}",
            "signature_valid": True,
        }
    try:
        response = httpx.post(
            settings.mock_export_url,
            json=payload,
            headers={
                "X-Mock-Export-Mode": settings.mock_export_mode,
                "Idempotency-Key": idempotency_key,
                "X-Signature": f"sha256={request_signature}",
                "X-Correlation-ID": correlation_id,
            },
            timeout=1.0,
        )
    except httpx.TimeoutException as error:
        raise ExportWorkflowError("Mock downstream export timed out; retry is safe.", retryable=True) from error
    except httpx.HTTPError as error:
        raise ExportWorkflowError("Mock downstream export could not be reached; retry is safe.", retryable=True) from error
    try:
        response_payload = response.json() if response.content else None
    except ValueError:
        response_payload = {"raw": response.text[:500]} if response.text else None
    if response.status_code == 429:
        raise ExportWorkflowError(
            "Mock downstream export is rate limited; retry with the same idempotency key.",
            retryable=True,
            response_status=response.status_code,
        )
    if response.status_code >= 500:
        raise ExportWorkflowError(
            f"Mock downstream export failed ({response.status_code}); retry is safe.",
            retryable=True,
            response_status=response.status_code,
        )
    if response.status_code >= 400:
        raise ExportWorkflowError(
            f"Mock downstream export rejected the record ({response.status_code}).",
            retryable=False,
            response_status=response.status_code,
        )
    return response.status_code, response_payload


def export_case(
    session: Session,
    case_id: str,
    idempotency_key: str,
    correlation_id: str,
    workspace_id: str | None = None,
) -> tuple[bool, ExportAttempt | ExportAttemptRecord]:
    case = get_case_or_raise(session, case_id, workspace_id, for_update=True)
    operation = session.scalar(
        select(ExportAttempt).where(
            ExportAttempt.case_id == case.id, ExportAttempt.idempotency_key == idempotency_key
        ).with_for_update()
    )
    if operation and operation.status == "succeeded":
        latest_attempt = session.scalar(
            select(ExportAttemptRecord)
            .where(ExportAttemptRecord.operation_id == operation.id)
            .order_by(ExportAttemptRecord.attempt_number.desc())
        )
        return False, latest_attempt or operation
    if CaseStatus(case.status) != CaseStatus.READY_FOR_EXPORT:
        raise WorkflowError("Only reviewer-approved cases can be exported.")
    latest_extraction = session.get(ExtractionResult, case.latest_extraction_id) if case.latest_extraction_id else None
    approval = session.scalar(
        select(ReviewDecision)
        .where(
            ReviewDecision.case_id == case.id,
            ReviewDecision.extraction_id == (latest_extraction.id if latest_extraction else None),
            ReviewDecision.action.in_(["approve", "correct"]),
        )
        .order_by(ReviewDecision.created_at.desc())
    )
    if approval is None:
        raise WorkflowError("A reviewer must approve or correct the record before export.")
    payload = {
        "schema_version": "intake-record/2",
        "case_id": case.id,
        "external_reference": case.external_reference,
        "scenario": case.scenario,
        "extraction_id": latest_extraction.id if latest_extraction else None,
        "record": latest_extraction.normalized_record if latest_extraction else None,
    }
    if operation and (
        operation.extraction_id != (latest_extraction.id if latest_extraction else None)
        or operation.request_payload != payload
    ):
        raise WorkflowError(
            "This idempotency key is bound to an earlier extraction payload; use a new key."
        )
    request_signature = _export_signature(payload)
    operation = operation or ExportAttempt(
        case_id=case.id,
        extraction_id=latest_extraction.id if latest_extraction else None,
        idempotency_key=idempotency_key,
        attempt_number=0,
    )
    session.add(operation)
    session.flush()
    previous_attempt_number = session.scalar(
        select(func.max(ExportAttemptRecord.attempt_number)).where(
            ExportAttemptRecord.operation_id == operation.id
        )
    ) or 0
    attempt = ExportAttemptRecord(
        operation_id=operation.id,
        case_id=case.id,
        extraction_id=latest_extraction.id if latest_extraction else None,
        idempotency_key=idempotency_key,
        attempt_number=previous_attempt_number + 1,
        status="started",
        request_payload=payload,
        request_signature=request_signature,
        retryable=False,
    )
    operation.attempt_number = attempt.attempt_number
    operation.status = "started"
    operation.request_payload = payload
    operation.request_signature = request_signature
    operation.retryable = False
    operation.error_message = None
    session.add(attempt)
    session.flush()
    transition_case(session, case, CaseStatus.EXPORTING, "reviewer", correlation_id, "approved export started")
    add_event(
        session,
        case,
        "export_requested",
        "reviewer",
        correlation_id,
        {"idempotency_key": idempotency_key, "attempt_id": attempt.id, "attempt_number": attempt.attempt_number},
    )
    try:
        response_status, response_body = submit_mock_export(
            case,
            idempotency_key,
            payload,
            request_signature=request_signature,
            correlation_id=correlation_id,
            # The guided flagship path and the standalone recovery scenario both
            # exercise the same controlled 429 -> same-key retry contract.
            force_rate_limit=case.scenario in {"exception-recovery", "retryable-export"}
            and attempt.attempt_number == 1,
        )
        attempt.response_status = response_status
        attempt.response_body = response_body
        if isinstance(response_body, dict):
            attempt.downstream_record_id = str(response_body.get("record_id")) if response_body.get("record_id") else None
        attempt.status = "succeeded"
        attempt.completed_at = now()
        operation.status = "succeeded"
        operation.response_status = response_status
        operation.response_body = response_body
        operation.downstream_record_id = attempt.downstream_record_id
    except ExportWorkflowError as error:
        attempt.status = "failed"
        attempt.retryable = error.retryable
        attempt.response_status = error.response_status
        attempt.error_message = str(error)
        attempt.completed_at = now()
        operation.status = "failed"
        operation.response_status = error.response_status
        operation.retryable = error.retryable
        operation.error_message = str(error)
        target = CaseStatus.READY_FOR_EXPORT if error.retryable else CaseStatus.FAILED
        transition_case(session, case, target, "mock-downstream", correlation_id, "retryable export failure" if error.retryable else "non-retryable export failure")
        add_event(
            session,
            case,
            "export_failed",
            "mock-downstream",
            correlation_id,
            {"error": str(error), "attempt_id": attempt.id, "attempt_number": attempt.attempt_number, "retryable": error.retryable, "response_status": error.response_status},
        )
        session.commit()
        raise
    transition_case(session, case, CaseStatus.COMPLETED, "mock-downstream", correlation_id, "mock export accepted")
    add_event(session, case, "export_completed", "mock-downstream", correlation_id, {"result": "accepted", "attempt_id": attempt.id})
    session.commit()
    return True, attempt


def case_query(workspace_id: str | None = None) -> Select[tuple[IntakeCase]]:
    statement = select(IntakeCase)
    if workspace_id is not None:
        statement = statement.where(IntakeCase.workspace_id == workspace_id)
    return statement.order_by(IntakeCase.updated_at.desc(), IntakeCase.created_at.desc())
