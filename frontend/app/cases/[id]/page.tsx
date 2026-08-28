"use client";
/* The viewer uses object URLs for workspace-scoped rendered pages. */
/* eslint-disable @next/next/no-img-element */

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { ChangeEvent, useCallback, useEffect, useMemo, useState } from "react";
import { StatusPill } from "@/components/status-pill";
import { TourCoach } from "@/components/tour-coach";
import { api, CaseDetail, ExtractedField, fetchPageImage, DemoManifest, Meta } from "@/lib/api";

const labels: Record<string, string> = {
  case_reference: "Case reference",
  member_identifier: "Member identifier",
  requesting_organization: "Requesting organization",
  requesting_contact: "Requesting contact",
  service_code: "Service code",
  requested_start_date: "Requested start date",
  date_of_birth: "Date of birth",
  patient_name: "Patient name",
  payer_name: "Payer",
  group_number: "Group number",
  provider_npi: "Provider NPI",
  provider_name: "Requesting provider",
  requested_service_date: "Requested service date",
};

function timestamp(value?: string) {
  return value ? new Intl.DateTimeFormat("en", { dateStyle: "medium", timeStyle: "short" }).format(new Date(value)) : "—";
}

export default function CasePage() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const caseId = params.id;
  const [detail, setDetail] = useState<CaseDetail | null>(null);
  const [manifest, setManifest] = useState<DemoManifest | null>(null);
  const [meta, setMeta] = useState<Meta | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [corrections, setCorrections] = useState<Record<string, string | null>>({});
  const [reviewReason, setReviewReason] = useState("");
  const [pageDocument, setPageDocument] = useState<string | null>(null);
  const [page, setPage] = useState(1);
  const [pageData, setPageData] = useState<Awaited<ReturnType<typeof api.getPage>> | null>(null);
  const [pageImage, setPageImage] = useState<string | null>(null);
  const [comparison, setComparison] = useState<Record<string, unknown> | null>(null);
  const [tourIndex, setTourIndex] = useState<number | null>(() => {
    if (typeof window === "undefined") return null;
    if (window.sessionStorage.getItem("intakeflow-tour-paused") === "true") return null;
    const stored = window.sessionStorage.getItem("intakeflow-tour-step");
    const parsed = stored ? Number.parseInt(stored, 10) : -1;
    // A user can follow the highlighted queue card directly instead of using
    // the coach's Next button. The queue is step 1 and the packet handoff is
    // step 2, so resume on the evidence step when that handoff is in flight.
    if (parsed === 1) return 2;
    return parsed >= 2 ? parsed : null;
  });

  const load = useCallback(async () => {
    try {
      const item = await api.getCase(caseId);
      setDetail(item);
      setError(null);
      if (!pageDocument && item.documents[0]) setPageDocument(item.documents[0].id);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Unable to load case.");
    }
  }, [caseId, pageDocument]);

  useEffect(() => {
    let active = true;
    void api.getCase(caseId)
      .then((item) => { if (active) { setDetail(item); setError(null); if (item.documents[0]) setPageDocument(item.documents[0].id); } })
      .catch((reason: unknown) => { if (active) setError(reason instanceof Error ? reason.message : "Unable to load case."); });
    void api.manifest().then((item) => { if (active) setManifest(item); }).catch(() => undefined);
    void api.meta().then((item) => { if (active) setMeta(item); }).catch(() => undefined);
    return () => { active = false; };
  }, [caseId]);

  useEffect(() => {
    if (!pageDocument) return;
    let active = true;
    void api.getPage(pageDocument, page)
      .then((data) => { if (active) { setPageData(data); return fetchPageImage(pageDocument, page); } })
      .then((image) => { if (active && image) setPageImage(image); else if (image) URL.revokeObjectURL(image); })
      .catch(() => { if (active) { setPageData(null); setPageImage(null); } });
    return () => { active = false; };
  }, [pageDocument, page]);

  useEffect(() => () => { if (pageImage) URL.revokeObjectURL(pageImage); }, [pageImage]);

  const fields = useMemo(() => {
    const fieldsByName = new Map((detail?.latest_record?.fields || []).map((field) => [field.name, field]));
    return Object.keys(labels).map((name) => ({ name, value: detail?.latest_record ? (detail.latest_record as unknown as Record<string, string | null>)[name] : null, evidence: fieldsByName.get(name)?.evidence || null }));
  }, [detail]);

  const changedCorrections = useMemo(() => Object.fromEntries(
    Object.entries(corrections).filter(([name, value]) => {
      const original = detail?.latest_record
        ? (detail.latest_record as unknown as Record<string, string | null>)[name]
        : null;
      return (value || "") !== (original || "");
    }),
  ), [corrections, detail]);

  const act = async (action: () => Promise<unknown>, message: string): Promise<boolean> => {
    try { setBusy(true); setNotice(null); setError(null); await action(); setNotice(message); await load(); return true; }
    catch (reason) { setError(reason instanceof Error ? reason.message : "Workflow action failed."); await load(); return false; }
    finally { setBusy(false); }
  };

  const upload = async () => {
    if (!file) { setError("Choose a synthetic PDF first."); return; }
    await act(async () => { await api.upload(caseId, file); setFile(null); }, "Document attached. Start processing when ready.");
  };
  const process = async () => act(() => api.process(caseId), "Processing completed through the deterministic pipeline.");
  const review = async (action: "approve" | "correct" | "request_information") => {
    const rationale = reviewReason.trim();
    if (action === "correct" && Object.keys(changedCorrections).length === 0) {
      setError("Change at least one field before saving a correction.");
      return false;
    }
    if (action !== "approve" && rationale.length < 10) {
      setError("Enter a concise reviewer rationale before continuing.");
      return false;
    }
    return act(
      () => api.review(caseId, action, action === "correct" ? changedCorrections : {}, rationale || undefined, detail?.latest_extraction_id),
      action === "request_information" ? "Case routed to missing information." : action === "correct" ? "Correction saved as a new extraction version and approved." : "Reviewer decision recorded.",
    );
  };
  const exportCase = async () => act(() => api.exportCase(caseId), "Export accepted or safely replayed by the mock downstream.");
  const compare = async () => { try { setBusy(true); const result = await api.compareModels(caseId); setComparison(result.result || result as unknown as Record<string, unknown>); } catch (reason) { setError(reason instanceof Error ? reason.message : "Model comparison is unavailable in this deployment."); } finally { setBusy(false); } };

  const setTourStep = useCallback((next: number) => {
    setTourIndex(next);
    window.sessionStorage.setItem("intakeflow-tour-step", String(next));
  }, []);
  const nextTour = useCallback(() => {
    if (!manifest || tourIndex === null) return;
    if (tourIndex >= manifest.tour.length - 1) {
      setTourIndex(null);
      window.sessionStorage.removeItem("intakeflow-tour-step");
      window.sessionStorage.removeItem("intakeflow-tour-paused");
      router.push("/proof");
      return;
    }
    setTourStep(tourIndex + 1);
  }, [manifest, router, setTourStep, tourIndex]);
  const backTour = useCallback(() => {
    if (tourIndex === null) return;
    setTourStep(Math.max(0, tourIndex - 1));
  }, [setTourStep, tourIndex]);
  const closeTour = useCallback(() => {
    setTourIndex(null);
    window.sessionStorage.setItem("intakeflow-tour-paused", "true");
  }, []);
  const restartTour = useCallback(() => {
    window.sessionStorage.removeItem("intakeflow-tour-paused");
    setTourStep(0);
    router.push("/demo");
  }, [router, setTourStep]);

  const guidedReview = async () => {
    if (!detail?.latest_extraction_id) return;
    const guidedCorrections = { member_identifier: "SYN-48219" };
    const rationale = "Reconciled against the synthetic insurance card in the source packet.";
    setCorrections(guidedCorrections);
    setReviewReason(rationale);
    const succeeded = await act(
      () => api.review(caseId, "correct", guidedCorrections, rationale, detail.latest_extraction_id),
      "Correction saved as extraction v2 and approved by the reviewer.",
    );
    if (succeeded) setTourStep(5);
  };

  const guidedExport = async () => {
    try {
      setBusy(true);
      setError(null);
      setNotice(null);
      let requestError: unknown = null;
      try {
        await api.exportCase(caseId);
      } catch (reason) {
        requestError = reason;
      }
      const updated = await api.getCase(caseId);
      setDetail(updated);
      if (updated.status === "completed") {
        setNotice("The same export operation succeeded without creating a duplicate downstream record.");
        setTourStep(6);
        return;
      }
      const retryableFailure = updated.export_attempts.find((attempt) => attempt.status === "failed" && attempt.retryable);
      if (retryableFailure) {
        setNotice(`Controlled downstream ${retryableFailure.response_status || 429} recorded. Retry uses the same idempotency key.`);
        return;
      }
      setError(requestError instanceof Error ? requestError.message : "The export workflow did not reach the expected retryable state.");
    } finally {
      setBusy(false);
    }
  };

  const handleTourNext = () => {
    if (tourIndex === 4 && !detail?.reviewer_approved) { void guidedReview(); return; }
    if (tourIndex === 5 && detail?.status !== "completed") { void guidedExport(); return; }
    nextTour();
  };

  const latestRetryableFailure = detail?.export_attempts.find((attempt) => attempt.status === "failed" && attempt.retryable);
  const tourNextLabel = busy
    ? "Working…"
    : tourIndex === 4 && !detail?.reviewer_approved
      ? "Apply correction + approve"
      : tourIndex === 5 && detail?.status !== "completed"
        ? latestRetryableFailure
          ? "Retry same export operation →"
          : "Trigger controlled 429 →"
        : tourIndex === 5
          ? "Inspect complete audit trail →"
          : undefined;

  if (!detail) return <main className="shell"><header className="topbar"><Link href="/" className="brand"><span className="brand-mark">I</span><span><strong>IntakeFlow</strong><small>Healthcare Intake AI</small></span></Link></header>{error ? <div className="case-load-error"><div className="alert" role="alert">{error}</div><button onClick={() => void load()}>Retry loading case</button><Link className="button-link secondary" href="/">Return to queue</Link></div> : <div className="loading-page"><span className="spinner" />Loading case workspace…</div>}</main>;

  const canProcess = ["received", "missing_information", "failed"].includes(detail.status) && detail.documents.length > 0;
  const canReview = ["review_required", "ready_for_export"].includes(detail.status);
  const canExport = detail.status === "ready_for_export" && detail.reviewer_approved;
  const currentTourSteps = manifest?.tour || [];
  return <main className="shell case-shell">
    <header className="topbar"><Link href={tourIndex !== null ? "/demo" : "/"} className="brand"><span className="brand-mark">I</span><span><strong>IntakeFlow</strong><small>{tourIndex !== null ? "Guided workspace" : "Healthcare Intake AI"}</small></span></Link><nav className="topnav"><Link href="/proof" data-tour-target="proof-link">Proof</Link><div className="synthetic-note"><span /> Synthetic data only · Not for clinical use</div></nav></header>
    <div className="case-breadcrumb"><Link href={tourIndex !== null ? "/demo" : "/"}>Case queue</Link><span>/</span><strong>{detail.external_reference}</strong></div>
    <section className="case-hero"><div><p className="eyebrow">{detail.scenario ? detail.scenario.replaceAll("-", " ").toUpperCase() : "INTAKE CASE"}</p><h1>{detail.external_reference}</h1><p>Evidence-first administrative workflow · {detail.document_count} attached document{detail.document_count === 1 ? "" : "s"} · extraction v{detail.latest_extraction_version || "—"}</p></div><StatusPill status={detail.status} /></section>
    {error && <div className="alert" role="alert">{error}<button className="alert-retry" onClick={() => void load()}>Retry</button></div>}{notice && <div className="notice" role="status">{notice}</div>}
    <section className="case-layout">
      <div className="case-main">
        <section className="panel" data-tour-target="evidence-viewer"><div className="panel-heading"><div><p className="eyebrow">SOURCE PACKET</p><h2>Evidence viewer</h2></div><span className="step">01</span></div><p className="muted">Rendered pages stay attached to their extraction source. Native text and OCR provenance are explicit.</p><div className="document-tabs">{detail.documents.map((document) => <button className={pageDocument === document.id ? "document-tab document-tab--active" : "document-tab"} key={document.id} onClick={() => { setPageDocument(document.id); setPage(1); }}>{document.original_filename}<small>{document.source_mode} · {document.page_count || 0} page</small></button>)}</div>{pageData ? <div className="page-viewer"><div className="page-toolbar"><span>Page {pageData.page_number}</span><span className="source-badge">{pageData.source_mode === "ocr" ? "OCR" : "NATIVE TEXT"} · {pageData.source_confidence !== null ? `${Math.round(pageData.source_confidence * 100)}% quality` : "verified"}</span><div><button className="icon-button" onClick={() => setPage((current) => Math.max(1, current - 1))} disabled={page <= 1}>←</button><button className="icon-button" onClick={() => setPage((current) => current + 1)} disabled={page >= (detail.documents.find((document) => document.id === pageDocument)?.page_count || 1)}>→</button></div></div><div className="page-canvas">{pageImage ? <div className="page-image-wrap"><img src={pageImage} alt={`Rendered page ${pageData.page_number} from ${detail.documents.find((document) => document.id === pageDocument)?.original_filename || "document"}`} />{detail.latest_record?.fields.flatMap((field) => field.evidence && field.evidence.document_id === pageDocument && field.evidence.page_number === pageData.page_number ? field.evidence.boxes.map((box, index) => <span className="evidence-box" key={`${field.name}-${index}`} style={{ left: `${box.x * 100}%`, top: `${box.y * 100}%`, width: `${box.width * 100}%`, height: `${box.height * 100}%` }} title={labels[field.name] || field.name} />) : [])}</div> : <pre>{pageData.text}</pre>}</div></div> : <div className="empty">No rendered page is available for this document.</div>}</section>
        <section className="panel"><div className="panel-heading"><div><p className="eyebrow">DOCUMENT INTAKE</p><h2>Packet inventory</h2></div><span className="step">02</span></div><p>Public demo workspaces use bundled synthetic packets. Custom synthetic uploads remain an explicit local-development capability.</p>{!detail.workspace_id && meta?.custom_uploads_enabled && <div className="upload-row"><label className="file-button"><input type="file" accept="application/pdf,.pdf" onChange={(event: ChangeEvent<HTMLInputElement>) => setFile(event.target.files?.[0] || null)} />{file ? file.name : "Choose synthetic PDF"}</label><button disabled={busy || !file} onClick={() => void upload()}>Attach document</button><button className="secondary" disabled={busy || !canProcess} onClick={() => void process()}>Process intake</button></div>}<div className="documents">{detail.documents.map((document) => <div key={document.id} className="document-item"><span className="file-icon">PDF</span><div><strong>{document.original_filename}</strong><small>{document.page_count} page{document.page_count === 1 ? "" : "s"} · {Math.max(1, Math.round(document.size_bytes / 1024))} KB · {document.source_mode}</small></div></div>)}</div></section>
        <section className="panel" data-tour-target="decision-trace"><div className="panel-heading"><div><p className="eyebrow">EXTRACTION REVIEW</p><h2>Current record and evidence</h2></div><span className="step">03</span></div>{detail.latest_record ? <div className="extraction-grid">{fields.map((field) => <FieldCard key={field.name} field={field} correction={corrections[field.name] ?? field.value ?? ""} onChange={(value) => setCorrections((current) => ({ ...current, [field.name]: value }))} />)}</div> : <div className="empty"><strong>No extraction yet.</strong><span>Attach and process a packet to generate a structured proposal.</span></div>}</section>
        {detail.validation_issues.length > 0 && <section className="panel issue-panel"><div className="panel-heading"><div><p className="eyebrow">VALIDATION FINDINGS</p><h2>Why this case stopped</h2></div><span className="issue-count">{detail.validation_issues.length} finding{detail.validation_issues.length === 1 ? "" : "s"}</span></div><div className="issues">{detail.validation_issues.map((issue) => <article key={issue.id} className={`issue issue--${issue.severity}`}><span>{issue.severity === "error" ? "!" : "i"}</span><div><strong>{issue.code.replaceAll("_", " ")}</strong><p>{issue.message}</p>{issue.field_name && <small>Field: {labels[issue.field_name] || issue.field_name}</small>}</div></article>)}</div></section>}
      </div>
      <aside className="case-side">
        <section className="panel action-panel" data-tour-target="review-actions"><p className="eyebrow">REVIEWER ACTIONS</p><h2>Human approval gate</h2><p>Workflow status is controlled by explicit reviewer decisions, never by model output.</p><label className="review-rationale" htmlFor="review-rationale"><span>Reviewer rationale</span><textarea id="review-rationale" value={reviewReason} onChange={(event) => setReviewReason(event.target.value)} placeholder="Explain the evidence used for this decision…" rows={3} /></label><button disabled={busy || !canReview || detail.reviewer_approved} onClick={() => void review("approve")}>{detail.reviewer_approved ? "Record approved" : "Approve record"}</button><button className="secondary" disabled={busy || !canReview || Object.keys(changedCorrections).length === 0} onClick={() => void review("correct")}>Save corrections + approve</button><button className="secondary" disabled={busy || !canReview} onClick={() => void review("request_information")}>Request information</button>{detail.scenario === "exception-recovery" && <div className="suggestion"><span>Suggested reconciliation</span><strong>SYN-48219</strong><small>Value on the synthetic insurance card</small><button className="suggestion-action" onClick={() => { setCorrections((current) => ({ ...current, member_identifier: "SYN-48219" })); setReviewReason("Reconciled against the synthetic insurance card in the source packet."); }}>Use this evidence</button></div>}<button className="export-button" data-tour-target="export-inspector" disabled={busy || !canExport} onClick={() => void exportCase()}>{detail.reviewer_approved ? "Export approved record" : "Approve record to unlock export"}</button></section>
        <section className="panel"><p className="eyebrow">MODEL RUN</p><h2>Processing metadata</h2>{detail.model_runs[0] ? <dl className="metadata"><div><dt>Provider</dt><dd>{detail.model_runs[0].provider}</dd></div><div><dt>Model</dt><dd>{detail.model_runs[0].model}</dd></div><div><dt>Route tier</dt><dd>{detail.model_runs[0].route_tier}</dd></div><div><dt>Duration</dt><dd>{detail.model_runs[0].duration_ms ?? "—"} ms</dd></div><div><dt>Extraction</dt><dd>v{detail.latest_extraction_version || 1}</dd></div></dl> : <p className="muted">No model run recorded.</p>}<button className="secondary compare-button" disabled={busy || !meta?.live_model_compare_enabled} onClick={() => void compare()}>{meta?.live_model_compare_enabled ? "Compare optional model run" : "Live comparison disabled"}</button>{!meta?.live_model_compare_enabled && <p className="capability-note">The rules baseline shown above remains authoritative. Live provider calls are opt-in, budgeted, and read-only.</p>}{comparison && <pre className="comparison-output">{JSON.stringify(comparison, null, 2)}</pre>}</section>
        <section className="panel"><p className="eyebrow">EXPORT INSPECTOR</p><h2>Downstream recovery</h2>{detail.export_attempts.length === 0 ? <p className="muted">No export attempt yet. Approval creates the outbox operation.</p> : <div className="attempt-list">{detail.export_attempts.map((attempt) => <details className="attempt" key={attempt.id}><summary><div><strong>Attempt {attempt.attempt_number}</strong><small>{attempt.status} · key {attempt.idempotency_key.slice(0, 14)}…</small></div><span className={`attempt-status attempt-status--${attempt.status}`}>{attempt.response_status || "—"}</span></summary>{attempt.error_message && <p>{attempt.error_message}</p>}<dl className="metadata attempt-metadata"><div><dt>Retry policy</dt><dd>{attempt.retryable ? "Safe to retry" : "Terminal / not retried"}</dd></div><div><dt>Signature</dt><dd>{attempt.request_signature ? `${attempt.request_signature.slice(0, 18)}…` : "—"}</dd></div><div><dt>Downstream ID</dt><dd>{attempt.downstream_record_id || "Not accepted"}</dd></div></dl>{attempt.response_body && <pre className="comparison-output">{JSON.stringify(attempt.response_body, null, 2)}</pre>}</details>)}</div>}</section>
        <section className="panel" data-tour-target="audit-timeline"><p className="eyebrow">AUDIT TIMELINE</p><h2>Workflow trace</h2><ol className="timeline">{detail.events.map((event) => <li key={event.id}><span /><div><strong>{event.event_type.replaceAll("_", " ")}</strong><small>{event.actor} · {timestamp(event.created_at)}</small></div></li>)}</ol></section>
      </aside>
    </section>
    {manifest && tourIndex !== null && <TourCoach steps={currentTourSteps} index={tourIndex} onNext={handleTourNext} onBack={backTour} onClose={closeTour} onRestart={restartTour} nextLabel={tourNextLabel} nextDisabled={busy} />}
  </main>;
}

