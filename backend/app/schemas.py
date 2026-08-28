from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class APIModel(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class EvidenceBox(APIModel):
    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)
    width: float = Field(ge=0, le=1)
    height: float = Field(ge=0, le=1)


class Evidence(APIModel):
    document_id: str | None = None
    page_number: int = Field(ge=1)
    quote: str = Field(min_length=1, max_length=500)
    confidence: float = Field(ge=0, le=1)
    provenance: Literal["model", "reviewer"] = "model"
    start_char: int | None = Field(default=None, ge=0)
    end_char: int | None = Field(default=None, ge=0)
    boxes: list[EvidenceBox] = Field(default_factory=list)
    source_mode: Literal["native", "ocr", "unknown"] = "native"
    source_confidence: float | None = Field(default=None, ge=0, le=1)


class ExtractedField(APIModel):
    name: str
    value: str | None = None
    evidence: Evidence | None = None


class IntakeRecord(APIModel):
    schema_version: str = "intake-record/2"
    case_reference: str | None = None
    member_identifier: str | None = None
    requesting_organization: str | None = None
    requesting_contact: str | None = None
    service_code: str | None = None
    requested_start_date: str | None = None
    document_types_present: list[str] = Field(default_factory=list)
    notes: str | None = None
    fields: list[ExtractedField] = Field(default_factory=list)
    patient_name: str | None = None
    date_of_birth: str | None = None
    payer_name: str | None = None
    group_number: str | None = None
    provider_name: str | None = None
    provider_npi: str | None = None
    procedure_codes: list[str] = Field(default_factory=list)
    diagnosis_codes: list[str] = Field(default_factory=list)
    requested_service_date: str | None = None


class CaseCreate(APIModel):
    external_reference: str = Field(min_length=3, max_length=100, pattern=r"^[A-Za-z0-9_-]+$")
    source: str = Field(default="web", max_length=100)


class CaseSummary(APIModel):
    id: str
    external_reference: str
    status: str
    source: str
    scenario: str | None = None
    document_count: int
    issue_count: int = 0
    workspace_id: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class DocumentSummary(APIModel):
    id: str
    original_filename: str
    sha256: str
    mime_type: str
    size_bytes: int
    page_count: int | None
    created_at: datetime | None = None
    source_mode: str = "native"


class ValidationIssueResponse(APIModel):
    id: str
    code: str
    severity: str
    field_name: str | None
    message: str
    evidence: dict | None
    created_at: datetime | None = None
    extraction_id: str | None = None
    resolved_at: datetime | None = None


class ModelRunResponse(APIModel):
    id: str
    provider: str
    model: str
    route_tier: str
    prompt_version: str
    schema_version: str
    input_tokens: int | None
    output_tokens: int | None
    duration_ms: int | None
    status: str
    error_message: str | None
    created_at: datetime | None = None
    purpose: str = "workflow"


class EventResponse(APIModel):
    id: str
    event_type: str
    actor: str
    correlation_id: str
    details: dict | None
    created_at: datetime | None = None


class CaseDetail(CaseSummary):
    documents: list[DocumentSummary]
    latest_record: IntakeRecord | None
    validation_issues: list[ValidationIssueResponse]
    model_runs: list[ModelRunResponse]
    events: list[EventResponse]
    reviewer_approved: bool
    latest_extraction_id: str | None = None
    latest_extraction_version: int | None = None
    export_attempts: list[ExportAttemptResponse] = Field(default_factory=list)


class ProcessResponse(APIModel):
    case_id: str
    job_id: str | None = None
    status: str
    stage: str = "queued"
    progress: int = Field(default=0, ge=0, le=100)
    correlation_id: str
    message: str


