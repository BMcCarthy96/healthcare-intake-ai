from __future__ import annotations

import uuid
from collections.abc import Callable
from contextlib import asynccontextmanager
from typing import cast

from fastapi import Depends, FastAPI, File, Header, HTTPException, Request, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_session
from app.demo import seed_demo_case
from app.documents import DocumentError, persist_and_parse_document
from app.evaluations import get_evaluation_payload, run_and_persist_evaluation
from app.models import (
    Document,
    EvalRun,
    ExtractionResult,
    IntakeCase,
    ModelRun,
    ReviewDecision,
    ValidationIssue,
)
from app.schemas import (
    CaseCreate,
    CaseDetail,
    CaseSummary,
    DocumentSummary,
    EvalRunResponse,
    EventResponse,
    ExportResponse,
    IntakeRecord,
    ModelRunResponse,
    ProcessResponse,
    ReviewRequest,
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


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings.document_storage_path.mkdir(parents=True, exist_ok=True)
    yield


app = FastAPI(
    title="Healthcare Intake AI",
    version="0.1.0",
    description="Synthetic-data-only administrative document-to-action workflow API.",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def correlation_middleware(request: Request, call_next: Callable) -> Response:
    correlation_id = request.headers.get("X-Correlation-ID", uuid.uuid4().hex)
    request.state.correlation_id = correlation_id
    response = cast(Response, await call_next(request))
    response.headers["X-Correlation-ID"] = correlation_id
    return response


def correlation_id(request: Request) -> str:
    return str(request.state.correlation_id)


def api_error(status: int, message: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"message": message})


def case_summary(case: IntakeCase) -> CaseSummary:
    return CaseSummary(
        id=case.id,
        external_reference=case.external_reference,
        status=case.status,
        source=case.source,
        document_count=len(case.documents),
        created_at=case.created_at,
        updated_at=case.updated_at,
    )


@app.get("/health/live")
def health_live() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/health/ready")
def health_ready() -> dict[str, str]:
    return {"status": "ready", "mode": "synthetic-only"}


@app.post("/v1/cases", response_model=CaseSummary, status_code=201)
def create_case(payload: CaseCreate, request: Request, session: Session = Depends(get_session)) -> CaseSummary:
    existing = session.scalar(select(IntakeCase).where(IntakeCase.external_reference == payload.external_reference))
    if existing:
        raise api_error(409, "A case with this external reference already exists.")
    case = IntakeCase(external_reference=payload.external_reference, source=payload.source)
    session.add(case)
    session.flush()
    add_event(session, case, "case_created", "api", correlation_id(request), {"source": payload.source})
    session.commit()
    session.refresh(case)
    return case_summary(case)


@app.get("/v1/cases", response_model=list[CaseSummary])
def list_cases(session: Session = Depends(get_session)) -> list[CaseSummary]:
    cases = list(session.scalars(case_query()))
    return [case_summary(case) for case in cases]


@app.post("/v1/demo/seed", response_model=CaseSummary)
def create_synthetic_demo(request: Request, session: Session = Depends(get_session)) -> CaseSummary:
    return case_summary(seed_demo_case(session, correlation_id(request)))


@app.get("/v1/cases/{case_id}", response_model=CaseDetail)
def get_case(case_id: str, session: Session = Depends(get_session)) -> CaseDetail:
    try:
        case = get_case_or_raise(session, case_id)
    except WorkflowError as error:
        raise api_error(404, str(error)) from error
    documents = list(session.scalars(select(Document).where(Document.case_id == case.id)))
    issues = list(
        session.scalars(select(ValidationIssue).where(ValidationIssue.case_id == case.id).order_by(ValidationIssue.created_at.desc()))
    )
    model_runs = list(session.scalars(select(ModelRun).where(ModelRun.case_id == case.id).order_by(ModelRun.created_at.desc())))
    latest_record = None
    if case.latest_extraction_id:
        extraction = session.get(ExtractionResult, case.latest_extraction_id)
        latest_record = IntakeRecord.model_validate(extraction.normalized_record) if extraction else None
    reviewer_approved = session.scalar(
        select(ReviewDecision.id).where(
            ReviewDecision.case_id == case.id,
            ReviewDecision.action.in_(["approve", "correct"]),
        )
    ) is not None
    return CaseDetail(
        **case_summary(case).model_dump(),
        documents=[DocumentSummary.model_validate(document, from_attributes=True) for document in documents],
        latest_record=latest_record,
        validation_issues=[ValidationIssueResponse.model_validate(issue, from_attributes=True) for issue in issues],
        model_runs=[ModelRunResponse.model_validate(run, from_attributes=True) for run in model_runs],
        events=[EventResponse.model_validate(event, from_attributes=True) for event in sorted(case.events, key=lambda e: e.created_at or 0, reverse=True)],
        reviewer_approved=reviewer_approved,
    )


@app.post("/v1/cases/{case_id}/documents", response_model=DocumentSummary, status_code=201)
async def upload_document(
    case_id: str,
    request: Request,
    file: UploadFile = File(...),
    session: Session = Depends(get_session),
) -> DocumentSummary:
    try:
        case = get_case_or_raise(session, case_id)
        content = await file.read()
        parsed = persist_and_parse_document(case.id, content, file.filename or "intake.pdf")
    except WorkflowError as error:
        raise api_error(404, str(error)) from error
    except DocumentError as error:
        raise api_error(422, str(error)) from error
    duplicate = session.scalar(
        select(Document).where(Document.case_id == case.id, Document.sha256 == parsed.sha256)
    )
    if duplicate:
        raise api_error(409, "This document is already attached to the case.")
    document = Document(
        case_id=case.id,
        storage_key=parsed.storage_key,
        original_filename=file.filename or "intake.pdf",
        sha256=parsed.sha256,
        mime_type="application/pdf",
        size_bytes=parsed.size_bytes,
        page_count=len(parsed.page_texts),
        extracted_pages={"pages": parsed.page_texts},
    )
    session.add(document)
    session.flush()
    add_event(
        session,
        case,
        "document_uploaded",
        "api",
        correlation_id(request),
        {"document_id": document.id, "sha256": parsed.sha256, "page_count": len(parsed.page_texts)},
    )
    session.commit()
    session.refresh(document)
    return DocumentSummary.model_validate(document, from_attributes=True)


@app.post("/v1/cases/{case_id}/process", response_model=ProcessResponse)
def process_case_endpoint(
    case_id: str,
    request: Request,
    idempotency_key: str = Header(alias="Idempotency-Key", min_length=8, max_length=200),
    session: Session = Depends(get_session),
) -> ProcessResponse:
    try:
        created = request_processing(session, case_id, idempotency_key, correlation_id(request))
        case = get_case_or_raise(session, case_id)
    except WorkflowError as error:
        raise api_error(409, str(error)) from error
    return ProcessResponse(
        case_id=case.id,
        status=case.status,
        correlation_id=correlation_id(request),
        message="Case processed." if created else "Idempotent replay returned existing processing result.",
    )


@app.post("/v1/cases/{case_id}/retry", response_model=ProcessResponse)
def retry_case(
    case_id: str,
    request: Request,
    idempotency_key: str = Header(alias="Idempotency-Key", min_length=8, max_length=200),
    session: Session = Depends(get_session),
) -> ProcessResponse:
    return process_case_endpoint(case_id, request, idempotency_key, session)


@app.get("/v1/cases/{case_id}/events", response_model=list[EventResponse])
def get_events(case_id: str, session: Session = Depends(get_session)) -> list[EventResponse]:
    try:
        case = get_case_or_raise(session, case_id)
    except WorkflowError as error:
        raise api_error(404, str(error)) from error
    return [EventResponse.model_validate(event, from_attributes=True) for event in sorted(case.events, key=lambda e: e.created_at or 0, reverse=True)]


@app.post("/v1/cases/{case_id}/review", response_model=CaseSummary)
def review_case(
    case_id: str,
    payload: ReviewRequest,
    request: Request,
    session: Session = Depends(get_session),
) -> CaseSummary:
    try:
        case = submit_review(session, case_id, payload, correlation_id(request))
    except WorkflowError as error:
        raise api_error(409, str(error)) from error
    return case_summary(case)


@app.post("/v1/cases/{case_id}/request-information", response_model=CaseSummary)
def request_information(
    case_id: str,
    payload: ReviewRequest,
    request: Request,
    session: Session = Depends(get_session),
) -> CaseSummary:
    forced = payload.model_copy(update={"action": "request_information"})
    return review_case(case_id, forced, request, session)


@app.post("/v1/cases/{case_id}/export", response_model=ExportResponse)
def export_case_endpoint(
    case_id: str,
    request: Request,
    idempotency_key: str = Header(alias="Idempotency-Key", min_length=8, max_length=200),
    session: Session = Depends(get_session),
) -> ExportResponse:
    try:
        exported = export_case(session, case_id, idempotency_key, correlation_id(request))
        case = get_case_or_raise(session, case_id)
    except WorkflowError as error:
        raise api_error(409, str(error)) from error
    return ExportResponse(
        case_id=case.id,
        status=case.status,
        correlation_id=correlation_id(request),
        message="Mock downstream export accepted." if exported else "Idempotent replay returned existing export result.",
    )


@app.get("/v1/model-runs/{run_id}", response_model=ModelRunResponse)
def get_model_run(run_id: str, session: Session = Depends(get_session)) -> ModelRunResponse:
    model_run = session.get(ModelRun, run_id)
    if model_run is None:
        raise api_error(404, "Model run not found.")
    return ModelRunResponse.model_validate(model_run, from_attributes=True)


@app.post("/v1/evals", response_model=EvalRunResponse)
def run_evaluation(dataset: str = "development", session: Session = Depends(get_session)) -> EvalRunResponse:
    if dataset not in {"development", "held_out"}:
        raise api_error(422, "Dataset must be 'development' or 'held_out'.")
    return EvalRunResponse.model_validate(get_evaluation_payload(session, run_and_persist_evaluation(session, dataset)))


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
