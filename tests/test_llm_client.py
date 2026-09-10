"""
Integration tests for llm_client.py.

These tests make real Gemini API calls and are skipped by default.
Run them explicitly:

    pytest tests/test_llm_client.py -m integration -s

Requires GEMINI_API_KEY to be set in the environment or .env file.

One run of this module costs 3 requests: one per pipeline stage.
"""
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from audit import find_placeholders  # noqa: E402
from llm_client import audit_resume, fact_check, tailor_resume  # noqa: E402

_PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Skip the entire module if the marker isn't requested, so `pytest` (no flags)
# stays fast and never touches the network.
pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def master_md() -> str:
    path = _PROJECT_ROOT / "data/masters/Jeffrey_Ding_CV.md"
    if not path.exists():
        pytest.skip(f"Master resume not found: {path}")
    return path.read_text()


@pytest.fixture(scope="module")
def sample_jd() -> str:
    return (
        "We are looking for a Data Scientist with strong Python and SQL skills. "
        "Experience with machine learning pipelines, cloud platforms (AWS/GCP), "
        "and communicating insights to non-technical stakeholders is required. "
        "Familiarity with clinical or healthcare data is a plus."
    )


def _timed(label: str, fn):
    t0 = time.perf_counter()
    value = fn()
    print(f"\n  [{label}] elapsed: {time.perf_counter() - t0:.2f}s", flush=True)
    return value


# ---------------------------------------------------------------------------
# Stage 1 — audit_resume
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def audit(master_md, sample_jd):
    return _timed("audit", lambda: audit_resume(master_md, sample_jd))


class TestAuditResume:
    def test_succeeds(self, audit):
        assert audit.skipped is False, audit.skip_reason
        assert len(audit.markdown) > 100

    def test_includes_all_required_sections(self, audit):
        for heading in (
            "ATS Score",
            "Keyword Match",
            "Gap Analysis",
            "Tailoring Directives",
            "Quantification",
            "Projected Score",
        ):
            assert heading in audit.markdown

    def test_scores_are_parseable_and_in_range(self, audit):
        assert audit.current_score is not None
        assert 0 <= audit.current_score <= 100
        assert audit.projected_score is not None
        assert 0 <= audit.projected_score <= 100

    def test_tailoring_improves_the_projected_score(self, audit):
        assert audit.projected_score >= audit.current_score

    def test_issues_actionable_directives(self, audit):
        assert len(audit.directives) >= 3


# ---------------------------------------------------------------------------
# Stage 2 — tailor_resume
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def tailored(master_md, sample_jd, audit) -> str:
    return _timed(
        "tailor", lambda: tailor_resume(master_md, sample_jd, audit=audit)
    )


class TestTailorResume:
    def test_returns_nonempty_markdown(self, tailored):
        assert isinstance(tailored, str)
        assert len(tailored) > 100
        assert tailored.startswith("#")

    def test_preserves_contact_line(self, tailored):
        assert "Jeffrey Ding" in tailored

    def test_preserves_all_sections(self, tailored):
        for section in (
            "## Technical Skills",
            "## Education",
            "## Experience",
            "## Projects",
        ):
            assert section in tailored

    def test_does_not_leak_audit_placeholders(self, tailored):
        assert find_placeholders(tailored) == []

    def test_does_not_leak_the_audit_report(self, tailored):
        assert "ATS score" not in tailored
        assert "Tailoring Directives" not in tailored


# ---------------------------------------------------------------------------
# Stage 3 — fact_check
# ---------------------------------------------------------------------------

class TestFactCheck:
    def test_reviews_the_tailored_output(self, master_md, tailored, sample_jd):
        result = _timed(
            "fact_check",
            lambda: fact_check(master_md, tailored, sample_jd),
        )
        assert result.skipped is False, result.skip_reason
        assert isinstance(result.passed, bool)
        print(f"\n{result.summary()}", flush=True)

    def test_unchanged_resume_needs_no_api_call(self, master_md, sample_jd):
        result = fact_check(master_md, master_md, sample_jd)
        assert result.passed is True
        assert result.reviewed == 0
