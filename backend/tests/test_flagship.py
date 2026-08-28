from __future__ import annotations

import json
from io import BytesIO

from reportlab.pdfgen import canvas


def _pdf(text: str) -> bytes:
    stream = BytesIO()
    document = canvas.Canvas(stream)
    for index, line in enumerate(text.splitlines()):
        document.drawString(72, 760 - index * 24, line)
    document.save()
    return stream.getvalue()


def _case(client, reference: str) -> str:
    response = client.post("/v1/cases", json={"external_reference": reference})
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _upload(client, case_id: str) -> None:
    payload = """Synthetic Administrative Intake Packet
Case Reference: FLAG-1001
Member ID: MEM-1001
Requesting Organization: Northstar Administrative Services
Requesting Contact: Jordan Lee
Service Code: ADM-204
Requested Start Date: 2026-08-01
"""
    response = client.post(f"/v1/cases/{case_id}/documents", files={"file": ("packet.pdf", _pdf(payload), "application/pdf")})
    assert response.status_code == 201, response.text


def test_demo_session_is_isolated_and_resettable(client) -> None:
    first = client.post("/v1/demo/sessions")
    assert first.status_code == 200, first.text
    first_payload = first.json()
    first_headers = {"X-Demo-Session": first_payload["token"]}
    cases = client.get("/v1/cases", headers=first_headers)
    assert cases.status_code == 200
    assert len(cases.json()) == 5
    assert any(item["scenario"] == "exception-recovery" for item in cases.json())

    second = client.post("/v1/demo/sessions")
    assert second.status_code == 200
    second_headers = {"X-Demo-Session": second.json()["token"]}
    assert second.json()["session_id"] != first_payload["session_id"]
    assert client.get(f"/v1/cases/{cases.json()[0]['id']}", headers=second_headers).status_code == 404
    assert client.get(f"/v1/cases/{cases.json()[0]['id']}").status_code == 404
    assert all(item["workspace_id"] is None for item in client.get("/v1/cases").json())

    reset = client.post(f"/v1/demo/sessions/{first_payload['session_id']}/reset", headers=first_headers)
    assert reset.status_code == 200, reset.text
    assert len(client.get("/v1/cases", headers=first_headers).json()) == 5


def test_correction_creates_new_extraction_version_and_export_replay_is_safe(client) -> None:
    case_id = _case(client, "FLAG-VERSION-001")
    _upload(client, case_id)
    processed = client.post(f"/v1/cases/{case_id}/process", headers={"Idempotency-Key": "flag-process-001"})
    assert processed.status_code == 200
    before = client.get(f"/v1/cases/{case_id}").json()
    extraction_id = before["latest_extraction_id"]
    review = client.post(f"/v1/cases/{case_id}/review", json={"action": "correct", "extraction_id": extraction_id, "corrections": {"member_identifier": "MEM-CORRECTED"}, "reason": "Reconciled against the synthetic insurance card."})
    assert review.status_code == 200, review.text
    after = client.get(f"/v1/cases/{case_id}").json()
    assert after["latest_extraction_version"] == before["latest_extraction_version"] + 1
    assert after["latest_record"]["member_identifier"] == "MEM-CORRECTED"
    corrected_field = next(
        field
        for field in after["latest_record"]["fields"]
        if field["name"] == "member_identifier"
    )
    assert corrected_field["value"] == "MEM-CORRECTED"
    assert corrected_field["evidence"] is None
    assert after["issue_count"] == 0
    exported = client.post(f"/v1/cases/{case_id}/export", headers={"Idempotency-Key": "flag-export-001"})
    assert exported.status_code == 200, exported.text
    replay = client.post(f"/v1/cases/{case_id}/export", headers={"Idempotency-Key": "flag-export-001"})
    assert replay.status_code == 200
    assert replay.json()["attempt_id"] == exported.json()["attempt_id"]
    assert len(client.get(f"/v1/cases/{case_id}/exports").json()) == 1


def test_page_endpoint_returns_rendered_evidence_asset(client) -> None:
    case_id = _case(client, "FLAG-PAGE-001")
    _upload(client, case_id)
    processed = client.post(f"/v1/cases/{case_id}/process", headers={"Idempotency-Key": "flag-page-process"})
    assert processed.status_code == 200
    detail = client.get(f"/v1/cases/{case_id}").json()
    document_id = detail["documents"][0]["id"]
    page = client.get(f"/v1/documents/{document_id}/pages/1")
    assert page.status_code == 200
    assert page.json()["source_mode"] == "native"
    image = client.get(f"/v1/documents/{document_id}/pages/1/image")
    assert image.status_code == 200
    assert image.headers["content-type"].startswith("image/png")


