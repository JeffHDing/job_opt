import datetime
import sys
from pathlib import Path

from llm_client import tailor_resume
from pdf_exporter import generate_resume_pdf
from resume_diff import revert_violations

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

    Returns (md_path, pdf_path).
    """
    resume_path = Path(resume_path) if resume_path else _DEFAULT_RESUME
    if not resume_path.exists():
        print(f"error: resume not found: {resume_path}", file=sys.stderr)
        sys.exit(1)

    master_md = resume_path.read_text()

    # 1. Tailor + optional judge validation
    suffix = "" if not validate else " + validate"
    print(f"Calling Gemini API (tailor{suffix})...", flush=True)
    tailored_md, result = tailor_resume(master_md, job_description, validate=validate)

    # 2. Print validation report
    print("\n--- Validation Report ---\n")
    print(result.summary())

    # 3. Offer revert if judge found violations
    if not result.passed and not result.skipped:
        print()
        try:
            answer = input("Revert flagged bullets to originals? [y/N] ").strip().lower()
        except EOFError:
            answer = "n"
        if answer == "y":
            tailored_md = revert_violations(tailored_md, result.violations)
            print("Reverted violations to originals.")

    # 4. Write outputs
    date_str = datetime.datetime.now().strftime("%Y%m%d")
    stem = f"{date_str}_{company}_{role}"
    _OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    md_path = _OUTPUT_DIR / f"{stem}.md"
    pdf_path = _OUTPUT_DIR / f"{stem}.pdf"

    md_path.write_text(tailored_md)
    print(f"\nMarkdown saved → {md_path.relative_to(_PROJECT_ROOT)}")

    generate_resume_pdf(tailored_md, str(pdf_path))

    return md_path, pdf_path
