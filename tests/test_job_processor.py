"""
Unit tests for job_processor.py.

All external side effects (Gemini calls, PDF rendering, interactive revert
prompt) are mocked so these run fast and offline.
"""
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import job_processor  # noqa: E402
from job_processor import _trim_one_bullet, process_application  # noqa: E402
from resume_diff import ValidationResult  # noqa: E402


def _make_resume(tmp_path: Path, content: str = "# Resume\n\n- bullet\n") -> Path:
    p = tmp_path / "resume.md"
    p.write_text(content)
    return p


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _patch_externals(get_page_count_pages: int = 1):
    """
    Return a context-manager stack that patches all external calls used by
    process_application.  get_page_count_pages controls what the page-count
    check returns (default 1 → no trimming needed).
    """
    return (
        patch(
            "job_processor.get_page_count",
            return_value=get_page_count_pages
            ),
        patch("job_processor.generate_resume_pdf"),
    )


# ---------------------------------------------------------------------------
# ProcessApplication tests
# ---------------------------------------------------------------------------

class TestProcessApplication:
    def test_raises_when_resume_missing(self, tmp_path):
        with pytest.raises(FileNotFoundError, match="resume not found"):
            process_application(
                job_description="jd",
                company="Acme",
                role="Engineer",
                resume_path=tmp_path / "missing.md",
            )

    def test_uses_default_resume_when_none_given(self, tmp_path, monkeypatch):
        default_resume = tmp_path / "default.md"
        default_resume.write_text("# Default Resume\n- bullet\n")
        monkeypatch.setattr(job_processor, "_DEFAULT_RESUME", default_resume)
        monkeypatch.setattr(job_processor, "_OUTPUT_DIR", tmp_path)
        validation = ValidationResult(passed=True, skipped=True, skip_reason="x")
        gpc, gpdf = _patch_externals()
        with patch(
            "job_processor.tailor_resume",
            return_value=("# Tailored\n", validation),
        ) as mock_tailor, gpc, gpdf:
            process_application(job_description="jd", company="Acme", role="Eng")
        assert mock_tailor.call_args[0][0] == "# Default Resume\n- bullet\n"

    def test_writes_output_files(self, tmp_path, monkeypatch):
        resume = _make_resume(tmp_path)
        monkeypatch.setattr(job_processor, "_OUTPUT_DIR", tmp_path / "out")
        validation = ValidationResult(passed=True, skipped=False)
        gpc, gpdf = _patch_externals()
        with patch(
            "job_processor.tailor_resume",
            return_value=("# Tailored\n- bullet\n", validation),
        ), gpc, gpdf as mock_pdf:
            md_path, pdf_path = process_application(
                job_description="jd",
                company="Stripe",
                role="Data_Scientist",
                resume_path=resume,
            )
        assert md_path.exists()
        assert md_path.read_text() == "# Tailored\n- bullet\n"
        assert md_path.suffix == ".md"
        assert pdf_path.suffix == ".pdf"
        assert "Stripe_Data_Scientist" in md_path.name
        assert "Stripe_Data_Scientist" in pdf_path.name
        assert md_path.stem == pdf_path.stem
        mock_pdf.assert_called_once_with("# Tailored\n- bullet\n", str(pdf_path))

    def test_validate_flag_passed_through(self, tmp_path, monkeypatch):
        resume = _make_resume(tmp_path)
        monkeypatch.setattr(job_processor, "_OUTPUT_DIR", tmp_path / "out")
        validation = ValidationResult(passed=True, skipped=True, skip_reason="x")
        gpc, gpdf = _patch_externals()
        with patch(
            "job_processor.tailor_resume", return_value=("# Out\n", validation)
        ) as mock_tailor, gpc, gpdf:
            process_application(
                job_description="jd",
                company="Acme",
                role="Eng",
                resume_path=resume,
                validate=False,
            )
        assert mock_tailor.call_args.kwargs["validate"] is False

    @pytest.mark.parametrize("user_input, expected_bullet, reverted", [
        ("y", "good bullet", True),
        ("n", "bad bullet",  False),
    ])
    def test_revert_decision_flows_to_output(
        self, tmp_path, monkeypatch, user_input, expected_bullet, reverted
    ):
        resume = _make_resume(tmp_path)
        monkeypatch.setattr(job_processor, "_OUTPUT_DIR", tmp_path / "out")
        violations = [{"original": "good bullet", "tailored": "bad bullet"}]
        validation = ValidationResult(passed=False, violations=violations)
        gpc, gpdf = _patch_externals()
        with patch(
            "job_processor.tailor_resume",
            return_value=("## S\n- bad bullet\n", validation),
        ), gpc, gpdf as mock_pdf, \
             patch("builtins.input", return_value=user_input):
            md_path, _ = process_application(
                job_description="jd",
                company="Acme",
                role="Eng",
                resume_path=resume,
            )
        assert expected_bullet in md_path.read_text()
        if reverted:
            mock_pdf.assert_called_once()
            assert "good bullet" in mock_pdf.call_args[0][0]

    def test_creates_output_dir_if_missing(self, tmp_path, monkeypatch):
        resume = _make_resume(tmp_path)
        nested_out = tmp_path / "nested" / "out"
        monkeypatch.setattr(job_processor, "_OUTPUT_DIR", nested_out)
        validation = ValidationResult(passed=True, skipped=False)
        gpc, gpdf = _patch_externals()
        with patch(
            "job_processor.tailor_resume", return_value=("# Out\n", validation)
        ), gpc, gpdf:
            process_application(
                job_description="jd", company="Acme", role="Eng", resume_path=resume
            )
        assert nested_out.exists()

    def test_trim_loop_runs_when_overflow_detected(self, tmp_path, monkeypatch):
        """If get_page_count reports > 1 page, bullets should be trimmed."""
        resume = _make_resume(tmp_path)
        monkeypatch.setattr(job_processor, "_OUTPUT_DIR", tmp_path / "out")
        validation = ValidationResult(passed=True, skipped=True, skip_reason="x")

        long_md = (
            "# Name\n\n"
            "## Projects\n\n"
            "### Alpha\n\n- Alpha bullet one.\n- Alpha bullet two.\n\n"
            "### Beta\n\n- Beta bullet one.\n- Beta bullet two.\n"
        )

        # Simulate 2 pages on first check, 1 page after first trim
        page_counts = iter([2, 1])
        with patch(
            "job_processor.tailor_resume",
            return_value=(long_md, validation),
        ), patch(
            "job_processor.get_page_count", side_effect=page_counts
        ), patch("job_processor.generate_resume_pdf"):
            md_path, _ = process_application(
                job_description="jd", company="Acme", role="Eng", resume_path=resume
            )

        result = md_path.read_text()
        # One of the second bullets should have been removed
        assert result.count("- ") < long_md.count("- ")


