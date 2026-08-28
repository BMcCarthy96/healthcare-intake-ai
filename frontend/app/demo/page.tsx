"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { StatusPill } from "@/components/status-pill";
import { TourCoach } from "@/components/tour-coach";
import { ApiError, api, CaseSummary, clearDemoSession, DemoManifest, setDemoSession } from "@/lib/api";

function timeInState(value?: string) {
  if (!value) return "activity unknown";
  const minutes = Math.max(0, Math.round((Date.now() - new Date(value).getTime()) / 60000));
  if (minutes < 2) return "updated just now";
  if (minutes < 60) return `${minutes}m in state`;
  const hours = Math.round(minutes / 60);
  return `${hours}h in state`;
}

export default function DemoPage() {
  const router = useRouter();
  const bootstrapStarted = useRef(false);
  const provisionInFlight = useRef<Promise<void> | null>(null);
  const [manifest, setManifest] = useState<DemoManifest | null>(null);
  const [cases, setCases] = useState<CaseSummary[]>([]);
  const [index, setIndex] = useState(() => {
    if (typeof window === "undefined") return 0;
    const stored = window.sessionStorage.getItem("intakeflow-tour-step");
    return stored ? Number.parseInt(stored, 10) || 0 : 0;
  });
  const [loading, setLoading] = useState(true);
  const [tourActive, setTourActive] = useState(() => {
    if (typeof window === "undefined") return true;
    return window.sessionStorage.getItem("intakeflow-tour-paused") !== "true";
  });
  const [error, setError] = useState<string | null>(null);
  const [queueQuery, setQueueQuery] = useState("");
  const [queueStatus, setQueueStatus] = useState("all");
  const [queueRisk, setQueueRisk] = useState("all");

  const load = useCallback(async () => {
    try {
      setLoading(true);
      const [nextManifest, nextCases] = await Promise.all([api.manifest(), api.listCases()]);
      setManifest(nextManifest);
      setCases(nextCases);
      setError(null);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Unable to load the demo workspace.");
      throw reason;
    } finally {
      setLoading(false);
    }
  }, []);

  const provision = useCallback(() => {
    if (provisionInFlight.current) return provisionInFlight.current;
    setLoading(true);
    setError(null);
    setManifest(null);
    setCases([]);
    clearDemoSession();
    const task = (async () => {
      try {
        const session = await api.startDemo();
        setDemoSession(session);
        setIndex(0);
        setTourActive(true);
        await load();
      } catch (reason) {
        setError(reason instanceof Error ? reason.message : "Unable to provision the demo workspace.");
        setLoading(false);
        throw reason;
      }
    })();
    provisionInFlight.current = task;
    void task.then(
      () => { if (provisionInFlight.current === task) provisionInFlight.current = null; },
      () => { if (provisionInFlight.current === task) provisionInFlight.current = null; },
    );
    return task;
  }, [load]);

  useEffect(() => {
    if (bootstrapStarted.current) return;
    bootstrapStarted.current = true;
    if (!window.sessionStorage.getItem("intakeflow-demo-token")) {
      // The async bootstrap synchronizes the remote session after mount.
      void provision().catch((reason: unknown) => { setError(reason instanceof Error ? reason.message : "Unable to provision the demo workspace."); setLoading(false); });
    } else {
      // The async bootstrap synchronizes the remote session after mount.
      // eslint-disable-next-line react-hooks/set-state-in-effect
      void load().catch((reason: unknown) => {
        if (reason instanceof ApiError && [401, 410].includes(reason.status)) {
          void provision().catch((retryReason: unknown) => {
            setError(retryReason instanceof Error ? retryReason.message : "Unable to provision the demo workspace.");
          });
        }
      });
    }
  }, [load, provision]);

  const setTourIndex = useCallback((next: number) => {
    const bounded = Math.max(0, Math.min((manifest?.tour.length || 1) - 1, next));
    setIndex(bounded);
    window.sessionStorage.setItem("intakeflow-tour-step", String(bounded));
  }, [manifest?.tour.length]);

  const recommended = useMemo(() => cases.find((item) => item.scenario === "exception-recovery") || cases[0], [cases]);
  const visibleCases = useMemo(() => cases.filter((item) => {
    const matchesQuery = !queueQuery || item.external_reference.toLowerCase().includes(queueQuery.toLowerCase()) || (item.scenario || "").includes(queueQuery.toLowerCase());
    const matchesStatus = queueStatus === "all" || item.status === queueStatus;
    const highRisk = ["review_required", "failed", "exporting"].includes(item.status);
    const mediumRisk = ["missing_information", "queued", "processing"].includes(item.status);
    const matchesRisk = queueRisk === "all" || (queueRisk === "high" && highRisk) || (queueRisk === "medium" && mediumRisk) || (queueRisk === "low" && !highRisk && !mediumRisk);
    return matchesQuery && matchesStatus && matchesRisk;
  }), [cases, queueQuery, queueRisk, queueStatus]);
  const queueMetrics = useMemo(() => ({
    review: cases.filter((item) => item.status === "review_required").length,
    missing: cases.filter((item) => item.status === "missing_information").length,
    ready: cases.filter((item) => item.status === "ready_for_export").length,
    completed: cases.filter((item) => item.status === "completed").length,
  }), [cases]);

  async function retryLoad() {
    try {
      await load();
    } catch (reason) {
      if (reason instanceof ApiError && [401, 410].includes(reason.status)) await provision();
    }
  }

  async function reset() {
    try {
      setLoading(true);
      const next = await api.resetDemo();
      setManifest(next);
      setCases(await api.listCases());
      setTourIndex(0);
      setTourActive(true);
      window.sessionStorage.removeItem("intakeflow-tour-paused");
      setError(null);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Unable to reset the demo workspace.");
    } finally {
      setLoading(false);
    }
  }

  function openRecommended() {
    if (!recommended) return;
    setTourIndex(2);
    router.push(`/demo/cases/${recommended.id}`);
  }

  if (loading && !manifest) return <main className="shell"><div className="loading-page"><span className="spinner" />Provisioning your isolated synthetic workspace…</div></main>;
  if (!manifest) return <main className="shell"><header className="topbar"><Link href="/" className="brand"><span className="brand-mark">I</span><span><strong>IntakeFlow</strong><small>Live synthetic workspace</small></span></Link></header><div className="case-load-error"><div className="alert" role="alert">{error || "The demo workspace could not be loaded."}</div><button onClick={() => { void provision().catch(() => undefined); }}>Start fresh workspace</button><Link className="button-link secondary" href="/">Return home</Link></div></main>;
  return <main className="shell demo-shell">
    <header className="topbar"><Link href="/" className="brand"><span className="brand-mark">I</span><span><strong>IntakeFlow</strong><small>Live synthetic workspace</small></span></Link><nav className="topnav"><Link href="/proof">Technical proof</Link><button className="text-button" onClick={() => void reset()}>Reset workspace</button></nav></header>
    <div className="demo-banner"><div><span className="live-dot" /> ISOLATED DEMO WORKSPACE</div><span>Expires {manifest ? new Intl.DateTimeFormat("en", { hour: "numeric", minute: "2-digit" }).format(new Date(manifest.expires_at)) : "soon"} · No real data</span></div>
    <section className="demo-hero"><div><p className="eyebrow">OPERATIONS CONTROL PLANE</p><h1>From uncertain packet<br /><em>to accountable action.</em></h1><p>Explore a real synthetic queue. The walkthrough follows one exception all the way from evidence to safe export recovery.</p></div><div className="demo-hero__principles"><span>01 <strong>Extract</strong><small>with evidence</small></span><span>02 <strong>Validate</strong><small>with rules</small></span><span>03 <strong>Approve</strong><small>with a person</small></span></div></section>
    <section className="demo-metrics" aria-label="Queue metrics"><div><span>Review queue</span><strong>{queueMetrics.review}</strong><small>human decision required</small></div><div><span>Missing information</span><strong>{queueMetrics.missing}</strong><small>blocked by required data</small></div><div><span>Ready to export</span><strong>{queueMetrics.ready}</strong><small>approval gate remains</small></div><div><span>Completed</span><strong>{queueMetrics.completed}</strong><small>mock downstream accepted</small></div></section>
    {error && <div className="alert" role="alert">{error}<button className="alert-retry" onClick={() => void retryLoad()}>Try again</button></div>}
    <section className="demo-grid" data-tour-target="demo-queue"><div className="panel demo-queue-panel"><div className="panel-heading"><div><p className="eyebrow">WORK QUEUE</p><h2>Five synthetic scenarios</h2></div><span className="queue-count">{visibleCases.length} of {cases.length} cases</span></div><p className="muted">Every card is seeded independently for this session. Open any case to explore freely.</p><div className="queue-filters"><label><span>Search</span><input value={queueQuery} onChange={(event) => setQueueQuery(event.target.value)} placeholder="Case or scenario" /></label><label><span>Status</span><select value={queueStatus} onChange={(event) => setQueueStatus(event.target.value)}><option value="all">All statuses</option><option value="review_required">Review required</option><option value="missing_information">Missing information</option><option value="ready_for_export">Ready for export</option><option value="completed">Completed</option></select></label><label><span>Risk</span><select value={queueRisk} onChange={(event) => setQueueRisk(event.target.value)}><option value="all">All risk</option><option value="high">High</option><option value="medium">Medium</option><option value="low">Low</option></select></label></div><div className="scenario-list">{visibleCases.length === 0 ? <div className="empty">No cases match these filters.</div> : visibleCases.map((item) => { const scenario = manifest?.scenarios.find((candidate) => candidate.case_id === item.id); return <Link href={`/demo/cases/${item.id}`} data-tour-target={item.scenario === "exception-recovery" ? "demo-case-exception-recovery" : undefined} className={`scenario-card ${item.scenario === "exception-recovery" ? "scenario-card--recommended" : ""}`} key={item.id}><div className="scenario-card__icon">{item.scenario === "exception-recovery" ? "!" : item.scenario === "missing-information" ? "?" : "✓"}</div><div><div className="scenario-card__title"><strong>{scenario?.title || item.external_reference}</strong>{scenario?.recommended && <span>TOUR PATH</span>}</div><p>{scenario?.description || "Synthetic administrative scenario"}</p><small>{item.external_reference} · {item.document_count} document{item.document_count === 1 ? "" : "s"} · {timeInState(item.updated_at)}</small></div><StatusPill status={item.status} /><span className="arrow">→</span></Link>; })}</div></div><aside className="panel demo-side-panel"><p className="eyebrow">START HERE</p><h2>Follow the exception</h2><p>One packet contains conflicting member IDs and an instruction-like sentence. Watch how the system refuses to auto-export and keeps every step reviewable.</p><button onClick={openRecommended} disabled={!recommended}>Open recommended case →</button><div className="side-divider" /><p className="eyebrow">SELF-GUIDED MODE</p><p className="muted">Pause the coachmarks at any time. Reset restores the same five cases.</p>{tourActive ? <Link className="button-link secondary" href={recommended ? `/demo/cases/${recommended.id}` : "/"}>Explore workspace</Link> : <button className="secondary" onClick={() => { setTourActive(true); window.sessionStorage.removeItem("intakeflow-tour-paused"); }}>Resume walkthrough</button>}</aside></section>
    {manifest && tourActive && <TourCoach steps={manifest.tour} index={Math.min(index, manifest.tour.length - 1)} onNext={() => { if (index === 1) openRecommended(); else setTourIndex(index + 1); }} onBack={() => setTourIndex(index - 1)} onClose={() => { setTourActive(false); window.sessionStorage.setItem("intakeflow-tour-paused", "true"); }} onRestart={() => { setTourActive(true); window.sessionStorage.removeItem("intakeflow-tour-paused"); setTourIndex(0); }} />}
  </main>;
}
