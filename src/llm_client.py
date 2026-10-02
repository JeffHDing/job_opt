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
from typing import Any, Callable

from dotenv import load_dotenv
from google import genai
from google.genai import types
from google.genai.errors import ClientError, ServerError

from audit import AuditReport, parse_audit_report
from config import DEFAULT_MAX_PAGES, PROJECT_ROOT, PROMPTS_DIR
from resume_diff import (
    ResumeChange,
    ValidationResult,
    find_changes,
    find_unsupported_skills,
)

load_dotenv(PROJECT_ROOT / ".env")

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
# gemini-3.5-flash-lite: 500 RPD on free tier. A full audit + tailor +
# fact-check run costs 3 requests → ~165 applications/day. Skipping the audit
# (--no-audit) or the fact-check (--no-factcheck) drops that to 2.

_MODEL = "gemini-3.5-flash-lite"

# Per-stage overrides. The auditor does the most reasoning and is the one worth
# pointing at a stronger model if you have the quota.
_AUDITOR_MODEL   = _MODEL
_TAILOR_MODEL    = _MODEL
_FACTCHECK_MODEL = _MODEL

_MAX_OUTPUT_TOKENS = 8192

_AUDITOR_SYSTEM_PROMPT   = (PROMPTS_DIR / "auditor_system.txt").read_text()
_TAILOR_SYSTEM_PROMPT    = (PROMPTS_DIR / "tailor_system.txt").read_text()
_FACTCHECK_SYSTEM_PROMPT = (PROMPTS_DIR / "factcheck_system.txt").read_text()


def _generate(
    model: str,
    system_instruction: str,
    contents: str,
    temperature: float,
    **config: Any,
) -> str:
    """Run one Gemini call, with retries, and return the stripped response text."""
    response = _with_retry(lambda: _get_client().models.generate_content(
        model=model,
        config=types.GenerateContentConfig(
            system_instruction=system_instruction,
            temperature=temperature,
            max_output_tokens=_MAX_OUTPUT_TOKENS,
            **config,
        ),
        contents=contents,
    ))
    return response.text.strip()


def _tailor_page_budget(max_pages: int) -> dict[str, int]:
    """Scale the tailor's content caps with the requested page limit."""
    return {
        "max_pages": max_pages,
        "max_exp_roles": 2 + max_pages,
        "max_exp_bullets": 3 + max_pages,
        "max_projects": 5 * max_pages,
        "max_bullets": 20 * max_pages,
    }


def _tailor_system_prompt(max_pages: int) -> str:
    return _TAILOR_SYSTEM_PROMPT.format(**_tailor_page_budget(max_pages))


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
        markdown = _generate(
            model=_AUDITOR_MODEL,
            system_instruction=_AUDITOR_SYSTEM_PROMPT,
            contents=_resume_and_jd(master_resume_md, job_description),
            # The rubric is meant to be reproducible run to run.
            temperature=0.1,
        )
    except Exception as exc:
        return AuditReport(
            markdown="",
            skipped=True,
            skip_reason=f"{type(exc).__name__}: {exc}",
        )

    return parse_audit_report(markdown)


# ---------------------------------------------------------------------------
# Stage 2 — tailor
# ---------------------------------------------------------------------------

def tailor_resume(
    master_resume_md: str,
    job_description: str,
    audit: AuditReport | None = None,
    max_pages: int = DEFAULT_MAX_PAGES,
) -> str:
    """
    Rewrite the master resume for the job description and return the Markdown.

    When *audit* carries a usable report it is appended to the prompt, and the
    tailor works from its directives instead of inferring priorities on its own.
    *max_pages* is injected into the system prompt so the rewrite targets the
    same page budget the PDF trimmer will enforce.
    """
    user_message = _resume_and_jd(master_resume_md, job_description)

    if audit is not None and audit.markdown and not audit.skipped:
        user_message += f"\n\n## ATS Audit\n\n{audit.markdown.strip()}"

    return _generate(
        model=_TAILOR_MODEL,
        system_instruction=_tailor_system_prompt(max_pages),
        contents=user_message,
        temperature=0.3,
    )


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
        verdicts: list[dict] = json.loads(_generate(
            model=_FACTCHECK_MODEL,
            system_instruction=_FACTCHECK_SYSTEM_PROMPT,
            contents=_factcheck_message(
                master_resume_md, job_description, changes
            ),
            temperature=0.0,
            response_mime_type="application/json",
            response_schema=_FACTCHECK_SCHEMA,
        ))
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
        f"{_resume_and_jd(master_resume_md, job_description)}\n\n"
        "## Edits to Review\n\n"
        + "\n\n".join(items)
    )
