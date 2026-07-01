import json
import os
import time
from pathlib import Path
from typing import Any, Callable

from dotenv import load_dotenv
from google import genai
from google.genai import types
from google.genai.errors import ClientError, ServerError

from resume_diff import BulletChange, ValidationResult, find_changed_bullets, revert_violations

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_PROJECT_ROOT / ".env")

_PROMPTS_DIR = _PROJECT_ROOT / "prompts"

# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------

_client: genai.Client | None = None


def _get_client() -> genai.Client:
    global _client
    if _client is None:
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise EnvironmentError(
                "GEMINI_API_KEY is not set. Copy .env.example to .env and add your key, "
                "or export it: export GEMINI_API_KEY='your-key'"
            )
        _client = genai.Client(api_key=api_key)
    return _client

# ---------------------------------------------------------------------------
# Retry helper
# ---------------------------------------------------------------------------

_RETRY_ATTEMPTS = 3
_RETRY_BASE_DELAY = 5.0   # seconds; doubles each attempt


def _with_retry(fn: Callable[[], Any]) -> Any:
    """
    Call fn() up to _RETRY_ATTEMPTS times, retrying on 503 (server overload)
    or 429 (rate-limit) with exponential backoff. All other exceptions propagate.
    """
    delay = _RETRY_BASE_DELAY
    for attempt in range(1, _RETRY_ATTEMPTS + 1):
        try:
            return fn()
        except (ServerError, ClientError) as exc:
            retryable = (
                (isinstance(exc, ServerError) and exc.code == 503)
                or (isinstance(exc, ClientError) and exc.code == 429)
            )
            if not retryable or attempt == _RETRY_ATTEMPTS:
                raise
            label = "503 overload" if exc.code == 503 else "429 rate-limit"
            print(
                f"  {label} from Gemini (attempt {attempt}/{_RETRY_ATTEMPTS}), "
                f"retrying in {delay:.0f}s...",
                flush=True,
            )
            time.sleep(delay)
            delay *= 2


# ---------------------------------------------------------------------------
# Model config
# ---------------------------------------------------------------------------
# gemini-3.1-flash-lite: 500 RPD on free tier
# Both calls in this script cost 2 requests per run → ~250 applications/day

_TAILOR_MODEL = "gemini-3.1-flash-lite"
_JUDGE_MODEL  = "gemini-3.1-flash-lite"


_TAILOR_SYSTEM_PROMPT = (_PROMPTS_DIR / "tailor_system.txt").read_text()
_JUDGE_SYSTEM_PROMPT  = (_PROMPTS_DIR / "judge_system.txt").read_text()


# ---------------------------------------------------------------------------
# Judge call
# ---------------------------------------------------------------------------

