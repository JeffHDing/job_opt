"""
resume_diff.py — pure-Python resume parsing, diffing, and revert utilities.

No LLM dependency; safe to import and test in isolation.

Two kinds of content are tracked separately because they have different
fact-checking rules and different revert mechanics:

  * **bullets** — the "- " lines, matched against the master within their own
    section, since the same claim in a different role is a different claim.
  * **lines** — headings, employer/date lines, and other non-bullet content.
    These carry identity (titles, dates, degrees) and must appear verbatim
    somewhere in the master, so they are matched globally.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable, Iterable, Iterator, NamedTuple

# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

BULLET = "bullet"
LINE = "line"


@dataclass
class ResumeChange:
    section: str
    original: str
    tailored: str
    kind: str = BULLET


@dataclass
class ValidationResult:
    passed: bool
    violations: list[dict] = field(default_factory=list)
    reviewed: int = 0
    skipped: bool = False
    skip_reason: str = ""

    @property
    def major_violations(self) -> list[dict]:
        return [v for v in self.violations if v.get("severity") == "major"]

    def summary(self) -> str:
        lines: list[str] = []
        if self.skipped:
            lines.append(f"⚠  Fact-check skipped: {self.skip_reason}")

        # Deterministic checks still run when the model call is skipped, so a
        # skipped result can carry violations and must still be reported.
        if not self.violations:
            if not self.skipped:
                lines.append(
                    f"✓  Fact-check passed ({self.reviewed} changed item(s) "
                    "reviewed, none flagged)"
                )
            return "\n".join(lines)

        major = len(self.major_violations)
        header = (
            f"✗  Fact-check failed — {len(self.violations)} unsupported edit(s) "
            f"out of {self.reviewed} reviewed"
        )
        if major:
            header += f" ({major} major)"
        lines.append(header + ":")
        for v in self.violations:
            severity = v.get("severity", "")
            tag = f"[{severity}] " if severity else ""
            lines.append(f"   • {tag}{v.get('reason', '(no reason given)')}")
            lines.append(f"     original: {v.get('original', '')}")
            lines.append(f"     tailored: {v.get('tailored', '')}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

# Stand-in for the "original" of tailored content that has no counterpart in
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


def _classify(raw_line: str) -> tuple[str, str] | None:
    """
    Return (kind, text) for a content-bearing line, or None for blank lines.

    Bullet text excludes the "- " marker so it can be compared and reverted
    independently of indentation; line text is the whole stripped line.
    """
    stripped = raw_line.strip()
    if not stripped:
        return None
    if stripped.startswith("- "):
        return BULLET, stripped[2:].strip()
    return LINE, stripped


def parse_bullets(md: str) -> dict[str, list[str]]:
    """
    Parse a Markdown resume into {section_path: [bullet_text, ...]} where
    section_path is 'H2 Section / H3 Subsection' (or just 'H2 Section').
    """
    result: dict[str, list[str]] = {}

    for section, raw_line in _iter_lines_with_section(md.splitlines()):
        classified = _classify(raw_line)
        if classified and classified[0] == BULLET:
            result.setdefault(section, []).append(classified[1])

    return result


def parse_content_lines(md: str) -> list[str]:
    """
    Return every non-bullet, non-blank line in document order.

    These are the headings, employer/date lines, and contact details that carry
    the resume's identity claims.
    """
    lines: list[str] = []
    for raw_line in md.splitlines():
        classified = _classify(raw_line)
        if classified and classified[0] == LINE:
            lines.append(classified[1])
    return lines


# ---------------------------------------------------------------------------
# Diffing
# ---------------------------------------------------------------------------

def _token_overlap(a: str, b: str) -> float:
    """Jaccard overlap on lowercased word tokens — fast proxy for similarity."""
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


def find_changed_bullets(master_md: str, tailored_md: str) -> list[ResumeChange]:
    """
    Compare master and tailored resumes bullet by bullet.

    A bullet is 'changed' if it does not appear verbatim in the master's
    corresponding section. Each changed bullet is paired with its closest
    master counterpart for fact-check review.
    """
    master_bullets = parse_bullets(master_md)
    tailored_bullets = parse_bullets(tailored_md)

    changes: list[ResumeChange] = []
    for section, t_list in tailored_bullets.items():
        m_list = master_bullets.get(section, [])
        m_set = set(m_list)
        for tb in t_list:
            if tb not in m_set:
                best = _closest_match(tb, m_list)
                changes.append(ResumeChange(
                    section=section,
                    original=best if best else NO_MASTER_MATCH,
                    tailored=tb,
                    kind=BULLET,
                ))
    return changes


def find_changed_lines(master_md: str, tailored_md: str) -> list[ResumeChange]:
    """
    Compare the non-bullet lines — headings, employers, dates, contact details.

    Matching is global rather than per-section so that reordering sections or
    moving an entry is not mistaken for an edit; only text that appears nowhere
    in the master is reported. This is what catches a tailoring model quietly
    promoting a job title or shifting a date range.
    """
    master_lines = parse_content_lines(master_md)
    master_set = set(master_lines)

    changes: list[ResumeChange] = []
    seen: set[str] = set()
    for section, raw_line in _iter_lines_with_section(tailored_md.splitlines()):
        classified = _classify(raw_line)
        if not classified or classified[0] != LINE:
            continue
        text = classified[1]
        if text in master_set or text in seen:
            continue
        seen.add(text)
        best = _closest_match(text, master_lines)
        changes.append(ResumeChange(
            section=section,
            original=best if best else NO_MASTER_MATCH,
            tailored=text,
            kind=LINE,
        ))
    return changes


def find_changes(master_md: str, tailored_md: str) -> list[ResumeChange]:
    """All tailored content that differs from the master, lines before bullets."""
    return (
        find_changed_lines(master_md, tailored_md)
        + find_changed_bullets(master_md, tailored_md)
    )


# ---------------------------------------------------------------------------
# Technical Skills integrity
# ---------------------------------------------------------------------------

_SKILLS_SECTION = "technical skills"
_SKILL_ROW_RE = re.compile(r"^\*\*(?P<category>[^*]+?):?\*\*:?\s*(?P<terms>.+)$")


# A skill written as "SQL (PostgreSQL)" is three strings an ATS can match and
# three ways for the tailor to list the same skill twice.
_ALIASED_TERM_RE = re.compile(r"^(?P<head>[^(]+?)\s*\((?P<inner>[^)]+)\)$")


class _SkillRow(NamedTuple):
    text: str     # the bullet as written, e.g. "**Languages:** Python, R"
    prefix: str   # everything up to the first term, e.g. "**Languages:** "
    terms: list[str]


def _term_components(term: str) -> list[str]:
    """
    The ways a skill can be written: itself, plus either half of an alias.

    "SQL (PostgreSQL)" yields "SQL (PostgreSQL)", "SQL", and "PostgreSQL", so
    that a tailored row listing any one of them is recognised as naming the
    same skill.
    """
    match = _ALIASED_TERM_RE.match(term)
    if not match:
        return [term]
    return [term, match.group("head"), match.group("inner")]


def _skill_rows(md: str) -> dict[str, _SkillRow]:
    """
    Parse the Technical Skills section into {category: _SkillRow}.

    Rows look like "**Programming & Databases:** Python, R, PostgreSQL".
    """
    rows: dict[str, _SkillRow] = {}
    for section, bullets in parse_bullets(md).items():
        if section.strip().lower() != _SKILLS_SECTION:
            continue
        for bullet in bullets:
            match = _SKILL_ROW_RE.match(bullet)
            if not match:
                continue
            terms = [t.strip() for t in match.group("terms").split(",") if t.strip()]
            rows[match.group("category").strip()] = _SkillRow(
                text=bullet,
                prefix=bullet[:match.start("terms")],
                terms=terms,
            )
    return rows


def _mentions(term: str, haystack: str) -> bool:
    """
    Whether *term* appears in *haystack* as a whole term, case-insensitively.

    Word boundaries matter here: a plain substring test would accept "SQL" on
    the strength of the master's "PostgreSQL", or "R" on any word containing an
    r. The lookarounds are written by hand rather than with \\b so that terms
    ending in punctuation, like "C++" or "A/B Testing", still match.
    """
    pattern = rf"(?<!\w){re.escape(term)}(?!\w)"
    return re.search(pattern, haystack, re.IGNORECASE) is not None


def find_unsupported_skills(master_md: str, tailored_md: str) -> list[dict]:
    """
    Flag Technical Skills terms the tailored resume added without evidence.

    A term is supported when it appears anywhere in the master resume, so
    promoting a tool named in a project into the Skills section is fine while
    inventing one outright is not. This runs deterministically alongside the
    model's fact-check because a silently padded skills list is the single most
    damaging thing a tailoring model can do — it is what a candidate gets caught
    on in a screen, and it is cheap to verify exactly.

    Returns violation dicts in the same shape the model emits, so they flow
    through the same review-and-revert path.
    """
    master_rows = _skill_rows(master_md)
    if not master_rows:
        return []

    violations: list[dict] = []

    for category, row in _skill_rows(tailored_md).items():
        master_row = master_rows.get(category)
        if master_row is None:
            continue

        known = {t.lower() for t in master_row.terms}
        added = [
            term for term in row.terms
            if term.lower() not in known and not _mentions(term, master_md)
        ]
        if added:
            violations.append({
                "original": master_row.text,
                "tailored": row.text,
                "supported": False,
                "severity": "major",
                "reason": (
                    f"Technical Skills row '{category}' added "
                    f"{', '.join(repr(t) for t in added)}, which "
                    f"{'do' if len(added) > 1 else 'does'} not appear anywhere "
                    "in the master resume."
                ),
            })

    return violations


# ---------------------------------------------------------------------------
# Reverting
# ---------------------------------------------------------------------------

def revert_violations(tailored_md: str, violations: list[dict]) -> str:
    """
    Replace each violation's tailored text with its original in the Markdown.

    Works line-by-line so that identical text appearing in different sections
    is only replaced at the first match for each violation entry, preventing
    cross-section collisions. The line's own prefix decides how it is rewritten,
    so a reverted bullet keeps its "- " marker and a reverted heading keeps its
    "###".

    Content is dropped instead of rewritten when it has no master counterpart,
    or when a bullet's original is already present in the same section —
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
        classified = _classify(raw_line)
        if classified and classified[1] in pending:
            kind, text = classified
            original = pending.pop(text)
            indent = " " * (len(raw_line) - len(raw_line.lstrip()))
            eol = "\n" if raw_line.endswith("\n") else ""

            if kind == BULLET:
                section_bullets = present.setdefault(section, set())
                section_bullets.discard(text)
                if original == NO_MASTER_MATCH or original in section_bullets:
                    continue
                section_bullets.add(original)
                result.append(f"{indent}- {original}{eol}")
            else:
                if original == NO_MASTER_MATCH:
                    continue
                result.append(f"{indent}{original}{eol}")
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
        classified = _classify(raw_line)
        if classified and classified[0] == BULLET:
            bullet_text = classified[1]
            section_bullets = seen.setdefault(section, set())
            if bullet_text in section_bullets:
                continue
            section_bullets.add(bullet_text)
        result.append(raw_line)

    return "".join(result)


