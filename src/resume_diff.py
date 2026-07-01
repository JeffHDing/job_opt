"""
resume_diff.py — pure-Python bullet parsing, diffing, and revert utilities.

No LLM dependency; safe to import and test in isolation.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass
class BulletChange:
    section: str
    original: str
    tailored: str


@dataclass
class ValidationResult:
    passed: bool
    violations: list[dict] = field(default_factory=list)
    skipped: bool = False
    skip_reason: str = ""

    def summary(self) -> str:
        if self.skipped:
            return f"⚠  Validation skipped: {self.skip_reason}"
        if self.passed:
            return f"✓  Validation passed ({len(self.violations)} changed bullets reviewed, none flagged)"
        lines = [f"✗  Validation failed — {len(self.violations)} unsupported edit(s):"]
        for v in self.violations:
            lines.append(f"   • {v.get('reason', '(no reason given)')}")
            lines.append(f"     original: {v.get('original', '')}")
            lines.append(f"     tailored: {v.get('tailored', '')}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Bullet parser + differ
# ---------------------------------------------------------------------------

def parse_bullets(md: str) -> dict[str, list[str]]:
    """
    Parse a Markdown resume into {section_path: [bullet_text, ...]} where
    section_path is 'H2 Section / H3 Subsection' (or just 'H2 Section').
    """
    result: dict[str, list[str]] = {}
    current_h2 = ""
    current_h3 = ""

    for raw_line in md.splitlines():
        line = raw_line.strip()
        if line.startswith("## "):
            current_h2 = line[3:].strip()
            current_h3 = ""
        elif line.startswith("### "):
            current_h3 = line[4:].strip()
        elif line.startswith("- "):
            key = f"{current_h2} / {current_h3}" if current_h3 else current_h2
            result.setdefault(key, []).append(line[2:].strip())

    return result


def _token_overlap(a: str, b: str) -> float:
    """Jaccard overlap on lowercased word tokens — fast proxy for bullet similarity."""
    ta = set(re.findall(r"\w+", a.lower()))
    tb = set(re.findall(r"\w+", b.lower()))
    if not ta and not tb:
        return 1.0
    return len(ta & tb) / len(ta | tb)


def _closest_match(target: str, candidates: list[str]) -> str | None:
    """Return the candidate most similar to target by token overlap."""
    if not candidates:
        return None
    return max(candidates, key=lambda c: _token_overlap(target, c))


def find_changed_bullets(master_md: str, tailored_md: str) -> list[BulletChange]:
    """
    Compare master and tailored resumes bullet by bullet.
    A bullet is 'changed' if it does not appear verbatim in the master's
    corresponding section. Each changed bullet is paired with its closest
    master counterpart for judge review.
    """
    master_bullets = parse_bullets(master_md)
    tailored_bullets = parse_bullets(tailored_md)

    changes: list[BulletChange] = []
    for section, t_list in tailored_bullets.items():
        m_list = master_bullets.get(section, [])
        m_set = set(m_list)
        for tb in t_list:
            if tb not in m_set:
                best = _closest_match(tb, m_list)
                changes.append(BulletChange(
                    section=section,
                    original=best if best else "(no matching master bullet)",
                    tailored=tb,
                ))
    return changes


# ---------------------------------------------------------------------------
# Revert helper
# ---------------------------------------------------------------------------

def revert_violations(tailored_md: str, violations: list[dict]) -> str:
    """
    Replace each violation's tailored bullet with its original in the Markdown.

    Works line-by-line so that identical text appearing in different sections
    is only replaced at the first match for each violation entry, preventing
    cross-section collisions.
    """
    # Index violations by tailored text for O(1) lookup; track which have been
    # consumed so each violation reverts at most one occurrence.
    pending: dict[str, str] = {}
    for v in violations:
        tailored_text = v.get("tailored", "")
        original_text = v.get("original", "")
        if tailored_text and original_text and tailored_text not in pending:
            pending[tailored_text] = original_text

    result: list[str] = []
    for raw_line in tailored_md.splitlines(keepends=True):
        stripped = raw_line.strip()
        if stripped.startswith("- "):
            bullet_text = stripped[2:]
            if bullet_text in pending:
                indent = len(raw_line) - len(raw_line.lstrip())
                eol = "\n" if raw_line.endswith("\n") else ""
                result.append(" " * indent + "- " + pending.pop(bullet_text) + eol)
                continue
        result.append(raw_line)

    return "".join(result)
