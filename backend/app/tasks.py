from __future__ import annotations

from os import getenv

import dramatiq
from dramatiq.brokers.redis import RedisBroker

from app.db import SessionLocal
from app.models import IntakeCase
from app.services import process_case

redis_url = getenv("REDIS_URL")
if redis_url:
    dramatiq.set_broker(RedisBroker(url=redis_url))


@dramatiq.actor(max_retries=3, min_backoff=1000, max_backoff=15000, queue_name="intake-processing")
def process_intake_job(case_id: str, correlation_id: str, job_id: str) -> None:
    """Worker entry point with bounded retries; terminal failures remain auditable."""
    session = SessionLocal()
    try:
        # The queue message intentionally contains no bearer token. Resolve the
        # workspace from the case inside the worker and keep the same isolation
        # predicate used by request-time processing.
        case = session.get(IntakeCase, case_id)
        process_case(session, case_id, correlation_id, job_id, case.workspace_id if case else None)
    finally:
        session.close()