def test_processing_returns_job_contract(client) -> None:
    case_id = _case(client, "FLAG-JOB-001")
    _upload(client, case_id)
    response = client.post(
        f"/v1/cases/{case_id}/process", headers={"Idempotency-Key": "flag-job-process-001"}
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["job_id"]
    assert payload["stage"] == "completed"
    assert payload["progress"] == 100
    job = client.get(f"/v1/jobs/{payload['job_id']}")
    assert job.status_code == 200
    assert job.json()["failure_classification"] is None


def test_job_contract_queue_filters_and_ocr_provenance(client) -> None:
    session = client.post("/v1/demo/sessions").json()
    headers = {"X-Demo-Session": session["token"]}
    filtered = client.get("/v1/cases?status=review_required&risk=high", headers=headers)
    assert filtered.status_code == 200
    assert filtered.json()
    assert all(case["status"] == "review_required" for case in filtered.json())
    retry = next(item for item in session["scenarios"] if item["id"] == "retryable-export")
    processing = client.post(
        f"/v1/cases/{retry['case_id']}/process",
        headers={**headers, "Idempotency-Key": "demo-retry-process"},
    )
    # Seeded cases have already been processed; the endpoint should reject an unsafe replay.
    assert processing.status_code == 409
    scanned = next(item for item in session["scenarios"] if item["id"] == "scanned-packet")
    scanned_detail = client.get(f"/v1/cases/{scanned['case_id']}", headers=headers).json()
    scanned_page = client.get(
        f"/v1/documents/{scanned_detail['documents'][0]['id']}/pages/1", headers=headers
    )
    assert scanned_page.status_code == 200
    assert scanned_page.json()["source_mode"] == "ocr"


def test_retryable_demo_export_preserves_attempt_and_reuses_signature(client) -> None:
    session = client.post("/v1/demo/sessions").json()
    headers = {"X-Demo-Session": session["token"]}
    scenario = next(item for item in session["scenarios"] if item["id"] == "retryable-export")
    detail = client.get(f"/v1/cases/{scenario['case_id']}", headers=headers).json()
    approved = client.post(
        f"/v1/cases/{scenario['case_id']}/review",
        headers=headers,
        json={"action": "approve", "extraction_id": detail["latest_extraction_id"]},
    )
    assert approved.status_code == 200, approved.text
    key = "demo-retry-export-001"
    first = client.post(
        f"/v1/cases/{scenario['case_id']}/export",
        headers={**headers, "Idempotency-Key": key},
    )
    assert first.status_code == 409
    attempts = client.get(f"/v1/cases/{scenario['case_id']}/exports", headers=headers).json()
    assert len(attempts) == 1
    assert attempts[0]["response_status"] == 429
    assert attempts[0]["retryable"] is True
    second = client.post(
        f"/v1/cases/{scenario['case_id']}/export",
        headers={**headers, "Idempotency-Key": key},
    )
    assert second.status_code == 200, second.text
    assert second.json()["attempt_number"] == 2
    attempts = client.get(f"/v1/cases/{scenario['case_id']}/exports", headers=headers).json()
    by_number = {attempt["attempt_number"]: attempt for attempt in attempts}
    assert len(by_number) == 2
    assert by_number[1]["status"] == "failed"
    assert by_number[2]["status"] == "succeeded"
    assert by_number[2]["request_signature"] == by_number[1]["request_signature"]


def test_guided_exception_path_uses_controlled_retryable_export(client) -> None:
    session = client.post("/v1/demo/sessions").json()
    headers = {"X-Demo-Session": session["token"]}
    scenario = next(item for item in session["scenarios"] if item["id"] == "exception-recovery")
    detail = client.get(f"/v1/cases/{scenario['case_id']}", headers=headers).json()
    insurance_document = next(
        document
        for document in detail["documents"]
        if document["original_filename"] == "insurance-card.pdf"
    )
    payer_evidence = next(
        field
        for field in detail["latest_record"]["fields"]
        if field["name"] == "payer_name"
    )["evidence"]
    assert payer_evidence["document_id"] == insurance_document["id"]
    assert payer_evidence["page_number"] == 1
    reviewed = client.post(
        f"/v1/cases/{scenario['case_id']}/reviews",
        headers=headers,
        json={
            "action": "correct",
            "extraction_id": detail["latest_extraction_id"],
            "corrections": {"member_identifier": "SYN-48219"},
            "reason": "Reconciled against the synthetic insurance card.",
        },
    )
    assert reviewed.status_code == 200, reviewed.text
    corrected_detail = client.get(
        f"/v1/cases/{scenario['case_id']}", headers=headers
    ).json()
    corrected_member = next(
        field
        for field in corrected_detail["latest_record"]["fields"]
        if field["name"] == "member_identifier"
    )
    assert corrected_member["value"] == "SYN-48219"
    assert corrected_member["evidence"]["document_id"] == insurance_document["id"]
    assert corrected_member["evidence"]["page_number"] == 1
    assert corrected_member["evidence"]["provenance"] == "reviewer"
    key = "guided-exception-export-001"
    first = client.post(
        f"/v1/cases/{scenario['case_id']}/exports",
        headers={**headers, "Idempotency-Key": key},
    )
    assert first.status_code == 409
    second = client.post(
        f"/v1/cases/{scenario['case_id']}/exports",
        headers={**headers, "Idempotency-Key": key},
    )
    assert second.status_code == 200
    assert second.json()["attempt_number"] == 2


def test_stale_reviews_and_unexplained_corrections_are_rejected(client) -> None:
    case_id = _case(client, "FLAG-STALE-001")
    _upload(client, case_id)
    client.post(
        f"/v1/cases/{case_id}/process",
        headers={"Idempotency-Key": "flag-stale-process"},
    )
    first = client.get(f"/v1/cases/{case_id}").json()
    missing_reason = client.post(
        f"/v1/cases/{case_id}/review",
        json={
            "action": "correct",
            "extraction_id": first["latest_extraction_id"],
            "corrections": {"member_identifier": "MEM-RECONCILED"},
        },
    )
    assert missing_reason.status_code == 422
    corrected = client.post(
        f"/v1/cases/{case_id}/review",
        json={
            "action": "correct",
            "extraction_id": first["latest_extraction_id"],
            "corrections": {"member_identifier": "MEM-RECONCILED"},
            "reason": "Reconciled against the synthetic insurance card.",
        },
    )
    assert corrected.status_code == 200
    stale = client.post(
        f"/v1/cases/{case_id}/review",
        json={"action": "approve", "extraction_id": first["latest_extraction_id"]},
    )
    assert stale.status_code == 409


def test_export_key_cannot_be_rebound_to_a_new_extraction(client) -> None:
    session = client.post("/v1/demo/sessions").json()
    headers = {"X-Demo-Session": session["token"]}
    scenario = next(item for item in session["scenarios"] if item["id"] == "exception-recovery")
    first_detail = client.get(f"/v1/cases/{scenario['case_id']}", headers=headers).json()
    reviewed = client.post(
        f"/v1/cases/{scenario['case_id']}/review",
        headers=headers,
        json={
            "action": "correct",
            "extraction_id": first_detail["latest_extraction_id"],
            "corrections": {"member_identifier": "SYN-48219"},
            "reason": "Reconciled against the synthetic insurance card.",
        },
    )
    assert reviewed.status_code == 200
    key = "bound-export-key-001"
    first_export = client.post(
        f"/v1/cases/{scenario['case_id']}/export",
        headers={**headers, "Idempotency-Key": key},
    )
    assert first_export.status_code == 409
    retry_detail = client.get(f"/v1/cases/{scenario['case_id']}", headers=headers).json()
    rereviewed = client.post(
        f"/v1/cases/{scenario['case_id']}/review",
        headers=headers,
        json={
            "action": "correct",
            "extraction_id": retry_detail["latest_extraction_id"],
            "corrections": {"member_identifier": "SYN-48219-RECHECKED"},
            "reason": "A second synthetic reviewer produced a newer extraction version.",
        },
    )
    assert rereviewed.status_code == 200
    rebound = client.post(
        f"/v1/cases/{scenario['case_id']}/export",
        headers={**headers, "Idempotency-Key": key},
    )
    assert rebound.status_code == 409
    assert "earlier extraction payload" in rebound.json()["detail"]["message"]
    assert len(client.get(f"/v1/cases/{scenario['case_id']}/exports", headers=headers).json()) == 1


def test_proof_endpoint_reports_persisted_evaluation_metrics(client) -> None:
    before = client.get("/v1/proof")
    assert before.status_code == 200
    assert before.json()["latest_evaluation"] is None
    run = client.post("/v1/evals?dataset=challenge")
    assert run.status_code == 200
    proof = client.get("/v1/proof")
    assert proof.status_code == 200
    payload = proof.json()
    assert payload["latest_evaluation"]["total_cases"] == 40
    assert payload["quality_gates"]["zero_false_ready"] is True


def test_proof_manifest_reads_ci_coverage_and_test_count(tmp_path, monkeypatch) -> None:
    from scripts.generate_proof_manifest import _coverage_percent, _test_count

    coverage_path = tmp_path / "coverage.json"
    coverage_path.write_text(
        json.dumps({"totals": {"percent_covered": 91.75}}), encoding="utf-8"
    )
    junit_path = tmp_path / "pytest-report.xml"
    junit_path.write_text(
        '<testsuites><testsuite name="unit" tests="17" /></testsuites>',
        encoding="utf-8",
    )
    monkeypatch.setenv("COVERAGE_JSON", str(coverage_path))
    monkeypatch.setenv("PYTEST_JUNIT_XML", str(junit_path))

    assert _coverage_percent() == 91.75
    assert _test_count() == 17
