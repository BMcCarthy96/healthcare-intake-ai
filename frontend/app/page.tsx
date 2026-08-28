"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { FormEvent, useEffect, useMemo, useState } from "react";
import { StatusPill } from "@/components/status-pill";
import { api, CaseSummary, EvalRun, Meta, setDemoSession } from "@/lib/api";

function date(value?: string) {
  return value ? new Intl.DateTimeFormat("en", { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }).format(new Date(value)) : "—";
}

export default function Dashboard() {
  const router = useRouter();
  const [cases, setCases] = useState<CaseSummary[]>([]);
  const [reference, setReference] = useState("");
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);
  const [startingDemo, setStartingDemo] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [evalRun, setEvalRun] = useState<EvalRun | null>(null);
  const [meta, setMeta] = useState<Meta | null>(null);

  const refresh = async () => {
    try {
      setLoading(true);
      setCases(await api.listCases());
      setError(null);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Unable to load workflow state.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    let active = true;
    void api.listCases()
      .then((items) => { if (active) { setCases(items); setError(null); } })
      .catch((reason: unknown) => { if (active) setError(reason instanceof Error ? reason.message : "Unable to load workflow state."); })
      .finally(() => { if (active) setLoading(false); });
    void api.meta().then((item) => { if (active) setMeta(item); }).catch(() => undefined);
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
    try {
      setCreating(true);
      const created = await api.createCase(reference.trim());
      setReference("");
      await refresh();
      router.push(`/cases/${created.id}`);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Unable to create case.");
    } finally {
      setCreating(false);
    }
  }

  async function startWalkthrough() {
    try {
      setStartingDemo(true);
      const session = await api.startDemo();
      setDemoSession(session);
      router.push("/demo");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Unable to start the isolated walkthrough.");
    } finally {
      setStartingDemo(false);
    }
  }

  async function runEvaluation(dataset: "development" | "challenge") {
    try {
      setEvalRun(await api.runEval(dataset));
      setError(null);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Evaluation failed.");
    }
  }

  async function seedDemo() {
    try {
      setCreating(true);
      const created = await api.seedDemo();
      await refresh();
      router.push(`/cases/${created.id}`);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Unable to load the synthetic demo.");
    } finally {
      setCreating(false);
    }
  }

  return (
    <main className="shell">
      <header className="topbar">
        <Link href="/" className="brand"><span className="brand-mark">I</span><span><strong>IntakeFlow</strong><small>Healthcare Intake AI</small></span></Link>
        <nav className="topnav" aria-label="Primary navigation"><Link href="/demo">Live demo</Link><Link href="/proof">Technical proof</Link><span className="synthetic-note"><span /> Synthetic data only · Not for clinical use</span></nav>
      </header>

      <section className="hero hero--landing">
        <div className="hero-copy-block"><p className="eyebrow">EVIDENCE-FIRST OPERATIONS CONTROL</p><h1>Make every intake decision <em>traceable and reviewable.</em></h1><p className="hero-copy">IntakeFlow turns synthetic administrative packets into reviewable workflow proposals. Models extract. Rules validate. People approve.</p><div className="hero-actions"><button data-tour-target="start-walkthrough" onClick={() => void startWalkthrough()} disabled={startingDemo}>{startingDemo ? "Provisioning workspace…" : "Start 90-second walkthrough →"}</button><Link className="button-link secondary" href="/proof">See how it is built</Link></div><div className="trust-row"><span>✓ Deterministic routing</span><span>✓ Page-level evidence</span><span>✓ Idempotent exports</span></div></div>
        <div className="hero-card hero-card--story"><span className="hero-card__label">THE FLAGSHIP SCENARIO</span><strong>Uncertain packet → human decision → safe recovery</strong><p>A contradictory synthetic packet is caught, corrected with evidence, and exported exactly once—even after a downstream rate limit.</p><div className="hero-card__steps"><span>01 Ground</span><span>02 Review</span><span>03 Prove</span></div></div>
      </section>

      <section className="feature-strip" aria-label="Capabilities"><article><span className="feature-icon">01</span><div><strong>Untrusted by default</strong><p>Document text can propose fields, never workflow instructions.</p></div></article><article><span className="feature-icon">02</span><div><strong>Human control</strong><p>Exceptions require a versioned reviewer decision before export.</p></div></article><article><span className="feature-icon">03</span><div><strong>Measured quality</strong><p>Evaluation, audit, and deployment proof stay visible.</p></div></article></section>

      <section className="metrics" aria-label="Workflow metrics"><article><span>Active cases</span><strong>{metrics.active}</strong><small>In flight across the workflow</small></article><article><span>Review queue</span><strong>{metrics.review}</strong><small>Human decision required</small></article><article><span>Ready to export</span><strong>{metrics.ready}</strong><small>Awaiting explicit approval</small></article><article><span>Completed</span><strong>{metrics.completed}</strong><small>Mock downstream accepted</small></article></section>

      <section className="workspace-grid">
        {meta?.custom_uploads_enabled ? <div className="panel intake-panel"><div className="panel-heading"><div><p className="eyebrow">LOCAL PLAYGROUND</p><h2>Start an intake workflow</h2></div><span className="step">01</span></div><p>Create a synthetic case, attach a packet, and inspect the same evidence-first workflow used by the walkthrough.</p><form onSubmit={createCase}><label htmlFor="reference">Case reference</label><div className="input-row"><input id="reference" value={reference} onChange={(event) => setReference(event.target.value)} placeholder="e.g. INTAKE-2026-001" /><button disabled={creating}>{creating ? "Creating…" : "Create case"}</button></div></form><button className="demo-button" disabled={creating} onClick={() => void seedDemo()}>Load a complete synthetic demo →</button></div> : <div className="panel"><div className="panel-heading"><div><p className="eyebrow">CANONICAL STORY</p><h2>Follow the exception, not a toy upload</h2></div><span className="step">01</span></div><p>The public experience uses five bundled synthetic packets so every recruiter sees the same contradiction, evidence, correction, controlled failure, and safe retry.</p><button onClick={() => void startWalkthrough()} disabled={startingDemo}>{startingDemo ? "Provisioning workspace…" : "Launch isolated walkthrough →"}</button></div>}
        {meta?.evaluation_runs_enabled ? <div className="panel eval-panel"><div className="panel-heading"><div><p className="eyebrow">QUALITY GATE</p><h2>Evaluate the real pipeline</h2></div><span className="step">02</span></div><p>Run the extraction and deterministic routing benchmark, including the locked challenge set, before trusting a provider change.</p><div className="button-row"><button className="secondary" onClick={() => void runEvaluation("development")}>Development run</button><button className="secondary" onClick={() => void runEvaluation("challenge")}>Challenge run</button></div>{evalRun && <div className="eval-result"><strong>{Math.round(evalRun.routing_accuracy * 100)}%</strong><span>{evalRun.matched_cases} of {evalRun.total_cases} routed correctly · {Math.round(evalRun.field_accuracy * 100)}% field accuracy</span></div>}</div> : <div className="panel"><div className="panel-heading"><div><p className="eyebrow">MEASURED PROOF</p><h2>Quality gates run in CI</h2></div><span className="step">02</span></div><p>Public evaluation writes are disabled. The proof surface reads the persisted locked challenge run, while CI regenerates and publishes the complete machine-readable artifact.</p><Link className="button-link secondary" href="/proof">Inspect technical proof →</Link></div>}
      </section>

      <section className="table-panel panel" data-tour-target="demo-queue"><div className="panel-heading"><div><p className="eyebrow">CASE QUEUE</p><h2>Intake operations</h2></div><button className="text-button" onClick={() => void refresh()}>Refresh</button></div>{error && <div className="alert" role="alert">{error}<button className="alert-retry" onClick={() => void refresh()}>Try again</button></div>}{loading ? <div className="empty"><span className="spinner" />Loading workflow state…</div> : cases.length === 0 ? <div className="empty"><strong>Your queue is clear.</strong><span>Create a synthetic intake case or launch the isolated demo.</span></div> : <div className="case-table"><div className="table-head"><span>Case</span><span>State</span><span>Documents</span><span>Last activity</span><span /></div>{cases.map((item) => <Link href={`/cases/${item.id}`} className="case-row" key={item.id}><div><strong>{item.external_reference}</strong><small>{item.scenario || item.source}</small></div><StatusPill status={item.status} /><span>{item.document_count} file{item.document_count === 1 ? "" : "s"}</span><span>{date(item.updated_at || item.created_at)}</span><span className="arrow">→</span></Link>)}</div>}</section>
      <footer className="site-footer"><span>IntakeFlow · synthetic administrative workflow</span><span>Models propose · rules decide · people approve</span></footer>
    </main>
  );
}
