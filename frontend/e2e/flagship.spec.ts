import { expect, test } from "@playwright/test";

const tour = [
  { id: "queue", title: "Start in the operations queue", body: "Queue", target: "demo-queue", route: "/demo" },
  { id: "packet", title: "Open the exception packet", body: "Packet", target: "demo-case-exception-recovery", route: "/demo" },
  { id: "evidence", title: "Inspect grounded evidence", body: "Evidence", target: "evidence-viewer", route: "/demo/cases/{case_id}" },
  { id: "decision", title: "See why it stopped", body: "Decision", target: "decision-trace", route: "/demo/cases/{case_id}" },
  { id: "review", title: "Make a versioned correction", body: "Review", target: "review-actions", route: "/demo/cases/{case_id}" },
  { id: "export", title: "Recover from a downstream failure", body: "Export", target: "export-inspector", route: "/demo/cases/{case_id}" },
  { id: "proof", title: "Confirm the complete recovery trail", body: "Proof", target: "audit-timeline", route: "/demo/cases/{case_id}" },
];

const scenarios = [
  { id: "exception-recovery", title: "Contradictory packet + prompt injection", description: "Exception", status: "review_required", recommended: true, case_id: "case-exception" },
  { id: "complete-packet", title: "Clean packet", description: "Complete", status: "ready_for_export", recommended: false, case_id: "case-complete" },
  { id: "missing-information", title: "Missing member identifier", description: "Missing", status: "missing_information", recommended: false, case_id: "case-missing" },
  { id: "scanned-packet", title: "Scanned packet", description: "OCR", status: "ready_for_export", recommended: false, case_id: "case-scanned" },
  { id: "retryable-export", title: "Export recovery", description: "Retry", status: "ready_for_export", recommended: false, case_id: "case-retry" },
];

const session = {
  session_id: "workspace-e2e",
  token: "token-e2e",
  expires_at: "2099-01-01T00:00:00Z",
  scenario_version: "v2",
  tour,
  scenarios,
};

test("an expired recruiter session provisions a fresh workspace", async ({ page }) => {
  let sessionStarts = 0;

  await page.addInitScript(() => {
    window.sessionStorage.setItem("intakeflow-demo-token", "expired-token");
    window.sessionStorage.setItem("intakeflow-demo-session", "expired-workspace");
  });
  await page.route("**/v1/demo/sessions", async (route) => {
    sessionStarts += 1;
    await route.fulfill({ contentType: "application/json", body: JSON.stringify(session) });
  });
  await page.route("**/v1/demo/manifest", async (route) => {
    if (route.request().headers()["x-demo-session"] === "expired-token") {
      await route.fulfill({ status: 410, contentType: "application/json", body: JSON.stringify({ detail: { message: "Demo session expired. Start a new walkthrough." } }) });
      return;
    }
    await route.fulfill({ contentType: "application/json", body: JSON.stringify({ ...session, token: undefined }) });
  });
  await page.route("**/v1/cases", async (route) => {
    if (route.request().headers()["x-demo-session"] === "expired-token") {
      await route.fulfill({ status: 410, contentType: "application/json", body: JSON.stringify({ detail: { message: "Demo session expired. Start a new walkthrough." } }) });
      return;
    }
    await route.fulfill({ contentType: "application/json", body: JSON.stringify(scenarios.map((item) => ({ id: item.case_id, external_reference: item.id, status: item.status, source: "demo", scenario: item.id, document_count: item.id === "exception-recovery" ? 2 : 1, issue_count: item.id === "exception-recovery" ? 2 : 0 }))) });
  });

  await page.goto("/demo");

  await expect(page.getByRole("heading", { name: "Five synthetic scenarios" })).toBeVisible();
  await expect(page.getByRole("dialog", { name: "Walkthrough step 1 of 7" })).toBeVisible();
  expect(sessionStarts).toBe(1);
  await expect.poll(() => page.evaluate(() => window.sessionStorage.getItem("intakeflow-demo-token"))).toBe("token-e2e");
});

