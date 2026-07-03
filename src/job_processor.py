import datetime
import re
from pathlib import Path

from llm_client import tailor_resume
from pdf_exporter import generate_resume_pdf, get_page_count
from resume_diff import report_and_maybe_revert

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_RESUME = _PROJECT_ROOT / "data/masters/Jeffrey_Ding_CV_Data_Science.md"
_OUTPUT_DIR = _PROJECT_ROOT / "data/tailored_outputs"

_MAX_TRIM_PASSES = 8


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
            if len(proj_entries) >= 2:
                next_h3_idx = proj_entries[-2][0]  # unused; block end computed below
            block_end = proj_end
            for i in range(last_h3_idx + 1, proj_end):
                if re.match(r'^###\s+', lines[i]):
                    block_end = i
                    break
            # Strip the h3 line and everything up to block_end, trimming blank lines
            kept = lines[:last_h3_idx] + lines[block_end:]
            # Remove trailing blank lines left by the removal
            while kept and kept[last_h3_idx - 1:last_h3_idx] == ['']:
                kept.pop(last_h3_idx - 1)
            return '\n'.join(kept)

    return None


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

        print(f"  Page overflow ({pages} pages) — trimming pass {pass_num}/{_MAX_TRIM_PASSES}...", flush=True)
        trimmed = _trim_one_bullet(markdown_text)
        if trimmed is None:
            print("  Warning: could not trim further; PDF may exceed one page.")
            return markdown_text
        markdown_text = trimmed

    pages = get_page_count(markdown_text)
    if pages > 1:
        print(f"  Warning: still {pages} pages after {_MAX_TRIM_PASSES} trim passes.")
    return markdown_text


def process_application(
    job_description: str,
    company: str,
    role: str,
    resume_path: Path | None = None,
    validate: bool = True,
) -> tuple[Path, Path]:
    """
    Full pipeline: tailor master resume → validate → trim to one page → export PDF.

    Returns (md_path, pdf_path). Raises FileNotFoundError if resume_path
    doesn't exist — callers (e.g. main.py) are responsible for turning that
    into a user-facing CLI error.
    """
    resume_path = Path(resume_path) if resume_path else _DEFAULT_RESUME
    if not resume_path.exists():
        raise FileNotFoundError(f"resume not found: {resume_path}")

    master_md = resume_path.read_text()

    date_str = datetime.datetime.now().strftime("%Y%m%d")
    stem = f"{date_str}_{company}_{role}"
    _OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # 1. Tailor + optional judge validation
    suffix = "" if not validate else " + validate"
    print(f"Calling Gemini API (tailor{suffix})...", flush=True)
    tailored_md, result = tailor_resume(
        master_md,
        job_description,
        validate=validate,
    )

    # 2. Report + offer revert if judge found violations
    tailored_md = report_and_maybe_revert(tailored_md, result)

    # 3. Trim to one page if needed
    tailored_md = _ensure_one_page(tailored_md)

    # 4. Write outputs
    md_path = _OUTPUT_DIR / f"{stem}.md"
    pdf_path = _OUTPUT_DIR / f"{stem}.pdf"

    md_path.write_text(tailored_md)
    try:
        display = md_path.relative_to(_PROJECT_ROOT)
    except ValueError:
        display = md_path
    print(f"\nMarkdown saved → {display}")

    generate_resume_pdf(tailored_md, str(pdf_path))

    return md_path, pdf_path
