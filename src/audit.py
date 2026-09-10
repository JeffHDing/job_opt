"""
audit.py — parsing and presentation for the ATS auditor's report.

The auditor returns a human-readable Markdown report whose headline numbers and
directive list also need to be read by code: the score drives what gets printed
and logged, the directives are what the tailor is asked to execute. This module
turns that Markdown into a structured AuditReport without an LLM dependency, so
it can be imported and tested in isolation.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

# The auditor prompt pins these two lines verbatim; everything around them is
# free-form Markdown that only a human reads.
_CURRENT_SCORE_RE = re.compile(
    r"Overall ATS score:\s*(\d{1,3})\s*/\s*100", re.IGNORECASE
)
_PROJECTED_SCORE_RE = re.compile(
    r"Projected ATS score after tailoring:\s*(\d{1,3})\s*/\s*100", re.IGNORECASE
)
_REACHABLE_RE = re.compile(r"\*\*Reachable:\*\*\s*`?(yes|no)`?", re.IGNORECASE)

_DIRECTIVES_HEADING_RE = re.compile(r"^#{1,4}\s*4\.\s*Tailoring Directives", re.I)
_ANY_HEADING_RE = re.compile(r"^#{1,4}\s+")
_NUMBERED_ITEM_RE = re.compile(r"^\s*\d+[.)]\s+(.*)")

# The tailor must never copy the auditor's "[X]%"-style placeholders into a
# resume, so the pipeline checks its output for them.
_PLACEHOLDER_RE = re.compile(r"\[[A-Za-z0-9 ,._/%+-]{1,30}\]")

# Below this the tailored resume is unlikely to clear a keyword screen; the
# auditor prompt asks for 90+, and 90-95 is the band the workflow targets.
TARGET_SCORE = 90


@dataclass
class AuditReport:
    """The auditor's Markdown report plus the fields code needs from it."""

    markdown: str
    current_score: int | None = None
    projected_score: int | None = None
    reachable: bool | None = None
    directives: list[str] = field(default_factory=list)
    skipped: bool = False
    skip_reason: str = ""

    @property
    def target_reachable(self) -> bool | None:
        """
        Whether tailoring alone can reach TARGET_SCORE.

        Prefers the auditor's own explicit verdict and falls back to the
        projected score, since the two can disagree when the model hedges.
        """
        if self.reachable is not None:
            return self.reachable
        if self.projected_score is None:
            return None
        return self.projected_score >= TARGET_SCORE

    def summary(self) -> str:
        if self.skipped:
            return f"⚠  Audit skipped: {self.skip_reason}"

        lines = []
        if self.current_score is None:
            lines.append("⚠  Could not parse an ATS score from the audit report.")
        else:
            lines.append(f"   Current ATS score:   {self.current_score}/100")
        if self.projected_score is not None:
            lines.append(f"   Projected after tailoring: {self.projected_score}/100")

        reachable = self.target_reachable
        if reachable is True:
            lines.append(f"   ✓  {TARGET_SCORE}%+ reachable by tailoring alone.")
        elif reachable is False:
            lines.append(
                f"   ✗  {TARGET_SCORE}%+ NOT reachable without new experience "
                "— see 'Unclosable without new experience' in the report."
            )

        lines.append(f"   {len(self.directives)} tailoring directive(s) issued.")
        return "\n".join(lines)


def _parse_score(pattern: re.Pattern[str], markdown: str) -> int | None:
    match = pattern.search(markdown)
    if match is None:
        return None
    score = int(match.group(1))
    return score if 0 <= score <= 100 else None


def _parse_reachable(markdown: str) -> bool | None:
    match = _REACHABLE_RE.search(markdown)
    if match is None:
        return None
    return match.group(1).lower() == "yes"


def parse_directives(markdown: str) -> list[str]:
    """
    Extract the numbered directives from section 4 of the audit report.

    A directive may wrap onto continuation lines, which are folded back into the
    item they belong to. Parsing stops at the next heading so sections 5 and 6
    never leak in.
    """
    lines = markdown.splitlines()

    start = next(
        (i for i, line in enumerate(lines) if _DIRECTIVES_HEADING_RE.match(line)),
        None,
    )
    if start is None:
        return []

    directives: list[str] = []
    for line in lines[start + 1:]:
        if _ANY_HEADING_RE.match(line):
            break
        item = _NUMBERED_ITEM_RE.match(line)
        if item:
            directives.append(item.group(1).strip())
        elif directives and line.strip():
            directives[-1] = f"{directives[-1]} {line.strip()}"

    return [d for d in directives if d]


def parse_audit_report(markdown: str) -> AuditReport:
    """Build an AuditReport from the auditor's raw Markdown output."""
    return AuditReport(
        markdown=markdown,
        current_score=_parse_score(_CURRENT_SCORE_RE, markdown),
        projected_score=_parse_score(_PROJECTED_SCORE_RE, markdown),
        reachable=_parse_reachable(markdown),
        directives=parse_directives(markdown),
    )


def find_placeholders(markdown: str) -> list[str]:
    """
    Return any bracketed placeholders left in a tailored resume.

    The auditor writes "[X]%"-style placeholders for the human to fill in; the
    tailor is instructed never to copy them into a resume. Markdown links are
    excluded — "[LinkedIn](...)" is legitimate resume content.
    """
    found: list[str] = []
    for match in _PLACEHOLDER_RE.finditer(markdown):
        if markdown[match.end():match.end() + 1] == "(":
            continue
        found.append(match.group(0))
    return found