# ---------------------------------------------------------------------------
# Interactive review
# ---------------------------------------------------------------------------

def normalize_skill_rows(master_md: str, tailored_md: str) -> str:
    """
    Make each Technical Skills row list exactly the skills the master puts in it.

    Row membership and spelling are the master's; ordering within a row is the
    tailor's. Four things are corrected, in this order:

      * A term the master files under a different row is removed. The tailor is
        told each skill stays in the row it came from, but it will happily copy
        a term into a second row to echo the job description.
      * A term is rewritten to the master's spelling of it, so that pulling the
        "SQL" out of the master's "SQL (PostgreSQL)" reads as the same skill
        rather than a second one. No keywords are lost, since the master's form
        contains the alias.
      * A skill named twice in a row, under any of its spellings, is collapsed
        to its first occurrence.
      * A term the master lists in this row but the tailor dropped is appended.

    Removal has to happen alongside restoration rather than on its own: putting
    a moved term back in its home row while leaving the copy in place is what
    turns a move into a duplicate. Genuinely new terms — ones the master names
    nowhere — are left where the tailor put them, since the fact-check reviews
    those separately.

    Rows the tailored resume deleted outright are left alone; there is no
    reliable place to reinsert them.
    """
    master_rows = _skill_rows(master_md)
    if not master_rows:
        return tailored_md

    # Every spelling of every master skill → (owning row, the master's spelling).
    # Built in row order, so an alias shared by two skills belongs to the first.
    canonical: dict[str, tuple[str, str]] = {}
    for category, master_row in master_rows.items():
        for term in master_row.terms:
            for component in _term_components(term):
                canonical.setdefault(component.lower(), (category, term))

    rewrites: dict[str, str] = {}
    for category, row in _skill_rows(tailored_md).items():
        master_row = master_rows.get(category)
        if master_row is None:
            continue

        kept: list[str] = []
        seen: set[str] = set()
        for term in row.terms:
            owner, spelling = canonical.get(term.lower(), (category, term))
            if owner != category:
                continue
            if spelling.lower() in seen:
                continue
            seen.add(spelling.lower())
            kept.append(spelling)

        kept += [t for t in master_row.terms if t.lower() not in seen]

        rebuilt = f"{row.prefix}{', '.join(kept)}"
        if rebuilt != row.text:
            rewrites[row.text] = rebuilt

    if not rewrites:
        return tailored_md

    result: list[str] = []
    for raw_line in tailored_md.splitlines(keepends=True):
        classified = _classify(raw_line)
        if classified and classified[0] == BULLET and classified[1] in rewrites:
            indent = " " * (len(raw_line) - len(raw_line.lstrip()))
            eol = "\n" if raw_line.endswith("\n") else ""
            result.append(f"{indent}- {rewrites.pop(classified[1])}{eol}")
            continue
        result.append(raw_line)

    return "".join(result)


