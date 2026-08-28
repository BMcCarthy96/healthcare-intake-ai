from __future__ import annotations

import base64
import binascii
import hashlib
import json
import logging
import os
import time
import uuid
from collections.abc import Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import cast

from fastapi import (
    Depends,
    FastAPI,
    File,
    Header,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
)
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import and_, func, or_, select, text
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import SessionLocal, get_session
from app.demo import (
    SCENARIO_VERSION,
    SCENARIOS,
    TOUR,
    ScenarioSpec,
    create_demo_workspace,
    reset_demo_workspace,
    seed_demo_case,
)
from app.documents import DocumentError, get_document_store, persist_and_parse_document
from app.evaluations import get_evaluation_payload, run_and_persist_evaluation
from app.model_gateway import AnthropicModelGateway
from app.models import (
    DemoWorkspace,
    Document,
    EvalRun,
    ExportAttemptRecord,
    ExtractionResult,
    IntakeCase,
    ModelComparison,
    ModelRun,
    ProcessingJob,
    ReviewDecision,
    ValidationIssue,
)
from app.schemas import (
    CaseCreate,
    CaseDetail,
    CaseSummary,
    DemoManifestResponse,
    DemoScenario,
    DemoSessionResponse,
    DocumentSummary,
    EvalRunResponse,
    EventResponse,
    ExportAttemptResponse,
    ExportResponse,
    IntakeRecord,
    JobResponse,
    MetaResponse,
    ModelComparisonResponse,
    ModelRunResponse,
    PageResponse,
    ProcessResponse,
    ProofResponse,
    ReviewRequest,
    TourStep,
    ValidationIssueResponse,
)
from app.services import (
    WorkflowError,
    add_event,
    case_query,
    export_case,
    get_case_or_raise,
    request_processing,
    submit_review,
)

settings = get_settings()
logger = logging.getLogger("intakeflow.api")


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings.document_storage_path.mkdir(parents=True, exist_ok=True)
    if settings.proof_auto_seed_enabled:
        proof_session = SessionLocal()
        try:
            existing = proof_session.scalar(
                select(EvalRun.id).where(EvalRun.dataset == "held_out").limit(1)
            )
            if existing is None:
                run_and_persist_evaluation(proof_session, "held_out")
        except Exception:
            logger.exception("Unable to seed the deterministic recruiter proof evaluation.")
        finally:
            proof_session.close()
    yield


app = FastAPI(
    title="Healthcare Intake AI",
    version=settings.app_version,
    description="Synthetic-data-only administrative document-to-action workflow API.",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "Idempotency-Key", "X-Correlation-ID", "X-Demo-Session"],
)


@app.middleware("http")
async def correlation_middleware(request: Request, call_next: Callable) -> Response:
    supplied_correlation = request.headers.get("X-Correlation-ID", "")
    correlation = (
        supplied_correlation
        if supplied_correlation and len(supplied_correlation) <= 64 and supplied_correlation.isascii()
        else uuid.uuid4().hex
    )
    request.state.correlation_id = correlation
    started = time.perf_counter()
    response = cast(Response, await call_next(request))
    response.headers["X-Correlation-ID"] = correlation
    response.headers["X-App-Version"] = settings.app_version
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    logger.info(
        json.dumps(
            {
                "event": "http_request",
                "method": request.method,
                "path": request.url.path,
                "status": response.status_code,
                "duration_ms": int((time.perf_counter() - started) * 1000),
                "correlation_id": correlation,
            },
            separators=(",", ":"),
        )
    )
    return response


def correlation_id(request: Request) -> str:
    return str(request.state.correlation_id)


def api_error(status: int, message: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"message": message})


def get_demo_workspace(
    x_demo_session: str | None = Header(default=None, alias="X-Demo-Session"),
    session: Session = Depends(get_session),
) -> DemoWorkspace | None:
    if not x_demo_session:
        return None
    token_hash = hashlib.sha256(x_demo_session.encode()).hexdigest()
    workspace = session.scalar(select(DemoWorkspace).where(DemoWorkspace.token_hash == token_hash))
    if workspace is None:
        raise api_error(401, "Demo session is invalid. Start a new walkthrough.")
    if workspace.expires_at.replace(tzinfo=UTC) <= datetime.now(UTC):
        raise api_error(410, "Demo session expired. Start a new walkthrough.")
    workspace.last_seen_at = datetime.now(UTC)
    session.commit()
    return workspace