test("seven-step walkthrough performs the real correction and idempotent export recovery", async ({ page }) => {
  let reviewed = false;
  let exportCalls = 0;
  const exportKeys: string[] = [];

  const attempts = () => exportCalls === 0 ? [] : [
    ...(exportCalls >= 2 ? [{
      id: "attempt-2", operation_id: "operation-1", case_id: "case-exception", extraction_id: "extract-v2",
      idempotency_key: exportKeys[0], attempt_number: 2, status: "succeeded", response_status: 202,
      response_body: { accepted: true, duplicate: false, signature_valid: true }, request_signature: "signature-e2e",
      downstream_record_id: "downstream-e2e", retryable: false, error_message: null,
    }] : []),
    {
      id: "attempt-1", operation_id: "operation-1", case_id: "case-exception", extraction_id: "extract-v2",
      idempotency_key: exportKeys[0], attempt_number: 1, status: "failed", response_status: 429,
      response_body: null, request_signature: "signature-e2e", downstream_record_id: null,
      retryable: true, error_message: "Rate limited; retry is safe.",
    },
  ];

  const caseDetail = () => ({
    id: "case-exception",
    external_reference: "DEMO-EXCEPTION-E2E",
    status: exportCalls >= 2 ? "completed" : reviewed ? "ready_for_export" : "review_required",
    source: "isolated-synthetic-demo",
    scenario: "exception-recovery",
    workspace_id: "workspace-e2e",
    document_count: 2,
    issue_count: reviewed ? 0 : 2,
    documents: [
      { id: "doc-ref", original_filename: "referral-order.pdf", sha256: "a", mime_type: "application/pdf", size_bytes: 1024, page_count: 1, source_mode: "native" },
      { id: "doc-card", original_filename: "insurance-card.pdf", sha256: "b", mime_type: "application/pdf", size_bytes: 1024, page_count: 1, source_mode: "native" },
    ],
    latest_record: {
      schema_version: "intake-record/2",
      case_reference: "DEMO-EXCEPTION-001",
      member_identifier: reviewed ? "SYN-48219" : "SYN-48291",
      requesting_organization: "Northstar Administrative Services",
      requesting_contact: "Jordan Lee",
      service_code: "ADM-204",
      requested_start_date: "2026-08-01",
      document_types_present: ["administrative_packet"],
      notes: "Synthetic only",
      fields: [{
        name: "member_identifier",
        value: reviewed ? "SYN-48219" : "SYN-48291",
        evidence: reviewed
          ? { document_id: "doc-card", page_number: 1, quote: "Member ID: SYN-48219", confidence: 1, provenance: "reviewer", boxes: [{ x: 0.1, y: 0.2, width: 0.2, height: 0.04 }], source_mode: "native", source_confidence: 1 }
          : { document_id: "doc-ref", page_number: 1, quote: "Member ID: SYN-48291", confidence: 0.98, provenance: "model", boxes: [{ x: 0.1, y: 0.2, width: 0.2, height: 0.04 }], source_mode: "native", source_confidence: 1 },
      }],
    },
    validation_issues: reviewed ? [] : [
      { id: "issue-1", code: "contradictory_document_values", severity: "error", field_name: null, message: "Conflicting member identifiers.", evidence: null, extraction_id: "extract-v1" },
      { id: "issue-2", code: "untrusted_instruction_detected", severity: "error", field_name: null, message: "Instruction-like text.", evidence: null, extraction_id: "extract-v1" },
    ],
    model_runs: [{ id: "run-1", provider: "stub", model: "deterministic-intake-extractor-v1", route_tier: "cheap", duration_ms: 2, status: "success" }],
    events: [
      ...(exportCalls >= 2 ? [{ id: "event-success", event_type: "export_completed", actor: "mock-downstream", correlation_id: "corr", details: null, created_at: "2026-08-26T12:03:00Z" }] : []),
      ...(exportCalls >= 1 ? [{ id: "event-failed", event_type: "export_failed", actor: "mock-downstream", correlation_id: "corr", details: null, created_at: "2026-08-26T12:02:00Z" }] : []),
      ...(reviewed ? [{ id: "event-review", event_type: "review_decision_recorded", actor: "demo-reviewer", correlation_id: "corr", details: null, created_at: "2026-08-26T12:01:00Z" }] : []),
      { id: "event-process", event_type: "extraction_completed", actor: "worker", correlation_id: "corr", details: null, created_at: "2026-08-26T12:00:00Z" },
    ],
    reviewer_approved: reviewed,
    latest_extraction_id: reviewed ? "extract-v2" : "extract-v1",
    latest_extraction_version: reviewed ? 2 : 1,
    export_attempts: attempts(),
  });

  await page.route("**/v1/demo/sessions", (route) => route.fulfill({ contentType: "application/json", body: JSON.stringify(session) }));
  await page.route("**/v1/demo/manifest", (route) => route.fulfill({ contentType: "application/json", body: JSON.stringify({ ...session, token: undefined }) }));
  await page.route("**/v1/meta", (route) => route.fulfill({ contentType: "application/json", body: JSON.stringify({ app_version: "0.2.0", api_commit_sha: "e2e", frontend_commit_sha: "e2e", build_time: "2026-08-26T12:00:00Z", schema_version: "intake-record/2", mode: "synthetic-only", demo_scenario_version: "v2", custom_uploads_enabled: false, live_model_compare_enabled: false, evaluation_runs_enabled: false }) }));
  await page.route("**/v1/proof", (route) => route.fulfill({ contentType: "application/json", body: JSON.stringify({ commit_sha: "e2e", frontend_commit_sha: "e2e", app_version: "0.2.0", schema_version: "intake-record/2", demo_scenario_version: "v2", provider: "stub", latest_evaluation: null, quality_gates: { zero_false_ready: true }, limitations: ["Synthetic only"] }) }));
  await page.route("**/v1/cases", (route) => route.fulfill({ contentType: "application/json", body: JSON.stringify(scenarios.map((item) => ({ id: item.case_id, external_reference: item.id, status: item.status, source: "demo", scenario: item.id, document_count: item.id === "exception-recovery" ? 2 : 1, issue_count: item.id === "exception-recovery" ? 2 : 0 }))) }));
  await page.route("**/v1/cases/case-exception", (route) => route.fulfill({ contentType: "application/json", body: JSON.stringify(caseDetail()) }));
  await page.route("**/v1/documents/doc-ref/pages/1", (route) => route.fulfill({ contentType: "application/json", body: JSON.stringify({ document_id: "doc-ref", page_number: 1, text: "Member ID: SYN-48291", source_mode: "native", source_confidence: 1, width: 612, height: 792, image_url: "/image" }) }));
  await page.route("**/v1/documents/doc-ref/pages/1/image", (route) => route.fulfill({ status: 404, contentType: "application/json", body: "{}" }));
  await page.route("**/v1/cases/case-exception/review", async (route) => {
    const payload = route.request().postDataJSON();
    expect(payload.corrections).toEqual({ member_identifier: "SYN-48219" });
    expect(payload.reason).toContain("insurance card");
    expect(payload.extraction_id).toBe("extract-v1");
    reviewed = true;
    await route.fulfill({ contentType: "application/json", body: JSON.stringify({ id: "case-exception", status: "ready_for_export" }) });
  });
  await page.route("**/v1/cases/case-exception/export", async (route) => {
    exportCalls += 1;
    exportKeys.push(route.request().headers()["idempotency-key"]);
    if (exportCalls === 1) {
      await route.fulfill({ status: 409, contentType: "application/json", body: JSON.stringify({ detail: { message: "Mock downstream export is rate limited; retry is safe." } }) });
    } else {
      await route.fulfill({ contentType: "application/json", body: JSON.stringify({ status: "completed", attempt_id: "attempt-2", attempt_number: 2, message: "Accepted" }) });
    }
  });

  await page.goto("/demo");
  await expect(page.getByRole("dialog", { name: "Walkthrough step 1 of 7" })).toBeVisible();
  await page.getByRole("button", { name: "Next →" }).click();
  await page.getByRole("link", { name: /Contradictory packet \+ prompt injection/ }).click();
  await expect(page).toHaveURL(/\/demo\/cases\/case-exception$/);
  await expect(page.getByRole("dialog", { name: "Walkthrough step 3 of 7" })).toBeVisible();
  await page.getByRole("button", { name: "Next →" }).click();
  await page.getByRole("button", { name: "Next →" }).click();
  await page.getByRole("button", { name: "Apply correction + approve" }).click();
  await expect(page.getByRole("dialog", { name: "Walkthrough step 6 of 7" })).toBeVisible();
  await expect(page.getByText("Reviewer-grounded exact match")).toBeVisible();
  await page.getByRole("button", { name: "Trigger controlled 429 →" }).click();
  await expect(page.getByText("Controlled downstream 429 recorded.")).toBeVisible();
  await page.getByRole("button", { name: "Retry same export operation →" }).click();
  await expect(page.getByRole("dialog", { name: "Walkthrough step 7 of 7" })).toBeVisible();
  await expect(page.getByText("export completed")).toBeVisible();
  expect(exportKeys[0]).toBe(exportKeys[1]);
  await page.getByRole("button", { name: "Open technical proof →" }).click();
  await expect(page).toHaveURL(/\/proof$/);
  await expect(page.getByRole("heading", { name: "A trustworthy workflow is more than a model call." })).toBeVisible();
});