def _format_violation_review(violation: dict, index: int, total: int) -> str:
    """Format one flagged edit for interactive review."""
    severity = violation.get("severity", "")
    heading = f"Edit {index} of {total}"
    if severity:
        heading += f"  [{severity}]"
    return "\n".join([
        f"{heading}:",
        f"  Reason: {violation.get('reason', '(no reason given)')}",
        f"  original: {violation.get('original', '')}",
        f"  tailored: {violation.get('tailored', '')}",
    ])


_PROMPT_OPTIONS = "[y]es / [n]o / [a]ll / [q]uit reviewing: "


def report_and_maybe_revert(
    tailored_md: str,
    result: ValidationResult,
    input_fn: Callable[[str], str] | None = None,
) -> str:
    """
    Print the fact-check summary and, if unsupported edits were flagged, walk
    the user through each one and ask whether to revert it.

    Answering `a` reverts every remaining edit and `q` keeps them; both exist so
    a run with many flags doesn't turn into a long interrogation. EOF (piped or
    non-interactive input) is treated as "keep", leaving the tailored text
    untouched.

    input_fn defaults to the builtin input(), resolved at call time (not
    bound at import time) so tests can monkeypatch builtins.input.
    """
    print("\n--- Fact-Check Report ---\n")
    print(result.summary())

    if not result.violations:
        return tailored_md

    if input_fn is None:
        input_fn = input

    print("\n--- Review flagged edits ---\n")
    to_revert: list[dict] = []
    total = len(result.violations)

    for i, violation in enumerate(result.violations, start=1):
        print(_format_violation_review(violation, i, total))
        action = "Remove this content?" if _is_new_content(violation) else \
            "Revert this to the master's original?"
        answer = _ask(input_fn, f"{action} {_PROMPT_OPTIONS}")
        if answer == "a":
            to_revert.extend(result.violations[i - 1:])
            print(f"  Reverting all {total - i + 1} remaining edit(s).\n")
            break
        if answer == "q":
            print("  Keeping all remaining edits.\n")
            break
        if answer == "y":
            to_revert.append(violation)
        print()

    if to_revert:
        tailored_md = revert_violations(tailored_md, to_revert)
        print(f"Reverted {len(to_revert)} edit(s) to the master's originals.")

    return tailored_md


def _is_new_content(violation: dict) -> bool:
    return violation.get("original") == NO_MASTER_MATCH


def _ask(input_fn: Callable[[str], str], prompt: str) -> str:
    """Read a single y/n/a/q answer, treating EOF as 'no'."""
    while True:
        try:
            answer = input_fn(prompt).strip().lower()
        except EOFError:
            print()
            return "n"
        if answer in ("y", "n", "a", "q"):
            return answer
        print("  Please enter 'y', 'n', 'a', or 'q'.")
