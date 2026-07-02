import datetime
from pathlib import Path

from llm_client import tailor_resume
from pdf_exporter import generate_resume_pdf
from resume_diff import report_and_maybe_revert

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_RESUME = _PROJECT_ROOT / "data/masters/Jeffrey_Ding_CV_Data_Science.md"
_OUTPUT_DIR = _PROJECT_ROOT / "data/tailored_outputs"


def process_application(
    job_description: str,
    company: str,
    role: str,
    resume_path: Path | None = None,
    validate: bool = True,
) -> tuple[Path, Path]:
    """
    Full pipeline: tailor master resume → validate → export PDF.

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

    # 3. Write outputs
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
