import { CaseStatus } from "@/lib/api";

const labels: Record<CaseStatus, string> = {
  received: "Received",
  queued: "Queued",
  processing: "Processing",
  ready_for_export: "Ready for export",
  missing_information: "Missing information",
  review_required: "Review required",
  failed: "Needs attention",
  completed: "Completed",
};

export function StatusPill({ status }: { status: CaseStatus }) {
  return <span className={`status status--${status}`}>{labels[status]}</span>;
}