def case_summary(session: Session, case: IntakeCase) -> CaseSummary:
    # Count explicitly instead of relying on an unloaded relationship; this keeps list responses cheap
    # enough for the small demo while remaining correct for newly created cases.
    issues = len(
        list(
            session.scalars(
                select(ValidationIssue.id).where(
                    ValidationIssue.case_id == case.id, ValidationIssue.resolved_at.is_(None)
                )
            )
        )
    )
    return CaseSummary(
        id=case.id,
        external_reference=case.external_reference,
        status=case.status,
        source=case.source,
        scenario=case.scenario,
        document_count=len(case.documents),
        issue_count=issues,
        workspace_id=case.workspace_id,
        created_at=case.created_at,
        updated_at=case.updated_at,
    )


def _decode_case_cursor(
    cursor: str | None, session: Session, workspace_id: str | None = None
) -> tuple[datetime, str] | None:
    if not cursor:
        return None
    try:
        decoded = base64.urlsafe_b64decode(cursor.encode()).decode()
        payload = json.loads(decoded)
        anchor_id = str(payload["id"])
        statement = select(IntakeCase).where(IntakeCase.id == anchor_id)
        if workspace_id is None:
            statement = statement.where(IntakeCase.workspace_id.is_(None))
        else:
            statement = statement.where(IntakeCase.workspace_id == workspace_id)
        anchor = session.scalar(statement)
        if anchor is None or anchor.updated_at is None:
            return None
        return anchor.updated_at, anchor.id
    except (ValueError, KeyError, TypeError, binascii.Error, json.JSONDecodeError):
        raise api_error(422, "Cursor is invalid or expired.") from None


