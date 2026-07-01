import json
import os
import time
from pathlib import Path
from typing import Any, Callable

from dotenv import load_dotenv
from google import genai
from google.genai import types
from google.genai.errors import ServerError

from resume_diff import BulletChange, ValidationResult, find_changed_bullets, revert_violations

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_PROJECT_ROOT / ".env")

# ---------------------------------------------------------------------------
# Model config
# ---------------------------------------------------------------------------
# gemini-3.1-flash-lite: 500 RPD on free tier
# Both calls in this script cost 2 requests per run → ~250 applications/day
_TAILOR_MODEL = "gemini-3.1-flash-lite"
_JUDGE_MODEL  = "gemini-3.1-flash-lite"

_TAILOR_SYSTEM_PROMPT = """\
You are an expert resume writer and ATS optimisation specialist.

Your job is to tailor a master resume (in Markdown) to a specific job description
while following these rules:

1. **Preserve structure exactly** — keep the same Markdown headings, sections,
   and list format as the input resume. Do not add, remove, or rename sections.
2. **Reorder and reweight bullet points** — move the most relevant bullets to the
   top within each section. Cut bullets only when they are genuinely irrelevant
   and space is needed; never fabricate experience.
3. **Incorporate appropriate keywords** — you may substitute a single word or short phrase inside
   an existing bullet with high-signal keywords from the job
   description (skills, tools, methodologies) ONLY when the substitution is directly supported by the
   original bullet's context (e.g. "data" → "clinical data" for a hospital role).
   Do NOT append new clauses or phrases to a bullet.
4. **Stay factual** — never invent metrics, titles, dates, tools, or domain claims
   not already present in the master resume. When in doubt, reorder rather than rewrite.
5. **Output only Markdown** — return the tailored resume as clean Markdown with
   no commentary, preamble, or code fences.
"""

_JUDGE_SYSTEM_PROMPT = """\
You are a strict fact-checker for resume edits. You receive a list of bullet-point
changes (original vs. tailored) and the job description that motivated them.

Your task: decide whether each tailored bullet adds claims not supported by the original.

Allowed changes:
  - Reordering words within the same sentence
  - Swapping one word for a direct synonym already used elsewhere in the original bullet
  - Adding a domain adjective (e.g. "data" → "clinical data") ONLY when the original
    role is explicitly at a healthcare or clinical institution

Forbidden changes:
  - Appending new clauses or phrases ("and demonstrating...", "including...", "showcasing...")
  - Adding skills, tools, methodologies, or domains not stated in the original bullet
  - Inferring capabilities from the job description that the original does not state

Return ONLY valid JSON — a single array, one object per bullet reviewed:
[
  {
    "original": "<original bullet text>",
    "tailored": "<tailored bullet text>",
    "supported": true | false,
    "reason": "<one sentence explaining the verdict>"
  }
]

Return [] if there are no changed bullets to review.
"""


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
                max_output_tokens=1024,
                response_mime_type="application/json",
            ),
            contents=user_message,
        ))
        verdicts: list[dict] = json.loads(response.text)
    except Exception as exc:
        return ValidationResult(
            passed=True,
            skipped=True,
            skip_reason=f"{type(exc).__name__}: {exc}",
        )

    violations = [v for v in verdicts if not v.get("supported", True)]
    return ValidationResult(passed=len(violations) == 0, violations=violations)


# ---------------------------------------------------------------------------
# Retry helper
# ---------------------------------------------------------------------------

_RETRY_ATTEMPTS = 3
_RETRY_BASE_DELAY = 5.0   # seconds; doubles each attempt


def _with_retry(fn: Callable[[], Any]) -> Any:
    """
    Call fn() up to _RETRY_ATTEMPTS times, retrying on 503 ServerError with
    exponential backoff. All other exceptions propagate immediately.
    """
    delay = _RETRY_BASE_DELAY
    for attempt in range(1, _RETRY_ATTEMPTS + 1):
        try:
            return fn()
        except ServerError as exc:
            if exc.status_code != 503 or attempt == _RETRY_ATTEMPTS:
                raise
            print(
                f"  503 from Gemini (attempt {attempt}/{_RETRY_ATTEMPTS}), "
                f"retrying in {delay:.0f}s...",
                flush=True,
            )
            time.sleep(delay)
            delay *= 2


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------

def _get_client() -> genai.Client:
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise EnvironmentError(
            "GEMINI_API_KEY is not set. Copy .env.example to .env and add your key, "
            "or export it: export GEMINI_API_KEY='your-key'"
        )
    return genai.Client(api_key=api_key)


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
            max_output_tokens=4096,
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
# Smoke test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    resume_path = _PROJECT_ROOT / "data/templates/Jeffrey_Ding_CV_Data_Science.md"
    if not resume_path.exists():
        print(f"Resume not found at {resume_path}", file=sys.stderr)
        sys.exit(1)

    sample_jd = """\
We are looking for a Data Scientist with strong Python and SQL skills.
Experience with machine learning pipelines, cloud platforms (AWS/GCP),
and communicating insights to non-technical stakeholders is required.
Familiarity with clinical or healthcare data is a plus.
"""

    print("Calling Gemini API (tailor + validate)...", flush=True)
    tailored, result = tailor_resume(resume_path.read_text(), sample_jd)

    print("\n--- Tailored Resume ---\n")
    print(tailored)
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
            print("\n--- Reverted Resume (violations restored to originals) ---\n")
            print(tailored)
        else:
            print("Keeping tailored output as-is.")
