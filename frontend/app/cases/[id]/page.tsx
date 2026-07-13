"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { ChangeEvent, useEffect, useMemo, useState } from "react";
import { api, CaseDetail, ExtractedField } from "@/lib/api";
import { StatusPill } from "@/components/status-pill";

const labels: Record<string, string> = {
  case_reference: "Case reference",
  member_identifier: "Member identifier",
  requesting_organization: "Requesting organization",
  requesting_contact: "Requesting contact",
  service_code: "Service code",
  requested_start_date: "Requested start date",
};

function timestamp(value?: string) {
  return value ? new Intl.DateTimeFormat("en", { dateStyle: "medium", timeStyle: "short" }).format(new Date(value)) : "—";
}

export default function CasePage() {
  const params = useParams<{ id: string }>();
  const caseId = params.id;
  const [detail, setDetail] = useState<CaseDetail | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [corrections, setCorrections] = useState<Record<string, string | null>>({});

  const load = async () => {
    try { setDetail(await api.getCase(caseId)); setError(null); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "Unable to load case."); }
  };
  useEffect(() => {
    let active = true;
    void api.getCase(caseId)
      .then((item) => { if (active) { setDetail(item); setError(null); } })
      .catch((reason: unknown) => { if (active) setError(reason instanceof Error ? reason.message : "Unable to load case."); });
    return () => { active = false; };
  }, [caseId]);

  const fields = useMemo(() => {
    const fieldsByName = new Map((detail?.latest_record?.fields || []).map((field) => [field.name, field]));
    return Object.keys(labels).map((name) => ({ name, value: detail?.latest_record?.[name as keyof NonNullable<CaseDetail["latest_record"]>] as string | null | undefined, evidence: fieldsByName.get(name)?.evidence || null }));
  }, [detail]);

  const act = async (action: () => Promise<unknown>, message: string) => {
    try { setBusy(true); setNotice(null); await action(); setNotice(message); await load(); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "Workflow action failed."); }
    finally { setBusy(false); }
  };

  const upload = async () => {
    if (!file) { setError("Choose a synthetic text-based PDF first."); return; }
    await act(async () => { await api.upload(caseId, file); setFile(null); }, "Document attached. Start processing when ready.");
  };

  const process = async () => act(() => api.process(caseId), "Processing completed through the deterministic demo pipeline.");
  const review = async (action: "approve" | "correct" | "request_information") => act(() => api.review(caseId, action, corrections, action === "request_information" ? "Please supply the missing administrative details." : undefined), action === "request_information" ? "Case routed to missing information." : "Reviewer decision recorded.");
  const exportCase = async () => act(() => api.exportCase(caseId), "Mock downstream export accepted.");

  if (!detail) return <main className="shell"><div className="loading-page">Loading case workspace…</div></main>;
  const canProcess = ["received", "missing_information", "failed"].includes(detail.status) && detail.documents.length > 0;
  const canReview = ["review_required", "ready_for_export"].includes(detail.status);
  const canExport = detail.status === "ready_for_export" && detail.reviewer_approved;

  return (
    <main className="shell case-shell">
      <header className="topbar"><Link href="/" className="brand"><span className="brand-mark">I</span><div><strong>IntakeFlow</strong><small>Healthcare Intake AI</small></div></Link><div className="synthetic-note"><span /> Synthetic data only · Not for clinical use</div></header>
      <div className="case-breadcrumb"><Link href="/">Case queue</Link><span>/</span><strong>{detail.external_reference}</strong></div>
      <section className="case-hero"><div><p className="eyebrow">INTAKE CASE</p><h1>{detail.external_reference}</h1><p>Evidence-first administrative workflow · {detail.document_count} attached document{detail.document_count === 1 ? "" : "s"}</p></div><StatusPill status={detail.status} /></section>
      {error && <div className="alert">{error}</div>}{notice && <div className="notice">{notice}</div>}
      <section className="case-layout">
        <div className="case-main">
          <section className="panel"><div className="panel-heading"><div><p className="eyebrow">DOCUMENT INTAKE</p><h2>Attach and process a packet</h2></div><span className="step">01</span></div><p>Only synthetic, digitally generated PDFs with extractable text are accepted.</p><div className="upload-row"><label className="file-button"><input type="file" accept="application/pdf,.pdf" onChange={(event: ChangeEvent<HTMLInputElement>) => setFile(event.target.files?.[0] || null)} />{file ? file.name : "Choose synthetic PDF"}</label><button disabled={busy || !file} onClick={() => void upload()}>Attach document</button><button className="secondary" disabled={busy || !canProcess} onClick={() => void process()}>Process intake</button></div>{detail.documents.length > 0 && <div className="documents">{detail.documents.map((document) => <div key={document.id} className="document-item"><span className="file-icon">PDF</span><div><strong>{document.original_filename}</strong><small>{document.page_count} page{document.page_count === 1 ? "" : "s"} · {Math.max(1, Math.round(document.size_bytes / 1024))} KB</small></div></div>)}</div>}</section>
          <section className="panel"><div className="panel-heading"><div><p className="eyebrow">EXTRACTION REVIEW</p><h2>Proposed record and evidence</h2></div><span className="step">02</span></div>{detail.latest_record ? <div className="extraction-grid">{fields.map((field) => <FieldCard key={field.name} field={field} correction={corrections[field.name] ?? field.value ?? ""} onChange={(value) => setCorrections((current) => ({ ...current, [field.name]: value }))} />)}</div> : <div className="empty"><strong>No extraction yet.</strong><span>Attach and process a packet to generate a structured proposal.</span></div>}</section>
          {detail.validation_issues.length > 0 && <section className="panel issue-panel"><div className="panel-heading"><div><p className="eyebrow">VALIDATION FINDINGS</p><h2>Why this case was routed</h2></div><span className="step">03</span></div><div className="issues">{detail.validation_issues.map((issue) => <article key={issue.id} className={`issue issue--${issue.severity}`}><span>{issue.severity === "error" ? "!" : "i"}</span><div><strong>{issue.code.replaceAll("_", " ")}</strong><p>{issue.message}</p>{issue.field_name && <small>Field: {labels[issue.field_name] || issue.field_name}</small>}</div></article>)}</div></section>}
        </div>
        <aside className="case-side">
          <section className="panel action-panel"><p className="eyebrow">REVIEWER ACTIONS</p><h2>Human approval gate</h2><p>Workflow status is controlled by explicit reviewer decisions, never by model output.</p><button disabled={busy || !canReview} onClick={() => void review("approve")}>{detail.reviewer_approved ? "Record approved" : "Approve record"}</button><button className="secondary" disabled={busy || !canReview} onClick={() => void review("correct")}>Save corrections + approve</button><button className="secondary" disabled={busy || !canReview} onClick={() => void review("request_information")}>Request information</button><button className="export-button" disabled={busy || !canExport} onClick={() => void exportCase()}>{detail.reviewer_approved ? "Approve mock export" : "Approve record to unlock export"}</button></section>
          <section className="panel"><p className="eyebrow">MODEL RUN</p><h2>Processing metadata</h2>{detail.model_runs[0] ? <dl className="metadata"><div><dt>Provider</dt><dd>{detail.model_runs[0].provider}</dd></div><div><dt>Model</dt><dd>{detail.model_runs[0].model}</dd></div><div><dt>Route tier</dt><dd>{detail.model_runs[0].route_tier}</dd></div><div><dt>Duration</dt><dd>{detail.model_runs[0].duration_ms ?? "—"} ms</dd></div></dl> : <p className="muted">No model run recorded.</p>}</section>
          <section className="panel"><p className="eyebrow">AUDIT TIMELINE</p><h2>Workflow trace</h2><ol className="timeline">{detail.events.map((event) => <li key={event.id}><span /><div><strong>{event.event_type.replaceAll("_", " ")}</strong><small>{event.actor} · {timestamp(event.created_at)}</small></div></li>)}</ol></section>
        </aside>
      </section>
    </main>
  );
}

function FieldCard({ field, correction, onChange }: { field: { name: string; value: string | null | undefined; evidence: ExtractedField["evidence"] }; correction: string; onChange: (value: string) => void }) {
  return <article className="field-card"><label htmlFor={field.name}>{labels[field.name]}</label><input id={field.name} value={correction} onChange={(event) => onChange(event.target.value)} placeholder="Not extracted" />{field.evidence ? <div className="evidence"><span>p. {field.evidence.page_number}</span><q>{field.evidence.quote}</q><small>{Math.round(field.evidence.confidence * 100)}% confidence</small></div> : <div className="no-evidence">No supporting evidence</div>}</article>;
}
