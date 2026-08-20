"""
resume_diff.py — pure-Python bullet parsing, diffing, and revert utilities.

No LLM dependency; safe to import and test in isolation.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable, Iterable, Iterator

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
            return (
                f"✓  Validation passed ({len(self.violations)} changed bullets "
                "reviewed, none flagged)"
            )
        lines = [f"✗  Validation failed — {len(self.violations)} unsupported edit(s):"]
        for v in self.violations:
            lines.append(f"   • {v.get('reason', '(no reason given)')}")
            lines.append(f"     original: {v.get('original', '')}")
            lines.append(f"     tailored: {v.get('tailored', '')}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Bullet parser + differ
# ---------------------------------------------------------------------------

# Stand-in for the "original" of a tailored bullet that has no counterpart in
# the master resume — i.e. wholly new content rather than an edit.
NO_MASTER_MATCH = "(no matching master bullet)"

# Two bullets scoring below this token overlap are treated as unrelated.
# Real edits to the master score ≳ 0.33; unrelated bullets score ≲ 0.15.
_MIN_MATCH_OVERLAP = 0.25


def _iter_lines_with_section(lines: Iterable[str]) -> Iterator[tuple[str, str]]:
    """
    Pair each line with the section path it belongs to, where section_path is
    'H2 Section / H3 Subsection' (or just 'H2 Section').
    """
    current_h2 = ""
    current_h3 = ""

    for raw_line in lines:
        line = raw_line.strip()
        if line.startswith("## "):
            current_h2 = line[3:].strip()
            current_h3 = ""
        elif line.startswith("### "):
            current_h3 = line[4:].strip()
        key = f"{current_h2} / {current_h3}" if current_h3 else current_h2
        yield key, raw_line


def parse_bullets(md: str) -> dict[str, list[str]]:
    """
    Parse a Markdown resume into {section_path: [bullet_text, ...]} where
    section_path is 'H2 Section / H3 Subsection' (or just 'H2 Section').
    """
    result: dict[str, list[str]] = {}

    for section, raw_line in _iter_lines_with_section(md.splitlines()):
        line = raw_line.strip()
        if line.startswith("- "):
            result.setdefault(section, []).append(line[2:].strip())

    return result


def _token_overlap(a: str, b: str) -> float:
    """Jaccard overlap on lowercased word tokens — fast proxy for bullet similarity."""
    ta = set(re.findall(r"\w+", a.lower()))
    tb = set(re.findall(r"\w+", b.lower()))
    if not ta and not tb:
        return 1.0
    return len(ta & tb) / len(ta | tb)


def _closest_match(
    target: str,
    candidates: list[str],
    min_overlap: float = _MIN_MATCH_OVERLAP,
) -> str | None:
    """
    Return the candidate most similar to target by token overlap, or None when
    even the best candidate falls below *min_overlap*. Without the floor an
    entirely new bullet would be paired with an unrelated master bullet, and
    reverting it would replace new content with a copy of that bullet.
    """
    if not candidates:
        return None
    best = max(candidates, key=lambda c: _token_overlap(target, c))
    return best if _token_overlap(target, best) >= min_overlap else None


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
                    original=best if best else NO_MASTER_MATCH,
                    tailored=tb,
                ))
    return changes


def revert_violations(tailored_md: str, violations: list[dict]) -> str:
    """
    Replace each violation's tailored bullet with its original in the Markdown.

    Works line-by-line so that identical text appearing in different sections
    is only replaced at the first match for each violation entry, preventing
    cross-section collisions.

    A flagged bullet is dropped instead of rewritten when it has no master
    counterpart, or when its original is already present in the same section —
    otherwise the revert would leave the section listing the same point twice.
    """
    # Index violations by tailored text for O(1) lookup; track which have been
    # consumed so each violation reverts at most one occurrence.
    pending: dict[str, str] = {}
    for v in violations:
        tailored_text = v.get("tailored", "")
        original_text = v.get("original", "")
        if tailored_text and original_text and tailored_text not in pending:
            pending[tailored_text] = original_text

    # Bullets each section currently holds, kept current as reverts are applied
    # so that back-to-back reverts can't converge on the same original.
    present = {sec: set(items) for sec, items in parse_bullets(tailored_md).items()}

    result: list[str] = []
    for section, raw_line in _iter_lines_with_section(
        tailored_md.splitlines(keepends=True)
    ):
        stripped = raw_line.strip()
        if stripped.startswith("- "):
            bullet_text = stripped[2:].strip()
            if bullet_text in pending:
                original = pending.pop(bullet_text)
                section_bullets = present.setdefault(section, set())
                section_bullets.discard(bullet_text)
                if original == NO_MASTER_MATCH or original in section_bullets:
                    continue
                section_bullets.add(original)
                indent = len(raw_line) - len(raw_line.lstrip())
                eol = "\n" if raw_line.endswith("\n") else ""
                result.append(" " * indent + "- " + original + eol)
                continue
        result.append(raw_line)

    return "".join(result)


def dedupe_bullets(md: str) -> str:
    """
    Drop bullets that repeat a bullet already listed in the same section.

    A backstop for duplicates from any source — the tailor agent restating a
    point, or a revert collapsing two bullets onto one original.
    """
    seen: dict[str, set[str]] = {}

    result: list[str] = []
    for section, raw_line in _iter_lines_with_section(md.splitlines(keepends=True)):
        stripped = raw_line.strip()
        if stripped.startswith("- "):
            bullet_text = stripped[2:].strip()
            section_bullets = seen.setdefault(section, set())
            if bullet_text in section_bullets:
                continue
            section_bullets.add(bullet_text)
        result.append(raw_line)

    return "".join(result)


def _format_violation_review(violation: dict, index: int, total: int) -> str:
    """Format one flagged edit for interactive review."""
    lines = [
        f"Edit {index} of {total}:",
        f"  Reason: {violation.get('reason', '(no reason given)')}",
        f"  original: {violation.get('original', '')}",
        f"  tailored: {violation.get('tailored', '')}",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Shared CLI helper — validation report + interactive revert prompt
# ---------------------------------------------------------------------------

def report_and_maybe_revert(
    tailored_md: str,
    result: ValidationResult,
    input_fn: Callable[[str], str] | None = None,
) -> str:
    """
    Print the validation summary and, if the judge flagged unsupported edits,
    walk the user through each flagged bullet and ask whether to revert it.

    Shared by every CLI entry point (main.py's job_processor and llm_client's
    standalone CLI) so the revert UX stays identical in one place. Returns the
    tailored Markdown, with any user-approved reverts applied in-place.

    input_fn defaults to the builtin input(), resolved at call time (not
    bound at import time) so tests can monkeypatch builtins.input.
    """
    print("\n--- Validation Report ---\n")
    print(result.summary())

    if result.passed or result.skipped:
        return tailored_md

    if input_fn is None:
        input_fn = input

    print("\n--- Review flagged edits ---\n")
    to_revert: list[dict] = []
    total = len(result.violations)

    for i, violation in enumerate(result.violations, start=1):
        print(_format_violation_review(violation, i, total))
        prompt = (
            "Remove this bullet? [y/n] "
            if violation.get("original") == NO_MASTER_MATCH
            else "Revert this bullet to original? [y/n] "
        )
        answer = ""
        while True:
            try:
                answer = input_fn(prompt).strip().lower()
            except EOFError:
                print()
                answer = ""
                break
            if answer in ("y", "n"):
                break
            print("  Please enter 'y' or 'n'.")
        if answer == "y":
            to_revert.append(violation)
        print()

    if to_revert:
        tailored_md = revert_violations(tailored_md, to_revert)
        print(f"Reverted {len(to_revert)} edit(s) to originals.")

    return tailored_md
