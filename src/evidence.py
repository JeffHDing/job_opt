"""Evidence and review artifacts derived from a job and the master resume."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from audit import AuditReport
from resume_diff import ValidationResult


def build_evidence_matrix(
    audit: AuditReport, master_resume: str, tailored_resume: str
) -> list[dict[str, Any]]:
    matrix: list[dict[str, Any]] = []
    for directive in audit.directives:
        quoted = directive.split('"', 2)
        evidence = quoted[1] if len(quoted) == 3 else ""
        matrix.append({
            "requirement_or_directive": directive,
            "master_evidence": (
                evidence if evidence and evidence in master_resume else None
            ),
            "present_in_tailored": bool(evidence and evidence in tailored_resume),
            "supported": bool(evidence and evidence in master_resume),
        })
    return matrix


def build_review_summary(
    audit: AuditReport, factcheck: ValidationResult, approval_state: str
) -> dict[str, Any]:
    return {
        "approval_state": approval_state,
        "audit": {
            "current_score": audit.current_score,
            "projected_score": audit.projected_score,
            "reachable": audit.target_reachable,
            "directive_count": len(audit.directives),
        },
        "fact_check": {
            "passed": factcheck.passed,
            "skipped": factcheck.skipped,
            "reviewed": factcheck.reviewed,
            "violations": factcheck.violations,
        },
        "human_review_required": bool(factcheck.violations or audit.skipped),
    }


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n")
