"use client";

import { useEffect, useRef } from "react";
import { TourStep } from "@/lib/api";

type Props = {
  steps: TourStep[];
  index: number;
  onNext: () => void;
  onBack: () => void;
  onClose: () => void;
  onRestart: () => void;
  nextLabel?: string;
  nextDisabled?: boolean;
};

export function TourCoach({ steps, index, onNext, onBack, onClose, onRestart, nextLabel, nextDisabled = false }: Props) {
  const step = steps[index];
  const cardRef = useRef<HTMLElement>(null);
  useEffect(() => {
    if (!step) return;
    const target = document.querySelector(`[data-tour-target="${step.target}"]`);
    const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    target?.scrollIntoView({ behavior: reducedMotion ? "auto" : "smooth", block: "center" });
    target?.classList.add("tour-focus");
    cardRef.current?.focus({ preventScroll: true });
    return () => target?.classList.remove("tour-focus");
  }, [step]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.target instanceof HTMLInputElement || event.target instanceof HTMLTextAreaElement || event.target instanceof HTMLSelectElement) return;
      if (event.key === "Escape") onClose();
      if (event.key === "ArrowRight" && !nextDisabled) onNext();
      if (event.key === "ArrowLeft") onBack();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [nextDisabled, onBack, onClose, onNext]);

  if (!step) return null;
  return <>
    <div className="tour-scrim" aria-hidden="true" />
    <aside ref={cardRef} className="tour-card" role="dialog" aria-modal="false" tabIndex={-1} aria-label={`Walkthrough step ${index + 1} of ${steps.length}`}>
      <div className="tour-card__top"><span>90-SECOND WALKTHROUGH</span><button className="tour-close" onClick={onClose} aria-label="Pause walkthrough">×</button></div>
      <div className="tour-progress"><span style={{ width: `${((index + 1) / steps.length) * 100}%` }} /></div>
      <small>Step {index + 1} of {steps.length}</small><h2>{step.title}</h2><p>{step.body}</p>
      <div className="tour-actions"><button className="secondary" onClick={onBack} disabled={index === 0 || nextDisabled}>Back</button><button onClick={onNext} disabled={nextDisabled}>{nextLabel || (index === steps.length - 1 ? "Open technical proof →" : "Next →")}</button></div>
      <button className="tour-restart" onClick={onRestart}>Restart from the beginning</button>
    </aside>
  </>;
}