def _encode_case_cursor(case: IntakeCase) -> str:
    payload = json.dumps({"id": case.id}, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(payload).decode()


def _scenario_payload(case: IntakeCase) -> DemoScenario:
    scenario: ScenarioSpec | None = next((item for item in SCENARIOS if item["id"] == case.scenario), None)
    if scenario is None:
        return DemoScenario(id=case.scenario or "custom", title=case.external_reference, description="Synthetic case", status=case.status, recommended=False, case_id=case.id)
    return DemoScenario(**scenario, case_id=case.id)


@app.get("/health/live")
def health_live() -> dict[str, str]:
    return {"status": "ok", "mode": "synthetic-only"}


@app.get("/health/ready")
def health_ready(session: Session = Depends(get_session)) -> dict[str, str]:
    try:
        session.execute(text("SELECT 1"))
    except Exception as error:
        raise api_error(503, "Database is not ready.") from error
    if settings.async_processing and settings.redis_url:
        try:
            import redis

            redis.Redis.from_url(settings.redis_url, socket_connect_timeout=0.5).ping()
        except Exception as error:
            raise api_error(503, "Queue service is not ready.") from error
    return {"status": "ready", "mode": "synthetic-only", "version": settings.app_version}


@app.get("/v1/meta", response_model=MetaResponse)
def metadata() -> MetaResponse:
    return MetaResponse(
        app_version=settings.app_version,
        api_commit_sha=os.getenv("RENDER_GIT_COMMIT", os.getenv("GIT_COMMIT_SHA", "local")),
        frontend_commit_sha=os.getenv("FRONTEND_COMMIT_SHA", "unknown"),
        build_time=os.getenv("BUILD_TIME"),
        schema_version="intake-record/2",
        mode="synthetic-only",
        demo_scenario_version=SCENARIO_VERSION,
        custom_uploads_enabled=settings.public_uploads_enabled,
        live_model_compare_enabled=settings.live_model_compare_enabled,
        evaluation_runs_enabled=settings.evaluation_runs_enabled,
    )


@app.get("/v1/proof", response_model=ProofResponse)
def proof(session: Session = Depends(get_session)) -> ProofResponse:
    """Return proof data from persisted evaluation state, not copied marketing numbers."""
    latest = session.scalar(
        select(EvalRun)
        .where(EvalRun.dataset == "held_out")
        .order_by(EvalRun.created_at.desc())
    ) or session.scalar(select(EvalRun).order_by(EvalRun.created_at.desc()))
    evaluation = get_evaluation_payload(session, latest) if latest else None
    gates = {
        "zero_false_ready": bool(evaluation and evaluation["false_ready_count"] == 0),
        "routing_macro_f1": bool(evaluation and evaluation["routing_macro_f1"] >= 0.95),
        "field_macro_f1": bool(evaluation and evaluation["field_macro_f1"] >= 0.95),
        "valid_evidence": bool(evaluation and evaluation["evidence_validity"] >= 1.0),
    }
    return ProofResponse(
        generated_at=datetime.now(UTC),
        commit_sha=os.getenv("RENDER_GIT_COMMIT", os.getenv("GIT_COMMIT_SHA", "local")),
        frontend_commit_sha=os.getenv("FRONTEND_COMMIT_SHA", "unknown"),
        build_time=os.getenv("BUILD_TIME"),
        app_version=settings.app_version,
        schema_version="intake-record/2",
        demo_scenario_version=SCENARIO_VERSION,
        provider=settings.model_provider,
        latest_evaluation=EvalRunResponse.model_validate(evaluation) if evaluation else None,
        quality_gates=gates,
        limitations=[
            "Synthetic administrative data only.",
            "No diagnosis, treatment, urgency, coverage, or autonomous clinical decisions.",
            "Live model comparison is optional, bounded, and never authoritative.",
        ],
    )


@app.post("/v1/cases", response_model=CaseSummary, status_code=201)
def create_case(
    payload: CaseCreate,
    request: Request,
    session: Session = Depends(get_session),
    workspace: DemoWorkspace | None = Depends(get_demo_workspace),
) -> CaseSummary:
    if not settings.public_uploads_enabled:
        raise api_error(
            403,
            "Custom case creation is disabled in this synthetic public deployment.",
        )
    existing = session.scalar(select(IntakeCase).where(IntakeCase.external_reference == payload.external_reference))
    if existing:
        raise api_error(409, "A case with this external reference already exists.")
    case = IntakeCase(
        external_reference=payload.external_reference,
        source=payload.source,
        workspace_id=workspace.id if workspace else None,
        scenario="custom",
    )
    session.add(case)
    session.flush()
    add_event(session, case, "case_created", "api", correlation_id(request), {"source": payload.source})
    session.commit()
    session.refresh(case)
    return case_summary(session, case)


@app.get("/v1/cases", response_model=list[CaseSummary])
def list_cases(
    response: Response,
    status: str | None = Query(default=None),
    risk: str | None = Query(default=None),
    query: str | None = Query(default=None, min_length=1, max_length=100),
    cursor: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=100),
    session: Session = Depends(get_session),
    workspace: DemoWorkspace | None = Depends(get_demo_workspace),
) -> list[CaseSummary]:
    statement = case_query(workspace.id if workspace else None)
    if workspace is None:
        statement = statement.where(IntakeCase.workspace_id.is_(None))
    if status:
        statement = statement.where(IntakeCase.status == status)
    if query:
        statement = statement.where(IntakeCase.external_reference.ilike(f"%{query}%"))
    if risk:
        risk_statuses = {
            "high": ["review_required", "failed", "exporting"],
            "medium": ["missing_information", "queued", "processing"],
            "low": ["received", "ready_for_export", "completed"],
        }.get(risk.lower())
        if risk_statuses is None:
            raise api_error(422, "Risk must be high, medium, or low.")
        statement = statement.where(IntakeCase.status.in_(risk_statuses))
    anchor = _decode_case_cursor(cursor, session, workspace.id if workspace else None)
    if anchor:
        anchor_updated, anchor_id = anchor
        statement = statement.where(
            or_(
                IntakeCase.updated_at < anchor_updated,
                and_(IntakeCase.updated_at == anchor_updated, IntakeCase.id < anchor_id),
            )
        )
    cases = list(session.scalars(statement.limit(limit)))
    if len(cases) == limit:
        response.headers["X-Next-Cursor"] = _encode_case_cursor(cases[-1])
    return [case_summary(session, case) for case in cases]


