"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { FormEvent, useEffect, useMemo, useState } from "react";
import { api, CaseSummary, EvalRun } from "@/lib/api";
import { StatusPill } from "@/components/status-pill";

function date(value?: string) {
  return value ? new Intl.DateTimeFormat("en", { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }).format(new Date(value)) : "—";
}

export default function Dashboard() {
  const router = useRouter();
  const [cases, setCases] = useState<CaseSummary[]>([]);
  const [reference, setReference] = useState("");
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [evalRun, setEvalRun] = useState<EvalRun | null>(null);

  const refresh = async () => {
    try { setLoading(true); setCases(await api.listCases()); setError(null); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "Unable to load cases."); }
    finally { setLoading(false); }
  };
  useEffect(() => {
    let active = true;
    void api.listCases()
      .then((items) => { if (active) { setCases(items); setError(null); } })
      .catch((reason: unknown) => { if (active) setError(reason instanceof Error ? reason.message : "Unable to load cases."); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, []);

  const metrics = useMemo(() => ({
    active: cases.filter((item) => !["completed", "failed"].includes(item.status)).length,
    review: cases.filter((item) => item.status === "review_required").length,
    ready: cases.filter((item) => item.status === "ready_for_export").length,
    completed: cases.filter((item) => item.status === "completed").length,
  }), [cases]);

  async function createCase(event: FormEvent) {
    event.preventDefault();
    if (!reference.trim()) return;
    try { setCreating(true); const created = await api.createCase(reference.trim()); setReference(""); await refresh(); router.push(`/cases/${created.id}`); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "Unable to create case."); }
    finally { setCreating(false); }
  }

  async function runEvaluation() {
    try { setEvalRun(await api.runEval("development")); setError(null); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "Evaluation failed."); }
  }

  async function seedDemo() {
    try { setCreating(true); const created = await api.seedDemo(); await refresh(); router.push(`/cases/${created.id}`); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "Unable to load the synthetic demo."); }
    finally { setCreating(false); }
  }

  return (
    <main className="shell">
      <header className="topbar">
        <div className="brand"><span className="brand-mark">I</span><div><strong>IntakeFlow</strong><small>Healthcare Intake AI</small></div></div>
        <div className="synthetic-note"><span /> Synthetic data only · Not for clinical use</div>
      </header>
      <section className="hero">
        <div><p className="eyebrow">OPERATIONS CONTROL</p><h1>Make every intake decision<br /><em>traceable and reviewable.</em></h1><p className="hero-copy">A calm, evidence-first workspace for synthetic administrative packets. Models propose. Deterministic rules and people decide.</p></div>
        <div className="hero-card"><span className="hero-card__label">WORKFLOW PRINCIPLE</span><p>“Extract with evidence. Validate with rules. Export with approval.”</p><div className="hero-card__steps"><span>01 Intake</span><span>02 Validate</span><span>03 Review</span></div></div>
      </section>
      <section className="metrics">
        <article><span>Active cases</span><strong>{metrics.active}</strong><small>In flight across the workflow</small></article>
        <article><span>Review queue</span><strong>{metrics.review}</strong><small>Human decision required</small></article>
        <article><span>Ready to export</span><strong>{metrics.ready}</strong><small>Awaiting explicit approval</small></article>
        <article><span>Completed</span><strong>{metrics.completed}</strong><small>Mock downstream accepted</small></article>
      </section>
      <section className="workspace-grid">
        <div className="panel intake-panel"><div className="panel-heading"><div><p className="eyebrow">NEW CASE</p><h2>Start an intake workflow</h2></div><span className="step">01</span></div><p>Create a synthetic case, attach a text-based PDF, and process it through the evidence-first routing workflow.</p><form onSubmit={createCase}><label htmlFor="reference">Case reference</label><div className="input-row"><input id="reference" value={reference} onChange={(event) => setReference(event.target.value)} placeholder="e.g. INTAKE-2026-001" /><button disabled={creating}>{creating ? "Creating…" : "Create case"}</button></div></form><button className="demo-button" disabled={creating} onClick={() => void seedDemo()}>Load a complete synthetic demo →</button></div>
        <div className="panel eval-panel"><div className="panel-heading"><div><p className="eyebrow">QUALITY GATE</p><h2>Evaluate extraction &amp; routing</h2></div><span className="step">02</span></div><p>Run the development benchmark through the real extraction and routing pipeline to keep workflow behavior visible and reproducible.</p><button className="secondary" onClick={() => void runEvaluation()}>Run development evaluation</button>{evalRun && <div className="eval-result"><strong>{Math.round(evalRun.routing_accuracy * 100)}%</strong><span>{evalRun.matched_cases} of {evalRun.total_cases} cases routed correctly · {Math.round(evalRun.field_accuracy * 100)}% field accuracy</span></div>}</div>
      </section>
      <section className="table-panel"><div className="panel-heading"><div><p className="eyebrow">CASE QUEUE</p><h2>Intake operations</h2></div><button className="text-button" onClick={() => void refresh()}>Refresh</button></div>{error && <div className="alert">{error}</div>}{loading ? <div className="empty">Loading workflow state…</div> : cases.length === 0 ? <div className="empty"><strong>Your queue is clear.</strong><span>Create a synthetic intake case to begin.</span></div> : <div className="case-table"><div className="table-head"><span>Case</span><span>State</span><span>Documents</span><span>Last activity</span><span /></div>{cases.map((item) => <Link href={`/cases/${item.id}`} className="case-row" key={item.id}><div><strong>{item.external_reference}</strong><small>{item.source}</small></div><StatusPill status={item.status} /><span>{item.document_count} file{item.document_count === 1 ? "" : "s"}</span><span>{date(item.updated_at || item.created_at)}</span><span className="arrow">→</span></Link>)}</div>}</section>
    </main>
  );
}
