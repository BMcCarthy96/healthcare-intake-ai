from __future__ import annotations

from enum import StrEnum


class CaseStatus(StrEnum):
    RECEIVED = "received"
    QUEUED = "queued"
    PROCESSING = "processing"
    READY_FOR_EXPORT = "ready_for_export"
    MISSING_INFORMATION = "missing_information"
    REVIEW_REQUIRED = "review_required"
    FAILED = "failed"
    COMPLETED = "completed"


ALLOWED_TRANSITIONS: dict[CaseStatus, set[CaseStatus]] = {
    CaseStatus.RECEIVED: {CaseStatus.QUEUED},
    CaseStatus.QUEUED: {CaseStatus.PROCESSING},
    CaseStatus.PROCESSING: {
        CaseStatus.READY_FOR_EXPORT,
        CaseStatus.MISSING_INFORMATION,
        CaseStatus.REVIEW_REQUIRED,
        CaseStatus.FAILED,
    },
    CaseStatus.REVIEW_REQUIRED: {
        CaseStatus.READY_FOR_EXPORT,
        CaseStatus.MISSING_INFORMATION,
        CaseStatus.FAILED,
    },
    CaseStatus.MISSING_INFORMATION: {CaseStatus.QUEUED},
    CaseStatus.FAILED: {CaseStatus.QUEUED},
    CaseStatus.READY_FOR_EXPORT: {CaseStatus.COMPLETED},
    CaseStatus.COMPLETED: set(),
}


def can_transition(current: CaseStatus, target: CaseStatus) -> bool:
    return target in ALLOWED_TRANSITIONS[current]