@app.post("/v1/demo/sessions", response_model=DemoSessionResponse)
def start_demo_session(request: Request, session: Session = Depends(get_session)) -> DemoSessionResponse:
    workspace, token, cases = create_demo_workspace(session, correlation_id(request))
    return DemoSessionResponse(
        session_id=workspace.id,
        token=token,
        expires_at=workspace.expires_at,
        scenario_version=workspace.scenario_version,
        scenarios=[_scenario_payload(case) for case in cases],
        tour=[TourStep(**step) for step in TOUR],
    )


@app.post("/v1/demo/sessions/{session_id}/reset", response_model=DemoManifestResponse)
def reset_session(
    session_id: str,
    request: Request,
    session: Session = Depends(get_session),
    workspace: DemoWorkspace | None = Depends(get_demo_workspace),
) -> DemoManifestResponse:
    if workspace is None or workspace.id != session_id:
        raise api_error(401, "A valid demo session is required to reset this workspace.")
    cases = reset_demo_workspace(session, workspace, correlation_id(request))
    return DemoManifestResponse(
        session_id=workspace.id,
        expires_at=workspace.expires_at,
        scenario_version=workspace.scenario_version,
        scenarios=[_scenario_payload(case) for case in cases],
        tour=[TourStep(**step) for step in TOUR],
    )


@app.get("/v1/demo/manifest", response_model=DemoManifestResponse)
def demo_manifest(
    session: Session = Depends(get_session),
    workspace: DemoWorkspace | None = Depends(get_demo_workspace),
) -> DemoManifestResponse:
    if workspace is None:
        raise api_error(401, "A valid demo session is required.")
    cases = list(session.scalars(case_query(workspace.id)))
    return DemoManifestResponse(session_id=workspace.id, expires_at=workspace.expires_at, scenario_version=workspace.scenario_version, scenarios=[_scenario_payload(case) for case in cases], tour=[TourStep(**step) for step in TOUR])


@app.post("/v1/demo/seed", response_model=CaseSummary)
def create_synthetic_demo(request: Request, session: Session = Depends(get_session)) -> CaseSummary:
    return case_summary(session, seed_demo_case(session, correlation_id(request)))


def _case_detail(session: Session, case: IntakeCase) -> CaseDetail:
    documents = list(session.scalars(select(Document).where(Document.case_id == case.id).order_by(Document.created_at)))
    issues = list(
        session.scalars(
            select(ValidationIssue)
            .where(ValidationIssue.case_id == case.id, ValidationIssue.resolved_at.is_(None))
            .order_by(ValidationIssue.created_at.desc())
        )
    )
    model_runs = list(session.scalars(select(ModelRun).where(ModelRun.case_id == case.id).order_by(ModelRun.created_at.desc())))
    extraction = session.get(ExtractionResult, case.latest_extraction_id) if case.latest_extraction_id else None
    latest_record = IntakeRecord.model_validate(extraction.normalized_record) if extraction else None
    reviewer_approved = bool(
        extraction
        and session.scalar(
            select(ReviewDecision.id).where(
                ReviewDecision.case_id == case.id,
                ReviewDecision.extraction_id == extraction.id,
                ReviewDecision.action.in_(["approve", "correct"]),
            )
        )
    )
    attempts = list(
        session.scalars(
            select(ExportAttemptRecord)
            .where(ExportAttemptRecord.case_id == case.id)
            .order_by(ExportAttemptRecord.created_at.desc())
        )
    )
    summary = case_summary(session, case)
    return CaseDetail(
        **summary.model_dump(),
        documents=[
            DocumentSummary.model_validate(document, from_attributes=True).model_copy(
                update={"source_mode": ((document.extracted_pages or {}).get("page_metadata") or [{"source_mode": "native"}])[0].get("source_mode", "native")}
            )
            for document in documents
        ],
        latest_record=latest_record,
        validation_issues=[ValidationIssueResponse.model_validate(issue, from_attributes=True) for issue in issues],
        model_runs=[ModelRunResponse.model_validate(run, from_attributes=True) for run in model_runs],
        events=[EventResponse.model_validate(event, from_attributes=True) for event in sorted(case.events, key=lambda e: e.created_at or datetime.min.replace(tzinfo=UTC), reverse=True)],
        reviewer_approved=reviewer_approved,
        latest_extraction_id=extraction.id if extraction else None,
        latest_extraction_version=extraction.version if extraction else None,
        export_attempts=[ExportAttemptResponse.model_validate(attempt, from_attributes=True) for attempt in attempts],
    )


