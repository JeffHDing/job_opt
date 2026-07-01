"""
Integration tests for llm_client.py.

These tests make real Gemini API calls and are skipped by default.
Run them explicitly:

    pytest tests/test_llm_client.py -m integration

Requires GEMINI_API_KEY to be set in the environment or .env file.
"""
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

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


# ---------------------------------------------------------------------------
# tailor_resume
# ---------------------------------------------------------------------------

class TestTailorResume:
    def test_returns_nonempty_markdown(self, master_md, sample_jd):
        from llm_client import tailor_resume
        tailored, result = tailor_resume(master_md, sample_jd)
        assert isinstance(tailored, str)
        assert len(tailored) > 100
        assert tailored.startswith("#")

    def test_validation_result_has_passed_field(self, master_md, sample_jd):
        from llm_client import tailor_resume
        _, result = tailor_resume(master_md, sample_jd)
        assert isinstance(result.passed, bool)

    def test_validate_false_skips_judge(self, master_md, sample_jd):
        from llm_client import tailor_resume
        _, result = tailor_resume(master_md, sample_jd, validate=False)
        assert result.skipped is True
        assert result.skip_reason == "validate=False"

    def test_tailored_preserves_contact_line(self, master_md, sample_jd):
        from llm_client import tailor_resume
        tailored, _ = tailor_resume(master_md, sample_jd)
        assert "Jeffrey Ding" in tailored

    def test_tailored_preserves_all_sections(self, master_md, sample_jd):
        from llm_client import tailor_resume
        tailored, _ = tailor_resume(master_md, sample_jd)
        for section in ("## Technical Skills", "## Education", "## Experience", "## Projects"):
            assert section in tailored