class ReviewRequest(APIModel):
    action: Literal["approve", "correct", "request_information"]
    reviewer: str = Field(default="demo-reviewer", min_length=2, max_length=100)
    reason: str | None = Field(default=None, max_length=1000)
    corrections: dict[str, str | None] = Field(default_factory=dict)
    extraction_id: str = Field(min_length=32, max_length=32)

    @field_validator("corrections")
    @classmethod
    def only_known_fields(cls, value: dict[str, str | None]) -> dict[str, str | None]:
        allowed = {
            "case_reference",
            "member_identifier",
            "requesting_organization",
            "requesting_contact",
            "service_code",
            "requested_start_date",
            "notes",
            "patient_name",
            "date_of_birth",
            "payer_name",
            "group_number",
            "provider_name",
            "provider_npi",
            "requested_service_date",
        }
        unknown = set(value).difference(allowed)
        if unknown:
            raise ValueError(f"Unknown correction fields: {', '.join(sorted(unknown))}")
        return value

    @model_validator(mode="after")
    def validate_review_intent(self) -> ReviewRequest:
        if self.action == "correct":
            if not self.corrections:
                raise ValueError("A correction decision must change at least one field.")
            if not self.reason or len(self.reason.strip()) < 10:
                raise ValueError("Reviewer corrections require a concise rationale.")
        elif self.corrections:
            raise ValueError("Corrections are only accepted with action='correct'.")
        if self.action == "request_information" and (
            not self.reason or len(self.reason.strip()) < 10
        ):
            raise ValueError("Requesting information requires a concise rationale.")
        return self


class ExportResponse(APIModel):
    case_id: str
    status: str
    correlation_id: str
    message: str
    attempt_id: str | None = None
    attempt_number: int | None = None


class EvalCaseResult(APIModel):
    case_id: str
    category: str = "unknown"
    expected_status: str
    actual_status: str
    matched: bool
    issue: str | None = None
    fields_matched: int = 0
    fields_compared: int = 0
    evidence_valid: bool = True


class EvalRunResponse(APIModel):
    id: str
    dataset: str
    total_cases: int
    matched_cases: int
    routing_accuracy: float
    field_accuracy: float
    routing_macro_f1: float = 0.0
    field_macro_f1: float = 0.0
    false_ready_count: int = 0
    evidence_validity: float = 1.0
    category_metrics: dict[str, dict[str, float]] = Field(default_factory=dict)
    results: list[EvalCaseResult]


class ExportAttemptResponse(APIModel):
    id: str
    operation_id: str | None = None
    case_id: str
    extraction_id: str | None
    idempotency_key: str
    attempt_number: int
    status: str
    response_status: int | None
    response_body: dict | None
    request_signature: str | None = None
    downstream_record_id: str | None = None
    retryable: bool = False
    error_message: str | None
    created_at: datetime | None = None
    completed_at: datetime | None = None


class DemoScenario(APIModel):
    id: str
    title: str
    description: str
    status: str
    case_id: str | None = None
    recommended: bool = False


class TourStep(APIModel):
    id: str
    title: str
    body: str
    target: str
    route: str


class DemoSessionResponse(APIModel):
    session_id: str
    token: str
    expires_at: datetime
    scenario_version: str
    scenarios: list[DemoScenario]
    tour: list[TourStep]


class DemoManifestResponse(APIModel):
    session_id: str
    expires_at: datetime
    scenario_version: str
    scenarios: list[DemoScenario]
    tour: list[TourStep]


class PageResponse(APIModel):
    document_id: str
    page_number: int
    text: str
    source_mode: str
    source_confidence: float | None
    width: float | None = None
    height: float | None = None
    image_url: str


class ModelComparisonResponse(APIModel):
    id: str
    case_id: str
    provider: str
    model: str
    status: str
    result: dict | None = None
    error_message: str | None = None
    created_at: datetime | None = None


class MetaResponse(APIModel):
    app_version: str
    api_commit_sha: str
    frontend_commit_sha: str = "unknown"
    build_time: str | None = None
    schema_version: str
    mode: str
    demo_scenario_version: str
    custom_uploads_enabled: bool
    live_model_compare_enabled: bool
    evaluation_runs_enabled: bool


class JobResponse(APIModel):
    id: str
    case_id: str
    job_type: str
    status: str
    stage: str
    attempt: int
    progress: int = Field(ge=0, le=100)
    idempotency_key: str
    correlation_id: str
    failure_classification: str | None = None
    error_message: str | None = None
    created_at: datetime | None = None
    completed_at: datetime | None = None


class ProofResponse(APIModel):
    generated_at: datetime | None = None
    commit_sha: str
    frontend_commit_sha: str = "unknown"
    build_time: str | None = None
    app_version: str
    schema_version: str
    demo_scenario_version: str
    provider: str
    latest_evaluation: EvalRunResponse | None = None
    quality_gates: dict[str, bool]
    limitations: list[str]