@app.get("/v1/cases/{case_id}", response_model=CaseDetail)
def get_case(
    case_id: str,
    session: Session = Depends(get_session),
    workspace: DemoWorkspace | None = Depends(get_demo_workspace),
) -> CaseDetail:
    try:
        case = get_case_or_raise(session, case_id, workspace.id if workspace else None)
    except WorkflowError as error:
        raise api_error(404, str(error)) from error
    return _case_detail(session, case)


@app.post("/v1/cases/{case_id}/documents", response_model=DocumentSummary, status_code=201)
async def upload_document(
    case_id: str,
    request: Request,
    file: UploadFile = File(...),
    session: Session = Depends(get_session),
    workspace: DemoWorkspace | None = Depends(get_demo_workspace),
) -> DocumentSummary:
    if not settings.public_uploads_enabled:
        raise api_error(
            403,
            "The public demo uses bundled synthetic packets. Custom uploads are local-only.",
        )
    try:
        case = get_case_or_raise(session, case_id, workspace.id if workspace else None)
        # Read one byte over the configured limit so a hostile upload cannot allocate
        # unbounded memory before validate_pdf gets a chance to reject it.
        content = await file.read(settings.max_upload_bytes + 1)
        parsed = persist_and_parse_document(case.id, content, file.filename or "intake.pdf")
    except WorkflowError as error:
        raise api_error(404, str(error)) from error
    except DocumentError as error:
        raise api_error(422, str(error)) from error
    duplicate = session.scalar(select(Document).where(Document.case_id == case.id, Document.sha256 == parsed.sha256))
    if duplicate:
        raise api_error(409, "This document is already attached to the case.")
    document = Document(case_id=case.id, storage_key=parsed.storage_key, original_filename=file.filename or "intake.pdf", sha256=parsed.sha256, mime_type="application/pdf", size_bytes=parsed.size_bytes, page_count=len(parsed.page_texts), extracted_pages={"pages": parsed.page_texts, "page_metadata": parsed.page_metadata})
    session.add(document)
    session.flush()
    add_event(session, case, "document_uploaded", "api", correlation_id(request), {"document_id": document.id, "sha256": parsed.sha256, "page_count": len(parsed.page_texts)})
    session.commit()
    session.refresh(document)
    return DocumentSummary.model_validate(document, from_attributes=True).model_copy(
        update={"source_mode": parsed.page_metadata[0].get("source_mode") if parsed.page_metadata else "native"}
    )


@app.get("/v1/documents/{document_id}/pages/{page_number}", response_model=PageResponse)
def get_document_page(
    document_id: str,
    page_number: int,
    workspace: DemoWorkspace | None = Depends(get_demo_workspace),
    session: Session = Depends(get_session),
) -> PageResponse:
    document = session.get(Document, document_id)
    if document is None:
        raise api_error(404, "Document not found.")
    case = session.get(IntakeCase, document.case_id)
    if case is None or (workspace is None and case.workspace_id is not None) or (workspace is not None and case.workspace_id != workspace.id):
        raise api_error(404, "Document not found.")
    pages = (document.extracted_pages or {}).get("pages", [])
    metadata = (document.extracted_pages or {}).get("page_metadata", [])
    if page_number < 1 or page_number > len(pages):
        raise api_error(404, "Document page not found.")
    page_meta = metadata[page_number - 1] if page_number <= len(metadata) else {}
    return PageResponse(document_id=document.id, page_number=page_number, text=pages[page_number - 1], source_mode=page_meta.get("source_mode", "native"), source_confidence=page_meta.get("source_confidence"), width=page_meta.get("width"), height=page_meta.get("height"), image_url=f"/v1/documents/{document.id}/pages/{page_number}/image")


