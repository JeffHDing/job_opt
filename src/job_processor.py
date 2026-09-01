"""
job_processor.py — orchestrates the audit → tailor → fact-check pipeline.

Everything the LLM does not do lives here: reading the master, persisting the
audit report, stamping the header role, deduping, trimming to one page, and
exporting the PDF.
"""
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from audit import AuditReport, find_placeholders
from llm_client import audit_resume, fact_check, tailor_resume
from pdf_exporter import generate_resume_pdf, get_page_count
from resume_diff import (
    dedupe_bullets,
    normalize_skill_rows,
    report_and_maybe_revert,
)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_RESUME = _PROJECT_ROOT / "data/masters/Jeffrey_Ding_CV_Data_Science.md"
_OUTPUT_DIR = _PROJECT_ROOT / "data/tailored_outputs"
_AUDIT_DIR = _PROJECT_ROOT / "data/audit_reports"

_MAX_TRIM_PASSES = 8


@dataclass
class ApplicationResult:
    """Everything a run produced. Paths are None for stages that were skipped."""

    audit: AuditReport | None = None
    audit_path: Path | None = None
    md_path: Path | None = None
    pdf_path: Path | None = None


def _slug(text: str) -> str:
    """Collapse arbitrary user input into something safe for a filename."""
    cleaned = re.sub(r"[^\w\s-]", "", text).strip()
    return re.sub(r"[\s_-]+", "_", cleaned) or "Untitled"


def _find_section_bounds(lines: list[str], header_pattern: str) -> tuple[int, int]:
    """
    Return (start, end) line indices for the first ## section whose header
    matches *header_pattern* (case-insensitive).  end is the index of the next
    ## header, or len(lines) if the section runs to EOF.
    """
    start = -1
    for i, line in enumerate(lines):
        if re.match(rf'^##\s+{header_pattern}', line, re.IGNORECASE):
            start = i
        elif start != -1 and re.match(r'^##\s+', line):
            return start, i
    return start, len(lines)


def _trim_one_bullet(markdown_text: str) -> str | None:
    """
    Remove one bullet to reduce content length, targeting the least-important
    positions first:

    Pass order:
      1. Last bullet of the last project entry that has ≥ 2 bullets.
      2. Last bullet of the last experience entry that has ≥ 4 bullets.
      3. Remove the entire last project entry (h3 + its bullets).

    Returns the trimmed markdown string, or None if nothing could be removed.
    """
    lines = markdown_text.split('\n')

    # ------------------------------------------------------------------ #
    # Helper: collect (h3_line_idx, [bullet_line_idxs]) within a section  #
    # ------------------------------------------------------------------ #
    def entries_in_section(start: int, end: int):
        entries: list[tuple[int, list[int]]] = []
        current_h3: int | None = None
        current_bullets: list[int] = []
        for i in range(start + 1, end):
            if re.match(r'^###\s+', lines[i]):
                if current_h3 is not None:
                    entries.append((current_h3, current_bullets))
                current_h3 = i
                current_bullets = []
            elif current_h3 is not None and re.match(r'^-\s+', lines[i]):
                current_bullets.append(i)
        if current_h3 is not None:
            entries.append((current_h3, current_bullets))
        return entries

    # ------------------------------------------------------------------ #
    # 1. Last project entry with ≥ 2 bullets → drop its last bullet       #
    # ------------------------------------------------------------------ #
    proj_start, proj_end = _find_section_bounds(lines, 'Projects')
    if proj_start != -1:
        proj_entries = entries_in_section(proj_start, proj_end)
        for h3_idx, bullets in reversed(proj_entries):
            if len(bullets) >= 2:
                drop = bullets[-1]
                return '\n'.join(lines[:drop] + lines[drop + 1:])

    # ------------------------------------------------------------------ #
    # 2. Last experience entry with ≥ 4 bullets → drop its last bullet    #
    # ------------------------------------------------------------------ #
    exp_start, exp_end = _find_section_bounds(lines, 'Experience')
    if exp_start != -1:
        exp_entries = entries_in_section(exp_start, exp_end)
        for h3_idx, bullets in reversed(exp_entries):
            if len(bullets) >= 4:
                drop = bullets[-1]
                return '\n'.join(lines[:drop] + lines[drop + 1:])

    # ------------------------------------------------------------------ #
    # 3. Remove the entire last project entry (h3 block)                  #
    # ------------------------------------------------------------------ #
    if proj_start != -1:
        proj_entries = entries_in_section(proj_start, proj_end)
        if proj_entries:
            last_h3_idx, _ = proj_entries[-1]
            # The block ends just before the next h3 or the section end
            block_end = proj_end
            for i in range(last_h3_idx + 1, proj_end):
                if re.match(r'^###\s+', lines[i]):
                    block_end = i
                    break
            # Strip the h3 line and everything up to block_end, then collapse
            # the seam to a single blank line so the next heading still reads as
            # a heading in the saved Markdown.
            kept = lines[:last_h3_idx] + lines[block_end:]
            seam = last_h3_idx
            while seam > 0 and not kept[seam - 1].strip():
                kept.pop(seam - 1)
                seam -= 1
            if 0 < seam < len(kept) and kept[seam].strip():
                kept.insert(seam, '')
            return '\n'.join(kept)

    return None


