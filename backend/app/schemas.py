from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class APIModel(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class Evidence(APIModel):
    page_number: int = Field(ge=1)
    quote: str = Field(min_length=1, max_length=500)
    confidence: float = Field(ge=0, le=1)


class ExtractedField(APIModel):
    name: str
    value: str | None = None
    evidence: Evidence | None = None


class IntakeRecord(APIModel):
    case_reference: str | None = None
    member_identifier: str | None = None
    requesting_organization: str | None = None
    requesting_contact: str | None = None
    service_code: str | None = None
    requested_start_date: str | None = None
    document_types_present: list[str] = Field(default_factory=list)
    notes: str | None = None
    fields: list[ExtractedField] = Field(default_factory=list)


class CaseCreate(APIModel):
    external_reference: str = Field(min_length=3, max_length=100, pattern=r"^[A-Za-z0-9_-]+$")
    source: str = Field(default="web", max_length=100)


class CaseSummary(APIModel):
    id: str
    external_reference: str
    status: str
    source: str
    document_count: int
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


class ValidationIssueResponse(APIModel):
    id: str
    code: str
    severity: str
    field_name: str | None
    message: str
    evidence: dict | None
    created_at: datetime | None = None


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


class ProcessResponse(APIModel):
    case_id: str
    status: str
    correlation_id: str
    message: str


class ReviewRequest(APIModel):
    action: Literal["approve", "correct", "request_information"]
    reviewer: str = Field(default="demo-reviewer", min_length=2, max_length=100)
    reason: str | None = Field(default=None, max_length=1000)
    corrections: dict[str, str | None] = Field(default_factory=dict)

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
        }
        unknown = set(value).difference(allowed)
        if unknown:
            raise ValueError(f"Unknown correction fields: {', '.join(sorted(unknown))}")
        return value


class ExportResponse(APIModel):
    case_id: str
    status: str
    correlation_id: str
    message: str


class EvalCaseResult(APIModel):
    case_id: str
    expected_status: str
    actual_status: str
    matched: bool
    issue: str | None = None
    fields_matched: int = 0
    fields_compared: int = 0


class EvalRunResponse(APIModel):
    id: str
    dataset: str
    total_cases: int
    matched_cases: int
    routing_accuracy: float
    field_accuracy: float
    results: list[EvalCaseResult]
