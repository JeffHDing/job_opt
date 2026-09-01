"""
llm_client.py — the three Gemini agents behind the pipeline.

Each public function is exactly one stage of the workflow:

  1. audit_resume()  — score the master resume as an ATS would and issue
                       tailoring directives.
  2. tailor_resume() — rewrite the master against those directives.
  3. fact_check()    — verify nothing in the rewrite outruns the master.

Stages 1 and 3 are advisory: they degrade to a "skipped" result rather than
raising, so a transient API failure can't cost the user their tailored resume.
Stage 2 raises, because there is no output without it.
"""
import json
import os
import time
from pathlib import Path
from typing import Any, Callable

from dotenv import load_dotenv
from google import genai
from google.genai import types
from google.genai.errors import ClientError, ServerError

from audit import AuditReport, parse_audit_report
from resume_diff import (
    ResumeChange,
    ValidationResult,
    find_changes,
    find_unsupported_skills,
)

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
                "GEMINI_API_KEY is not set. "
                "Copy .env.example to .env and add your key, "
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
# gemini-3.1-flash-lite: 500 RPD on free tier. A full audit + tailor +
# fact-check run costs 3 requests → ~165 applications/day. Skipping the audit
# (--no-audit) or the fact-check (--no-factcheck) drops that to 2.

_AUDITOR_MODEL   = "gemini-3.1-flash-lite"
_TAILOR_MODEL    = "gemini-3.1-flash-lite"
_FACTCHECK_MODEL = "gemini-3.1-flash-lite"

_AUDITOR_SYSTEM_PROMPT   = (_PROMPTS_DIR / "auditor_system.txt").read_text()
_TAILOR_SYSTEM_PROMPT    = (_PROMPTS_DIR / "tailor_system.txt").read_text()
_FACTCHECK_SYSTEM_PROMPT = (_PROMPTS_DIR / "factcheck_system.txt").read_text()


def _resume_and_jd(master_resume_md: str, job_description: str) -> str:
    return (
        "## Master Resume\n\n"
        f"{master_resume_md.strip()}\n\n"
        "## Job Description\n\n"
        f"{job_description.strip()}"
    )


# ---------------------------------------------------------------------------
# Stage 1 — audit
# ---------------------------------------------------------------------------

def audit_resume(master_resume_md: str, job_description: str) -> AuditReport:
    """
    Score the master resume against the job description as an ATS would.

    Returns an AuditReport carrying the full Markdown report, the current and
    projected scores, and the numbered directives the tailor will execute.
    On any API or parsing failure the report comes back with skipped=True so
    the pipeline can fall back to untargeted tailoring.
    """
    try:
        response = _with_retry(lambda: _get_client().models.generate_content(
            model=_AUDITOR_MODEL,
            config=types.GenerateContentConfig(
                system_instruction=_AUDITOR_SYSTEM_PROMPT,
                # The rubric is meant to be reproducible run to run.
                temperature=0.1,
                max_output_tokens=8192,
            ),
            contents=_resume_and_jd(master_resume_md, job_description),
        ))
    except Exception as exc:
        return AuditReport(
            markdown="",
            skipped=True,
            skip_reason=f"{type(exc).__name__}: {exc}",
        )

    return parse_audit_report(response.text.strip())


# ---------------------------------------------------------------------------
# Stage 2 — tailor
# ---------------------------------------------------------------------------

def tailor_resume(
    master_resume_md: str,
    job_description: str,
    audit: AuditReport | None = None,
) -> str:
    """
    Rewrite the master resume for the job description and return the Markdown.

    When *audit* carries a usable report it is appended to the prompt, and the
    tailor works from its directives instead of inferring priorities on its own.
    """
    user_message = _resume_and_jd(master_resume_md, job_description)

    if audit is not None and audit.markdown and not audit.skipped:
        user_message += f"\n\n## ATS Audit\n\n{audit.markdown.strip()}"

    response = _with_retry(lambda: _get_client().models.generate_content(
        model=_TAILOR_MODEL,
        config=types.GenerateContentConfig(
            system_instruction=_TAILOR_SYSTEM_PROMPT,
            temperature=0.3,
            max_output_tokens=8192,
        ),
        contents=user_message,
    ))

    return response.text.strip()


