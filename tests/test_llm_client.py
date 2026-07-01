"""
Integration tests for llm_client.py.

These tests make real Gemini API calls and are skipped by default.
Run them explicitly:

    pytest tests/test_llm_client.py -m integration -s

Requires GEMINI_API_KEY to be set in the environment or .env file.
"""
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from llm_client import tailor_resume  # noqa: E402

_PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Skip the entire module if the marker isn't requested, so `pytest` (no flags)
# stays fast and never touches the network.
pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def master_md() -> str:
    path = _PROJECT_ROOT / "data/templates/Jeffrey_Ding_CV_Data_Science.md"
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


@pytest.fixture(scope="module")
def tailor_result(master_md, sample_jd) -> tuple[str, object]:
    """Single tailor+validate API call shared across all tests that need it."""
    t0 = time.perf_counter()
    tailored, result = tailor_resume(master_md, sample_jd)
    elapsed = time.perf_counter() - t0
    print(f"\n  [tailor_result fixture] elapsed: {elapsed:.2f}s", flush=True)
    return tailored, result


# ---------------------------------------------------------------------------
# tailor_resume
# ---------------------------------------------------------------------------

class TestTailorResume:
    def test_returns_nonempty_markdown(self, tailor_result):
        tailored, _ = tailor_result
        assert isinstance(tailored, str)
        assert len(tailored) > 100
        assert tailored.startswith("#")

    def test_validation_result_has_passed_field(self, tailor_result):
        _, result = tailor_result
        assert isinstance(result.passed, bool)

    def test_validate_false_skips_judge(self, master_md, sample_jd):
        t0 = time.perf_counter()
        _, result = tailor_resume(master_md, sample_jd, validate=False)
        elapsed = time.perf_counter() - t0
        msg = f"\n  [test_validate_false_skips_judge] elapsed: {elapsed:.2f}s"
        print(msg, flush=True)
        assert result.skipped is True
        assert result.skip_reason == "validate=False"

    def test_tailored_preserves_contact_line(self, tailor_result):
        tailored, _ = tailor_result
        assert "Jeffrey Ding" in tailored

    def test_tailored_preserves_all_sections(self, tailor_result):
        tailored, _ = tailor_result
        sections = (
            "## Technical Skills",
            "## Education",
            "## Experience",
            "## Projects",
        )
        for section in sections:
            assert section in tailored