@app.get("/v1/documents/{document_id}/pages/{page_number}/image")
def get_document_page_image(
    document_id: str,
    page_number: int,
    workspace: DemoWorkspace | None = Depends(get_demo_workspace),
    session: Session = Depends(get_session),
) -> Response:
    document = session.get(Document, document_id)
    case = session.get(IntakeCase, document.case_id) if document else None
    if document is None or case is None or (workspace is None and case.workspace_id is not None) or (workspace is not None and case.workspace_id != workspace.id):
        raise api_error(404, "Document page not found.")
    metadata = (document.extracted_pages or {}).get("page_metadata", [])
    if page_number < 1 or page_number > len(metadata):
        raise api_error(404, "Document page not found.")
    image_key = metadata[page_number - 1].get("image_key")
    if not image_key:
        raise api_error(404, "Rendered page image is unavailable.")
    try:
        content = get_document_store().get(image_key)
    except DocumentError as error:
        raise api_error(404, str(error)) from error
    return Response(content=content, media_type="image/png", headers={"Cache-Control": "private, max-age=3600"})


@app.post("/v1/cases/{case_id}/process", response_model=ProcessResponse)
def process_case_endpoint(
    case_id: str,
    request: Request,
    idempotency_key: str = Header(alias="Idempotency-Key", min_length=8, max_length=200),
    session: Session = Depends(get_session),
    workspace: DemoWorkspace | None = Depends(get_demo_workspace),
) -> ProcessResponse:
    try:
        created = request_processing(session, case_id, idempotency_key, correlation_id(request), workspace.id if workspace else None)
        case = get_case_or_raise(session, case_id, workspace.id if workspace else None)
    except WorkflowError as error:
        raise api_error(409, str(error)) from error
    job = session.scalar(
        select(ProcessingJob)
        .where(ProcessingJob.case_id == case.id, ProcessingJob.idempotency_key == idempotency_key)
        .order_by(ProcessingJob.created_at.desc())
    )
    return ProcessResponse(
        case_id=case.id,
        job_id=job.id if job else None,
        status=case.status,
        stage=job.stage if job else "queued",
        progress=job.progress if job else 0,
        correlation_id=correlation_id(request),
        message=(
            "Processing queued."
            if created and settings.async_processing
            else "Processing completed."
            if created
            else "Idempotent replay returned existing processing result."
        ),
    )


@app.get("/v1/jobs/{job_id}", response_model=JobResponse)
def get_job(
    job_id: str,
    session: Session = Depends(get_session),
    workspace: DemoWorkspace | None = Depends(get_demo_workspace),
) -> JobResponse:
    job = session.get(ProcessingJob, job_id)
    case = session.get(IntakeCase, job.case_id) if job else None
    if job is None or case is None or (workspace is None and case.workspace_id is not None) or (workspace is not None and case.workspace_id != workspace.id):
        raise api_error(404, "Processing job not found.")
    return JobResponse.model_validate(job, from_attributes=True)


@app.post("/v1/cases/{case_id}/retry", response_model=ProcessResponse)
def retry_case(
    case_id: str,
    request: Request,
    idempotency_key: str = Header(alias="Idempotency-Key", min_length=8, max_length=200),
    session: Session = Depends(get_session),
    workspace: DemoWorkspace | None = Depends(get_demo_workspace),
) -> ProcessResponse:
    return process_case_endpoint(case_id, request, idempotency_key, session, workspace)


@app.get("/v1/cases/{case_id}/events", response_model=list[EventResponse])
def get_events(case_id: str, session: Session = Depends(get_session), workspace: DemoWorkspace | None = Depends(get_demo_workspace)) -> list[EventResponse]:
    try:
        case = get_case_or_raise(session, case_id, workspace.id if workspace else None)
    except WorkflowError as error:
        raise api_error(404, str(error)) from error
    return [EventResponse.model_validate(event, from_attributes=True) for event in sorted(case.events, key=lambda e: e.created_at or datetime.min.replace(tzinfo=UTC), reverse=True)]


@app.post("/v1/cases/{case_id}/review", response_model=CaseSummary)
@app.post("/v1/cases/{case_id}/reviews", response_model=CaseSummary)
def review_case(
    case_id: str,
    payload: ReviewRequest,
    request: Request,
    session: Session = Depends(get_session),
    workspace: DemoWorkspace | None = Depends(get_demo_workspace),
) -> CaseSummary:
    try:
        case = submit_review(session, case_id, payload, correlation_id(request), workspace.id if workspace else None)
    except WorkflowError as error:
        raise api_error(409, str(error)) from error
    return case_summary(session, case)