function FieldCard({ field, correction, onChange }: { field: { name: string; value: string | null | undefined; evidence: ExtractedField["evidence"] }; correction: string; onChange: (value: string) => void }) {
  const changed = correction !== (field.value || "");
  const reviewerGrounded = field.evidence?.provenance === "reviewer";
  return <article className={`field-card ${changed ? "field-card--changed" : ""}`}><label htmlFor={field.name}>{labels[field.name] || field.name}</label>{changed && <small className="original-value">Current record: {field.value || "Not extracted"}</small>}<input id={field.name} value={correction} onChange={(event) => onChange(event.target.value)} placeholder="Not extracted" />{field.evidence ? <div className="evidence">{changed && <small className="evidence-note">Current evidence · pending reviewer correction is recorded separately</small>}<span>p. {field.evidence.page_number} · {field.evidence.source_mode}{field.evidence.document_id ? ` · ${field.evidence.document_id.slice(0, 8)}` : ""}</span><q>{field.evidence.quote}</q><small>{reviewerGrounded ? "Reviewer-grounded exact match" : `${Math.round(field.evidence.confidence * 100)}% extraction confidence`}{field.evidence.source_confidence !== null && field.evidence.source_confidence !== undefined ? ` · ${Math.round(field.evidence.source_confidence * 100)}% source quality` : ""}{field.evidence.boxes.length > 0 ? " · highlighted on page" : ""}</small></div> : <div className="no-evidence">{changed ? "Pending reviewer value has no source match" : "No supporting evidence"}</div>}</article>;
}
