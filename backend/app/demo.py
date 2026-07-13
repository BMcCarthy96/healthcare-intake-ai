from __future__ import annotations

from io import BytesIO

from reportlab.pdfgen import canvas
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.documents import persist_and_parse_document
from app.models import Document, IntakeCase
from app.services import add_event, request_processing


def _build_demo_pdf() -> bytes:
    stream = BytesIO()
    pdf = canvas.Canvas(stream)
    lines = [
        "SYNTHETIC ADMINISTRATIVE INTAKE PACKET",
        "Case Reference: DEMO-2026-001",
        "Member ID: SYN-48291",
        "Requesting Organization: Northstar Administrative Services",
        "Requesting Contact: Jordan Lee",
        "Service Code: ADM-204",
        "Requested Start Date: 2026-08-01",
        "This packet contains synthetic administrative data only.",
    ]
    for index, line in enumerate(lines):
        pdf.drawString(72, 760 - index * 30, line)
    pdf.save()
    return stream.getvalue()


def seed_demo_case(session: Session, correlation_id: str) -> IntakeCase:
    existing = session.scalar(select(IntakeCase).where(IntakeCase.external_reference == "DEMO-2026-001"))
    if existing:
        return existing
    case = IntakeCase(external_reference="DEMO-2026-001", source="synthetic-demo")
    session.add(case)
    session.flush()
    add_event(session, case, "case_created", "demo-seed", correlation_id, {"source": "synthetic-demo"})
    parsed = persist_and_parse_document(case.id, _build_demo_pdf(), "synthetic-intake-demo.pdf")
    document = Document(
        case_id=case.id,
        storage_key=parsed.storage_key,
        original_filename="synthetic-intake-demo.pdf",
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
        "demo-seed",
        correlation_id,
        {"document_id": document.id, "sha256": parsed.sha256, "page_count": len(parsed.page_texts)},
    )
    session.commit()
    request_processing(session, case.id, f"demo-seed-{case.id}", correlation_id)
    return session.get(IntakeCase, case.id) or case