def _validate_changes(
    changes: list[BulletChange],
    job_description: str,
    client: genai.Client,
) -> ValidationResult:
    """
    Send only the changed bullets to a second LLM call for fact-checking.
    Returns a ValidationResult; never raises — on any error it returns skipped=True.
    """
    if not changes:
        return ValidationResult(passed=True)

    # Build a compact numbered list of changed bullets for the judge
    items = []
    for i, c in enumerate(changes, 1):
        items.append(
            f"[{i}] Section: {c.section}\n"
            f"    Original: \"{c.original}\"\n"
            f"    Tailored:  \"{c.tailored}\""
        )

    user_message = (
        "## Job Description\n\n"
        f"{job_description.strip()}\n\n"
        "## Bullet Edits to Review\n\n"
        + "\n\n".join(items)
    )

    try:
        response = _with_retry(lambda: client.models.generate_content(
            model=_JUDGE_MODEL,
            config=types.GenerateContentConfig(
                system_instruction=_JUDGE_SYSTEM_PROMPT,
                temperature=0.0,
                max_output_tokens=8192,
                response_mime_type="application/json",
            ),
            contents=user_message,
        ))
        verdicts: list[dict] = json.loads(response.text)
    except json.JSONDecodeError as exc:
        return ValidationResult(
            passed=True,
            skipped=True,
            skip_reason=f"JSONDecodeError (malformed model output): {exc}",
        )
    except Exception as exc:
        return ValidationResult(
            passed=True,
            skipped=True,
            skip_reason=f"{type(exc).__name__}: {exc}",
        )

    violations = [v for v in verdicts if not v.get("supported", True)]
    return ValidationResult(passed=len(violations) == 0, violations=violations)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def tailor_resume(
    master_resume_md: str,
    job_description: str,
    validate: bool = True,
) -> tuple[str, ValidationResult]:
    """
    Tailor a master resume to a job description using Gemini.

    Returns (tailored_markdown, ValidationResult). When validate=True a second
    judge call reviews only the changed bullets; on any judge failure the result
    is returned with skipped=True rather than raising.
    """
    client = _get_client()

    user_message = (
        "## Master Resume\n\n"
        f"{master_resume_md.strip()}\n\n"
        "## Job Description\n\n"
        f"{job_description.strip()}"
    )

    response = _with_retry(lambda: client.models.generate_content(
        model=_TAILOR_MODEL,
        config=types.GenerateContentConfig(
            system_instruction=_TAILOR_SYSTEM_PROMPT,
            temperature=0.3,
            max_output_tokens=8192,
        ),
        contents=user_message,
    ))

    tailored_md = response.text.strip()

    if not validate:
        return tailored_md, ValidationResult(passed=True, skipped=True, skip_reason="validate=False")

    changes = find_changed_bullets(master_resume_md, tailored_md)
    validation = _validate_changes(changes, job_description, client)
    return tailored_md, validation


# ---------------------------------------------------------------------------
# CLI entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse
    import sys

    _DEFAULT_RESUME = _PROJECT_ROOT / "data/templates/Jeffrey_Ding_CV_Data_Science.md"

    parser = argparse.ArgumentParser(
        description="Tailor a Markdown resume to a job description using Gemini.",
    )
    parser.add_argument(
        "--resume", "-r",
        type=Path,
        default=_DEFAULT_RESUME,
        metavar="FILE",
        help=f"Path to master resume Markdown (default: {_DEFAULT_RESUME.relative_to(_PROJECT_ROOT)})",
    )
    parser.add_argument(
        "--jd", "-j",
        type=Path,
        default=None,
        metavar="FILE",
        help="Path to job description text file (omit to read from stdin)",
    )
    parser.add_argument(
        "--no-validate",
        action="store_true",
        help="Skip the judge validation call",
    )
    parser.add_argument(
        "--out", "-o",
        type=Path,
        default=None,
        metavar="FILE",
        help="Write final Markdown to FILE instead of stdout",
    )
    args = parser.parse_args()

    if not args.resume.exists():
        print(f"error: resume not found: {args.resume}", file=sys.stderr)
        sys.exit(1)

    if args.jd is not None:
        if not args.jd.exists():
            print(f"error: JD file not found: {args.jd}", file=sys.stderr)
            sys.exit(1)
        jd_text = args.jd.read_text()
    else:
        if sys.stdin.isatty():
            print("Paste job description, then press Ctrl-D (Ctrl-Z on Windows):")
        jd_text = sys.stdin.read()

    if not jd_text.strip():
        print("error: job description is empty", file=sys.stderr)
        sys.exit(1)

    print("Calling Gemini API (tailor" + ("" if args.no_validate else " + validate") + ")...", flush=True)
    tailored, result = tailor_resume(
        args.resume.read_text(),
        jd_text,
        validate=not args.no_validate,
    )

    print("\n--- Validation Report ---\n")
    print(result.summary())

    if not result.passed and not result.skipped:
        print()
        try:
            answer = input("Revert flagged bullets to originals? [y/N] ").strip().lower()
        except EOFError:
            answer = "n"

        if answer == "y":
            tailored = revert_violations(tailored, result.violations)
            print("Reverted violations to originals.")

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(tailored)
        print(f"\nSaved to {args.out}")
    else:
        print("\n--- Tailored Resume ---\n")
        print(tailored)