@app.post("/v1/cases/{case_id}/request-information", response_model=CaseSummary)
def request_information(case_id: str, payload: ReviewRequest, request: Request, session: Session = Depends(get_session), workspace: DemoWorkspace | None = Depends(get_demo_workspace)) -> CaseSummary:
    forced = payload.model_copy(update={"action": "request_information"})
    return review_case(case_id, forced, request, session, workspace)


@app.post("/v1/cases/{case_id}/export", response_model=ExportResponse)
@app.post("/v1/cases/{case_id}/exports", response_model=ExportResponse)
def export_case_endpoint(
    case_id: str,
    request: Request,
    idempotency_key: str = Header(alias="Idempotency-Key", min_length=8, max_length=200),
    session: Session = Depends(get_session),
    workspace: DemoWorkspace | None = Depends(get_demo_workspace),
) -> ExportResponse:
    try:
        exported, attempt = export_case(session, case_id, idempotency_key, correlation_id(request), workspace.id if workspace else None)
        case = get_case_or_raise(session, case_id, workspace.id if workspace else None)
    except WorkflowError as error:
        raise api_error(409, str(error)) from error
    return ExportResponse(case_id=case.id, status=case.status, correlation_id=correlation_id(request), message="Mock downstream export accepted." if exported else "Idempotent replay returned existing export result.", attempt_id=attempt.id, attempt_number=attempt.attempt_number)


@app.get("/v1/cases/{case_id}/exports", response_model=list[ExportAttemptResponse])
def get_exports(case_id: str, session: Session = Depends(get_session), workspace: DemoWorkspace | None = Depends(get_demo_workspace)) -> list[ExportAttemptResponse]:
    try:
        case = get_case_or_raise(session, case_id, workspace.id if workspace else None)
    except WorkflowError as error:
        raise api_error(404, str(error)) from error
    attempts = list(
        session.scalars(
            select(ExportAttemptRecord)
            .where(ExportAttemptRecord.case_id == case.id)
            .order_by(ExportAttemptRecord.created_at.desc())
        )
    )
    return [ExportAttemptResponse.model_validate(attempt, from_attributes=True) for attempt in attempts]


@app.get("/v1/model-runs/{run_id}", response_model=ModelRunResponse)
def get_model_run(run_id: str, session: Session = Depends(get_session), workspace: DemoWorkspace | None = Depends(get_demo_workspace)) -> ModelRunResponse:
    model_run = session.get(ModelRun, run_id)
    if model_run is None:
        raise api_error(404, "Model run not found.")
    case = session.get(IntakeCase, model_run.case_id)
    if case is None or (workspace is None and case.workspace_id is not None) or (workspace is not None and case.workspace_id != workspace.id):
        raise api_error(404, "Model run not found.")
    return ModelRunResponse.model_validate(model_run, from_attributes=True)