# ---------------------------------------------------------------------------
# Stage 3 — fact-check
# ---------------------------------------------------------------------------

# Constraining the response shape keeps `original` and `tailored` verbatim,
# which is what makes automatic reverting possible.
_FACTCHECK_SCHEMA = types.Schema(
    type=types.Type.ARRAY,
    items=types.Schema(
        type=types.Type.OBJECT,
        required=["original", "tailored", "supported", "severity", "reason"],
        properties={
            "original": types.Schema(type=types.Type.STRING),
            "tailored": types.Schema(type=types.Type.STRING),
            "supported": types.Schema(type=types.Type.BOOLEAN),
            "severity": types.Schema(
                type=types.Type.STRING, enum=["none", "minor", "major"]
            ),
            "reason": types.Schema(type=types.Type.STRING),
        },
    ),
)


def fact_check(
    master_resume_md: str,
    tailored_md: str,
    job_description: str,
) -> ValidationResult:
    """
    Check the tailored resume for claims the master resume does not support.

    Only content that actually changed is sent for review — anything carried
    over verbatim is supported by definition — which keeps this call small even
    for a heavily rewritten resume. Never raises: any failure comes back as
    skipped=True so the tailored resume still reaches the user, with any
    deterministic findings still attached.
    """
    changes = find_changes(master_resume_md, tailored_md)
    padded_skills = find_unsupported_skills(master_resume_md, tailored_md)

    if not changes:
        return ValidationResult(passed=True, reviewed=0)

    try:
        response = _with_retry(lambda: _get_client().models.generate_content(
            model=_FACTCHECK_MODEL,
            config=types.GenerateContentConfig(
                system_instruction=_FACTCHECK_SYSTEM_PROMPT,
                temperature=0.0,
                max_output_tokens=8192,
                response_mime_type="application/json",
                response_schema=_FACTCHECK_SCHEMA,
            ),
            contents=_factcheck_message(
                master_resume_md, job_description, changes
            ),
        ))
        verdicts: list[dict] = json.loads(response.text)
    except json.JSONDecodeError as exc:
        return _skipped(
            changes, padded_skills,
            f"JSONDecodeError (malformed model output): {exc}",
        )
    except Exception as exc:
        return _skipped(changes, padded_skills, f"{type(exc).__name__}: {exc}")

    violations = _merge(
        [v for v in verdicts if not v.get("supported", True)], padded_skills
    )
    return ValidationResult(
        passed=not violations,
        violations=violations,
        reviewed=len(changes),
    )


def _merge(model_violations: list[dict], extra: list[dict]) -> list[dict]:
    """Add deterministic violations the model did not already flag."""
    flagged = {v.get("tailored") for v in model_violations}
    return model_violations + [v for v in extra if v["tailored"] not in flagged]


def _skipped(
    changes: list[ResumeChange], extra: list[dict], reason: str
) -> ValidationResult:
    return ValidationResult(
        passed=not extra,
        violations=extra,
        reviewed=len(changes),
        skipped=True,
        skip_reason=reason,
    )


def _factcheck_message(
    master_resume_md: str,
    job_description: str,
    changes: list[ResumeChange],
) -> str:
    items = [
        f"[{i}] Section: {c.section}\n"
        f"    Kind: {c.kind}\n"
        f'    Original: "{c.original}"\n'
        f'    Tailored: "{c.tailored}"'
        for i, c in enumerate(changes, 1)
    ]
    return (
        "## Master Resume\n\n"
        f"{master_resume_md.strip()}\n\n"
        "## Job Description\n\n"
        f"{job_description.strip()}\n\n"
        "## Edits to Review\n\n"
        + "\n\n".join(items)
    )
