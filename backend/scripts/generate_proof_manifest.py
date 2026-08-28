"""Generate the machine-readable recruiter proof artifact used by CI and the proof page."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from pathlib import Path

from app.demo import SCENARIO_VERSION
from app.evaluations import evaluate_dataset

ROOT = Path(__file__).resolve().parents[2]


def _commit_sha() -> str:
    try:
        local_commit = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, check=False, capture_output=True, text=True
        ).stdout.strip()
    except FileNotFoundError:
        local_commit = ""
    return os.getenv("GITHUB_SHA") or os.getenv("RENDER_GIT_COMMIT") or local_commit or "local"


def _coverage_percent() -> float | None:
    path = Path(os.getenv("COVERAGE_JSON", str(ROOT / "backend" / "coverage.json")))
    if not path.exists():
        return None
    try:
        return float(json.loads(path.read_text(encoding="utf-8"))["totals"]["percent_covered"])
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None


def _test_count() -> int:
    path = Path(os.getenv("PYTEST_JUNIT_XML", str(ROOT / "backend" / "pytest-report.xml")))
    if path.exists():
        try:
            root = ET.parse(path).getroot()
            if "tests" in root.attrib:
                return int(root.attrib["tests"])
            return sum(int(item.attrib.get("tests", "0")) for item in root.findall("testsuite"))
        except (ET.ParseError, TypeError, ValueError):
            pass
    return int(os.getenv("CI_TEST_COUNT", "0"))


def main() -> None:
    development = evaluate_dataset("development")
    challenge = evaluate_dataset("held_out")
    gates = {
        "zero_false_ready": development["false_ready_count"] == 0 and challenge["false_ready_count"] == 0,
        "routing_macro_f1": min(development["routing_macro_f1"], challenge["routing_macro_f1"]) >= 0.95,
        "field_macro_f1": min(development["field_macro_f1"], challenge["field_macro_f1"]) >= 0.95,
        "valid_evidence": min(development["evidence_validity"], challenge["evidence_validity"]) >= 1.0,
    }
    manifest = {
        "generated_at": datetime.now(UTC).isoformat(),
        "commit_sha": _commit_sha(),
        "app_version": os.getenv("APP_VERSION", "0.2.0"),
        "schema_version": "intake-record/2",
        "demo_scenario_version": SCENARIO_VERSION,
        "provider": os.getenv("MODEL_PROVIDER", "stub"),
        "coverage_percent": _coverage_percent(),
        "test_count": _test_count(),
        "quality_gates": gates,
        "all_quality_gates_pass": all(gates.values()),
        "evaluations": {"development": development, "challenge": challenge},
        "limitations": [
            "Synthetic administrative data only.",
            "Deterministic extraction is a rules baseline, not an LLM claim.",
            "Anthropic comparison is optional, bounded, and never changes workflow state.",
        ],
    }
    output = Path(os.getenv("PROOF_OUTPUT", str(ROOT / "evals" / "reports" / "recruiter-proof.json")))
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {output}")
    if not manifest["all_quality_gates_pass"]:
        failed = [name for name, passed in gates.items() if not passed]
        print(f"quality gates failed: {', '.join(failed)}", file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
