"""
main.py — the single CLI entry point.

Runs the three-stage workflow: audit the master resume as an ATS would, tailor
it against the audit's directives, then fact-check the result against the
master. Individual stages can be switched off with the --no-* flags.
"""
import argparse
import sys
from pathlib import Path

import pyperclip

# src/ uses bare imports (e.g. `from resume_diff import ...`), so it must be
# on sys.path before any src module is imported.
sys.path.insert(0, str(Path(__file__).parent / "src"))

from job_processor import process_application, run_audit  # noqa: E402

_PROJECT_ROOT = Path(__file__).parent
_DEFAULT_RESUME = _PROJECT_ROOT / "data/masters/Jeffrey_Ding_CV.md"
_CLIPBOARD_PREVIEW_LENGTH = 300


def _clipboard_job_description() -> str | None:
    try:
        text = pyperclip.paste()
    except pyperclip.PyperclipException:
        return None
    return text if text.strip() else None


def _confirm_clipboard_job_description(job_description: str) -> bool:
    preview = " ".join(job_description.split())
    if len(preview) > _CLIPBOARD_PREVIEW_LENGTH:
        preview = f"{preview[:_CLIPBOARD_PREVIEW_LENGTH].rstrip()}..."

    print("\nJob description found in clipboard:")
    print(f'  "{preview}"')
    response = input("\nUse this job description? [Y/n]: ").strip().lower()
    return response in {"", "y", "yes"}


def _read_job_description() -> str:
    clipboard_text = _clipboard_job_description()
    if clipboard_text and _confirm_clipboard_job_description(clipboard_text):
        return clipboard_text

    print("Paste job description, then press Ctrl-D (Ctrl-Z on Windows):")
    return sys.stdin.read()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Audit a master resume against a job description, tailor it to the "
            "audit's findings, and fact-check the result."
        )
    )
    parser.add_argument(
        "--company", "-c",
        metavar="NAME",
        help="Company name (prompted if omitted)",
    )
    parser.add_argument(
        "--role", "-r",
        metavar="TITLE",
        help="Job title (prompted if omitted)",
    )
    parser.add_argument(
        "--jd", "-j",
        type=Path,
        default=None,
        metavar="FILE",
        help="Path to job description file (defaults to clipboard interactively)",
    )
    parser.add_argument(
        "--resume",
        type=Path,
        default=_DEFAULT_RESUME,
        metavar="FILE",
        help=f"Master resume Markdown (default: {_DEFAULT_RESUME.name})",
    )
    parser.add_argument(
        "--audit-only",
        action="store_true",
        help="Run the ATS audit and stop; write the report without tailoring",
    )
    parser.add_argument(
        "--no-audit",
        action="store_true",
        help="Tailor without auditing first (saves one API call)",
    )
    parser.add_argument(
        "--no-factcheck",
        action="store_true",
        help="Skip the fact-check stage (saves one API call)",
    )
    parser.add_argument(
        "--no-pdf",
        action="store_true",
        help="Write the tailored Markdown only, skipping PDF export",
    )
    return parser


def _resolve_job_description(args: argparse.Namespace) -> str:
    if args.jd is not None:
        if not args.jd.exists():
            print(f"error: JD file not found: {args.jd}", file=sys.stderr)
            sys.exit(1)
        return args.jd.read_text()
    if sys.stdin.isatty():
        return _read_job_description()
    return sys.stdin.read()


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    if args.audit_only and args.no_audit:
        parser.error("--audit-only and --no-audit are mutually exclusive")

    if args.company is None:
        args.company = input("Company: ").strip()
    if not args.company:
        parser.error("company cannot be empty")

    if args.role is None:
        args.role = input("Role title: ").strip()
    if not args.role:
        parser.error("role title cannot be empty")

    job_description = _resolve_job_description(args)
    if not job_description.strip():
        print("error: job description is empty", file=sys.stderr)
        sys.exit(1)

    action = "Auditing" if args.audit_only else "Tailoring"
    print(f"\n{action} resume for {args.role} at {args.company}...\n")

    try:
        if args.audit_only:
            _, audit_path = run_audit(
                job_description=job_description,
                company=args.company,
                role=args.role,
                resume_path=args.resume,
            )
            if audit_path is None:
                sys.exit(1)
            return

        result = process_application(
            job_description=job_description,
            company=args.company,
            role=args.role,
            resume_path=args.resume,
            audit=not args.no_audit,
            factcheck=not args.no_factcheck,
            export_pdf=not args.no_pdf,
        )
    except FileNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(1)

    final = result.pdf_path or result.md_path
    try:
        final = final.relative_to(_PROJECT_ROOT)
    except ValueError:
        pass
    print(f"\nDone!  {final}")


if __name__ == "__main__":
    main()
