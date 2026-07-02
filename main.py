import argparse
import sys
from pathlib import Path

# src/ uses bare imports (e.g. `from resume_diff import ...`), so it must be
# on sys.path before any src module is imported.
sys.path.insert(0, str(Path(__file__).parent / "src"))

from job_processor import process_application  # noqa: E402

_DEFAULT_RESUME = Path(__file__).parent / "data/masters/Jeffrey_Ding_CV_Data_Science.md"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Tailor a master resume to a job description and export a PDF."
    )
    parser.add_argument(
        "--company", "-c",
        required=True,
        metavar="NAME",
        help="Company name (e.g. 'Stripe')",
    )
    parser.add_argument(
        "--role", "-r",
        required=True,
        metavar="TITLE",
        help="Job title, underscores for spaces (e.g. 'Data_Scientist')",
    )
    parser.add_argument(
        "--jd", "-j",
        type=Path,
        default=None,
        metavar="FILE",
        help="Path to job description file (omit to paste via stdin)",
    )
    parser.add_argument(
        "--resume",
        type=Path,
        default=_DEFAULT_RESUME,
        metavar="FILE",
        help=f"Master resume Markdown (default: {_DEFAULT_RESUME.name})",
    )
    parser.add_argument(
        "--no-validate",
        action="store_true",
        help="Skip the judge validation step (faster, 1 API call instead of 2)",
    )
    args = parser.parse_args()

    # Read job description
    if args.jd is not None:
        if not args.jd.exists():
            print(f"error: JD file not found: {args.jd}", file=sys.stderr)
            sys.exit(1)
        job_description = args.jd.read_text()
    else:
        if sys.stdin.isatty():
            print("Paste job description, then press Ctrl-D (Ctrl-Z on Windows):")
        job_description = sys.stdin.read()

    if not job_description.strip():
        print("error: job description is empty", file=sys.stderr)
        sys.exit(1)

    print(f"\nTailoring resume for {args.role} at {args.company}...\n")

    md_path, pdf_path = process_application(
        job_description=job_description,
        company=args.company,
        role=args.role,
        resume_path=args.resume,
        validate=not args.no_validate,
    )

    print(f"\nDone!  PDF → {pdf_path.relative_to(Path(__file__).parent)}")


if __name__ == "__main__":
    main()
