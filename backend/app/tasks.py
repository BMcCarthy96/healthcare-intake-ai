from __future__ import annotations

from os import getenv

import dramatiq
from dramatiq.brokers.redis import RedisBroker

from app.db import SessionLocal
from app.services import process_case

redis_url = getenv("REDIS_URL")
if redis_url:
    dramatiq.set_broker(RedisBroker(url=redis_url))


@dramatiq.actor(max_retries=0, queue_name="intake-processing")
def process_intake_job(case_id: str, correlation_id: str, job_id: str) -> None:
    """Worker entry point. Failed jobs remain auditable and require an explicit API retry."""
    session = SessionLocal()
    try:
        process_case(session, case_id, correlation_id, job_id)
    finally:
        session.close()