def _set_header_role(markdown_text: str, role: str) -> str:
    """
    Replace the bolded role title in the resume header (the line containing
    the phone/email contact info) with *role* from the job description.

    The header line looks like:
        **Data Scientist** | 647-... | ...

    The tailor is told to leave this line alone so that any change it makes is
    caught by the fact-check; stamping it here instead keeps the title matching
    the posting without muddying that signal.
    """
    display_role = role.replace("_", " ")

    def _replace(m: re.Match) -> str:
        return f"**{display_role}**{m.group(1)}"

    # Match **<anything>** followed by a pipe separator on the same line
    return re.sub(r'\*\*[^*]+\*\*(\s*\|)', _replace, markdown_text, count=1)


def _ensure_one_page(markdown_text: str) -> str:
    """
    Iteratively trim bullets from the tailored markdown until the rendered
    PDF fits on exactly one page, up to _MAX_TRIM_PASSES attempts.
    """
    for pass_num in range(1, _MAX_TRIM_PASSES + 1):
        pages = get_page_count(markdown_text)
        if pages <= 1:
            if pass_num > 1:
                print(f"  Trimmed to 1 page after {pass_num - 1} pass(es).")
            return markdown_text

        print(
            f"  Page overflow ({pages} pages) — trimming pass"
            f" {pass_num}/{_MAX_TRIM_PASSES}...",
            flush=True,
        )
        trimmed = _trim_one_bullet(markdown_text)
        if trimmed is None:
            print("  Warning: could not trim further; PDF may exceed one page.")
            return markdown_text
        markdown_text = trimmed

    pages = get_page_count(markdown_text)
    if pages > 1:
        print(f"  Warning: still {pages} pages after {_MAX_TRIM_PASSES} trim passes.")
    return markdown_text


def _read_master(resume_path: Path | None) -> str:
    resume_path = Path(resume_path) if resume_path else _DEFAULT_RESUME
    if not resume_path.exists():
        raise FileNotFoundError(f"resume not found: {resume_path}")
    return resume_path.read_text()


def _display(path: Path) -> Path:
    try:
        return path.relative_to(_PROJECT_ROOT)
    except ValueError:
        return path


def run_audit(
    job_description: str,
    company: str,
    role: str,
    resume_path: Path | None = None,
) -> tuple[AuditReport, Path | None]:
    """
    Stage 1: score the master resume against the job description and save the
    report. Returns the report and the path it was written to (None if the
    audit call failed).
    """
    master_md = _read_master(resume_path)

    print("Stage 1/3 — auditing master resume against the job description...",
          flush=True)
    audit = audit_resume(master_md, job_description)
    print(audit.summary())

    if audit.skipped:
        return audit, None

    _AUDIT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = date.today().strftime("%Y%m%d")
    audit_path = _AUDIT_DIR / f"{stamp}_{_slug(company)}_{_slug(role)}_ats_audit.md"
    audit_path.write_text(audit.markdown)
    print(f"   Audit report → {_display(audit_path)}")

    return audit, audit_path


def process_application(
    job_description: str,
    company: str,
    role: str,
    resume_path: Path | None = None,
    audit: bool = True,
    factcheck: bool = True,
    export_pdf: bool = True,
) -> ApplicationResult:
    """
    Full pipeline: audit → tailor → fact-check → trim to one page → export PDF.

    Raises FileNotFoundError if resume_path doesn't exist — callers (e.g.
    main.py) are responsible for turning that into a user-facing CLI error.
    """
    master_md = _read_master(resume_path)
    result = ApplicationResult()

    # 1. Audit
    if audit:
        result.audit, result.audit_path = run_audit(
            job_description, company, role, resume_path
        )
        print()

    # 2. Tailor
    directive_note = (
        f" against {len(result.audit.directives)} audit directive(s)"
        if result.audit and result.audit.directives
        else ""
    )
    print(f"Stage 2/3 — tailoring resume{directive_note}...", flush=True)
    tailored_md = tailor_resume(master_md, job_description, audit=result.audit)

    # 3. Fact-check, then let the user revert anything flagged
    if factcheck:
        print("\nStage 3/3 — fact-checking against the master resume...", flush=True)
        validation = fact_check(master_md, tailored_md, job_description)
        tailored_md = report_and_maybe_revert(tailored_md, validation)

    placeholders = find_placeholders(tailored_md)
    if placeholders:
        print(
            "\n⚠  Unfilled placeholders left in the resume: "
            f"{', '.join(sorted(set(placeholders)))}\n"
            "   Fill in the real figures in the master resume and re-run."
        )

    # 4. Post-process: stamp the job title, put back dropped keywords, drop
    #    repeats, fit one page
    tailored_md = _set_header_role(tailored_md, role)
    tailored_md = normalize_skill_rows(master_md, tailored_md)
    tailored_md = dedupe_bullets(tailored_md)
    tailored_md = _ensure_one_page(tailored_md)

    # 5. Write outputs
    stem = f"Jeffrey_Ding_CV_{_slug(role)}"
    _OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    result.md_path = _OUTPUT_DIR / f"{stem}.md"
    result.md_path.write_text(tailored_md)
    print(f"\nMarkdown saved → {_display(result.md_path)}")

    if export_pdf:
        result.pdf_path = _OUTPUT_DIR / f"{stem}.pdf"
        generate_resume_pdf(tailored_md, str(result.pdf_path))

    return result