@app.post("/v1/cases/{case_id}/model-comparisons", response_model=ModelComparisonResponse)
def compare_models(
    case_id: str,
    request: Request,
    session: Session = Depends(get_session),
    workspace: DemoWorkspace | None = Depends(get_demo_workspace),
) -> ModelComparisonResponse:
    if workspace is None:
        raise api_error(401, "Model comparison is available inside a demo session.")
    if not settings.live_model_compare_enabled:
        raise api_error(503, "Live model comparison is disabled for this deployment; the deterministic baseline remains authoritative.")
    try:
        case = get_case_or_raise(session, case_id, workspace.id)
    except WorkflowError as error:
        raise api_error(404, str(error)) from error
    if case.source != "isolated-synthetic-demo":
        raise api_error(403, "Model comparison is limited to bundled synthetic demo packets.")
    pages: list[str] = []
    document_hashes: list[str] = []
    for document in case.documents:
        pages.extend((document.extracted_pages or {}).get("pages", []))
        document_hashes.append(document.sha256)
    model_id = os.getenv("ANTHROPIC_MODEL", "configured-provider")
    cache_key = hashlib.sha256(
        ("\n".join(sorted(document_hashes)) + "\nprompt-v1\nintake-record/2\n" + model_id).encode()
    ).hexdigest()
    existing = session.scalar(select(ModelComparison).where(ModelComparison.workspace_id == workspace.id, ModelComparison.cache_key == cache_key))
    if existing:
        return ModelComparisonResponse.model_validate(existing, from_attributes=True)
    comparison_count = session.scalar(
        select(func.count(ModelComparison.id)).where(ModelComparison.workspace_id == workspace.id)
    ) or 0
    if comparison_count >= settings.max_model_comparisons_per_session:
        raise api_error(429, "The demo comparison budget is used; reset the workspace for another run.")
    day_start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    daily_count = session.scalar(
        select(func.count(ModelComparison.id)).where(ModelComparison.created_at >= day_start)
    ) or 0
    if daily_count >= settings.model_compare_daily_budget:
        raise api_error(429, "The global model comparison budget is used for today.")
    circuit_cutoff = datetime.now(UTC) - timedelta(minutes=settings.model_compare_circuit_window_minutes)
    recent_statuses = list(
        session.scalars(
            select(ModelComparison.status)
            .where(ModelComparison.created_at >= circuit_cutoff)
            .order_by(ModelComparison.created_at.desc())
            .limit(settings.model_compare_circuit_failure_threshold)
        )
    )
    if (
        len(recent_statuses) >= settings.model_compare_circuit_failure_threshold
        and all(status == "error" for status in recent_statuses)
    ):
        raise api_error(503, "The optional model comparison circuit is open; try again later.")
    try:
        result = AnthropicModelGateway().extract(pages)
        input_tokens = result.input_tokens or 0
        output_tokens = result.output_tokens or 0
        payload = {
            "record": result.record.model_dump(mode="json"),
            "duration_ms": result.duration_ms,
            "input_tokens": result.input_tokens,
            "output_tokens": result.output_tokens,
            "estimated_cost_usd": round(input_tokens * 0.000001 + output_tokens * 0.000005, 6),
        }
        comparison = ModelComparison(workspace_id=workspace.id, case_id=case.id, cache_key=cache_key, provider=result.provider, model=result.model, status="success", result=payload)
    except Exception as error:
        comparison = ModelComparison(workspace_id=workspace.id, case_id=case.id, cache_key=cache_key, provider="anthropic", model=os.getenv("ANTHROPIC_MODEL", "configured-provider"), status="error", error_message=str(error))
    session.add(comparison)
    session.commit()
    session.refresh(comparison)
    add_event(session, case, "model_comparison_completed", "model-compare", correlation_id(request), {"comparison_id": comparison.id, "status": comparison.status})
    session.commit()
    return ModelComparisonResponse.model_validate(comparison, from_attributes=True)


@app.post("/v1/evals", response_model=EvalRunResponse)
def run_evaluation(dataset: str = "development", session: Session = Depends(get_session)) -> EvalRunResponse:
    if not settings.evaluation_runs_enabled:
        raise api_error(403, "Ad hoc evaluation runs are disabled; inspect the persisted proof results.")
    if dataset not in {"development", "held_out", "challenge"}:
        raise api_error(422, "Dataset must be 'development', 'held_out', or 'challenge'.")
    dataset_name = "held_out" if dataset == "challenge" else dataset
    return EvalRunResponse.model_validate(get_evaluation_payload(session, run_and_persist_evaluation(session, dataset_name)))


@app.get("/v1/evals", response_model=list[EvalRunResponse])
def list_evaluations(session: Session = Depends(get_session)) -> list[EvalRunResponse]:
    evaluations = list(session.scalars(select(EvalRun).order_by(EvalRun.created_at.desc())))
    return [EvalRunResponse.model_validate(get_evaluation_payload(session, item)) for item in evaluations]


@app.get("/v1/evals/{eval_run_id}", response_model=EvalRunResponse)
def get_evaluation(eval_run_id: str, session: Session = Depends(get_session)) -> EvalRunResponse:
    evaluation = session.get(EvalRun, eval_run_id)
    if evaluation is None:
        raise api_error(404, "Evaluation run not found.")
    return EvalRunResponse.model_validate(get_evaluation_payload(session, evaluation))
