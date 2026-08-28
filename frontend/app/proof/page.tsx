"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { api, EvalRun, Meta, Proof } from "@/lib/api";

const proofCards = [
  { label: "Model boundary", value: "Extract only", detail: "Provider output is untrusted. Deterministic policy owns routing and export." },
  { label: "Evidence trail", value: "Page + quote", detail: "Model proposals and exact reviewer matches point to the source; ungrounded overrides stay explicit." },
  { label: "Human gate", value: "Required", detail: "A versioned reviewer decision unlocks downstream export." },
  { label: "Recovery", value: "Exactly once", detail: "The same idempotency key safely survives a retryable failure." },
];

export default function ProofPage() {
  const [meta, setMeta] = useState<Meta | null>(null);
  const [evalRun, setEvalRun] = useState<EvalRun | null>(null);
  const [proof, setProof] = useState<Proof | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    void Promise.all([api.meta(), api.proof()])
      .then(([nextMeta, nextProof]) => { setMeta(nextMeta); setProof(nextProof); setEvalRun(nextProof.latest_evaluation || null); })
      .catch((reason: unknown) => setError(reason instanceof Error ? reason.message : "Proof data is unavailable until the API is running."));
  }, []);

  const challengeResults = evalRun?.results.filter((result) => !result.matched).slice(0, 3) || [];
  const frontendCommit =
    [meta?.frontend_commit_sha, proof?.frontend_commit_sha].find(
      (value) => value && value !== "unknown" && value !== "local",
    ) ||
    process.env.NEXT_PUBLIC_GIT_SHA ||
    "Not reported";
  return <main className="shell proof-shell">
    <header className="topbar"><Link href="/" className="brand"><span className="brand-mark">I</span><span><strong>IntakeFlow</strong><small>Technical proof</small></span></Link><nav className="topnav"><Link href="/demo">Live demo</Link><Link href="/">Home</Link></nav></header>
    <section className="proof-hero"><p className="eyebrow">RECRUITER PROOF SURFACE</p><h1>A trustworthy workflow is<br /><em>more than a model call.</em></h1><p>These are the engineering decisions behind the IntakeFlow demo: explicit boundaries, measurable behavior, and failure paths that remain safe to retry.</p><div className="hero-actions"><Link className="button-link" href="/demo">Launch the live workspace →</Link><a className="button-link secondary" href="https://github.com/BMcCarthy96/healthcare-intake-ai" target="_blank" rel="noreferrer">Read the source</a><a className="button-link secondary" href="https://github.com/BMcCarthy96/healthcare-intake-ai/actions/workflows/ci.yml" target="_blank" rel="noreferrer">Inspect CI runs</a></div></section>
    <section className="proof-grid">{proofCards.map((card) => <article className="proof-card" key={card.label}><span>{card.label}</span><strong>{card.value}</strong><p>{card.detail}</p></article>)}</section>
    <section className="panel proof-panel"><div className="panel-heading"><div><p className="eyebrow">ARCHITECTURE TRAIL</p><h2>Document → evidence → policy → action</h2></div><span className="proof-status"><i /> synthetic-only</span></div><div className="architecture-flow"><div><b>01</b><strong>Ingest</strong><span>PDF validation<br />native text or OCR</span></div><div className="flow-arrow">→</div><div><b>02</b><strong>Propose</strong><span>Typed fields<br />page evidence</span></div><div className="flow-arrow">→</div><div><b>03</b><strong>Validate</strong><span>Rules, conflicts<br />prompt injection</span></div><div className="flow-arrow">→</div><div><b>04</b><strong>Review</strong><span>Versioned correction<br />explicit approval</span></div><div className="flow-arrow">→</div><div><b>05</b><strong>Export</strong><span>Outbox, retry<br />audit event</span></div></div></section>
    <section className="proof-columns"><div className="panel"><div className="panel-heading"><div><p className="eyebrow">MEASURED QUALITY</p><h2>Evaluation scoreboard</h2></div><span className="proof-status"><i /> locked challenge suite</span></div>{error ? <div className="alert">{error}</div> : evalRun ? <><div className="score-row"><div><strong>{Math.round(evalRun.routing_accuracy * 100)}%</strong><span>routing accuracy</span></div><div><strong>{Math.round(evalRun.field_accuracy * 100)}%</strong><span>field accuracy</span></div><div><strong>{Math.round(evalRun.routing_macro_f1 * 100)}%</strong><span>routing macro-F1</span></div><div><strong>{evalRun.false_ready_count}</strong><span>false-ready cases</span></div></div><div className="proof-metric-row"><span>Evidence validity <strong>{Math.round(evalRun.evidence_validity * 100)}%</strong></span><span>Field macro-F1 <strong>{Math.round(evalRun.field_macro_f1 * 100)}%</strong></span></div><div className="bar-chart">{evalRun.results.slice(0, 12).map((result, index) => <div key={result.case_id} className={result.matched ? "bar bar--pass" : "bar bar--fail"} style={{ height: `${Math.max(18, result.fields_compared ? (result.fields_matched / result.fields_compared) * 100 : result.matched ? 100 : 18)}%` }} title={result.case_id} aria-label={`${result.case_id}: ${result.matched ? "pass" : "fail"}`}><span>{index + 1}</span></div>)}</div>{challengeResults.length > 0 && <p className="muted">Latest run includes visible challenge failures for inspection—not a hidden green score.</p>}</> : <div className="empty"><span>The deployment has not persisted its locked challenge evaluation yet.</span></div>}</div><div className="panel"><div className="panel-heading"><div><p className="eyebrow">BUILD PROVENANCE</p><h2>What is running</h2></div></div><dl className="metadata proof-metadata"><div><dt>API version</dt><dd>{meta?.app_version || "Loading…"}</dd></div><div><dt>API commit</dt><dd>{meta?.api_commit_sha || proof?.commit_sha || "Not reported"}</dd></div><div><dt>Frontend commit</dt><dd>{frontendCommit}</dd></div><div><dt>Build time</dt><dd>{meta?.build_time || proof?.build_time || process.env.NEXT_PUBLIC_BUILD_TIME || "Not reported"}</dd></div><div><dt>Record schema</dt><dd>{meta?.schema_version || proof?.schema_version || "intake-record/2"}</dd></div><div><dt>Demo scenario</dt><dd>{meta?.demo_scenario_version || proof?.demo_scenario_version || "v2"}</dd></div><div><dt>Provider</dt><dd>{proof?.provider === "stub" ? "Rules baseline" : proof?.provider || "Not reported"}</dd></div><div><dt>Data policy</dt><dd>Synthetic only</dd></div></dl><div className="proof-gates">{Object.entries(proof?.quality_gates || {}).map(([name, passed]) => <span className={passed ? "gate gate--pass" : "gate gate--fail"} key={name}>{passed ? "✓" : "!"} {name.replaceAll("_", " ")}</span>)}</div><div className="proof-note">This page reads the persisted locked challenge evaluation. CI independently regenerates the same gates and publishes the machine-readable proof artifact.</div></div></section>
    <section className="panel limitations"><p className="eyebrow">INTENTIONAL LIMITS</p><h2>What this project does not claim</h2><div className="limit-list"><span>× No diagnosis, treatment, urgency, or coverage decisions.</span><span>× No real patient data or production EHR connection.</span><span>× No HIPAA-compliance claim; the public environment is synthetic and TTL-scoped.</span><span>× Live model comparison is optional and never authoritative.</span></div></section>
    <footer className="site-footer"><span>Proof generated from the running system</span><span>Models propose · rules decide · people approve</span></footer>
  </main>;
}