# ---------------------------------------------------------------------------
# _trim_one_bullet unit tests
# ---------------------------------------------------------------------------

_TWO_BULLET_PROJECTS = (
    "# Name\n\n"
    "## Projects\n\n"
    "### Alpha\n\n- Alpha bullet one.\n- Alpha bullet two.\n\n"
    "### Beta\n\n- Beta bullet one.\n- Beta bullet two.\n"
)

_ONE_BULLET_PROJECTS = (
    "# Name\n\n"
    "## Projects\n\n"
    "### Alpha\n\n- Alpha bullet.\n\n"
    "### Beta\n\n- Beta bullet.\n"
)


class TestTrimOneBullet:
    def test_removes_last_bullet_from_last_multi_bullet_project(self):
        result = _trim_one_bullet(_TWO_BULLET_PROJECTS)
        assert result is not None
        assert "Beta bullet two." not in result
        assert "Beta bullet one." in result

    def test_no_change_to_projects_with_one_bullet_each(self):
        """Falls through to remove entire last project entry."""
        result = _trim_one_bullet(_ONE_BULLET_PROJECTS)
        assert result is not None
        # Beta project should be removed entirely
        assert "### Beta" not in result
        assert "### Alpha" in result

    def test_returns_none_when_nothing_to_trim(self):
        md = "# Name\n\n## Education\n\n**UBC** | MDS | 2025-2026\n"
        result = _trim_one_bullet(md)
        assert result is None

    def test_prefers_project_bullets_over_experience_bullets(self):
        md = (
            "# Name\n\n"
            "## Experience\n\n"
            "### Corp\n\n- E1.\n- E2.\n- E3.\n- E4.\n\n"
            "## Projects\n\n"
            "### Proj\n\n- P1.\n- P2.\n"
        )
        result = _trim_one_bullet(md)
        assert result is not None
        # Project bullet should be dropped, not experience
        assert "P2." not in result
        assert "E4." in result

    def test_experience_bullet_dropped_when_four_or_more(self):
        md = (
            "# Name\n\n"
            "## Experience\n\n"
            "### Corp\n\n- E1.\n- E2.\n- E3.\n- E4.\n"
        )
        result = _trim_one_bullet(md)
        assert result is not None
        assert "E4." not in result
        assert "E3." in result

    def test_experience_bullet_kept_when_fewer_than_four(self):
        md = (
            "# Name\n\n"
            "## Experience\n\n"
            "### Corp\n\n- E1.\n- E2.\n- E3.\n"
        )
        result = _trim_one_bullet(md)
        # No projects section and experience has < 4 bullets → nothing to trim
        assert result is None
