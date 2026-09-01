"""
Unit tests for job_processor.py.

All external side effects (Gemini calls, PDF rendering, interactive revert
prompt) are mocked so these run fast and offline.
"""
import sys
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import job_processor  # noqa: E402
from audit import AuditReport  # noqa: E402
from job_processor import (  # noqa: E402
    _slug,
    _trim_one_bullet,
    process_application,
    run_audit,
)
from resume_diff import ValidationResult  # noqa: E402


def _make_resume(tmp_path: Path, content: str = "# Resume\n\n- bullet\n") -> Path:
    p = tmp_path / "resume.md"
    p.write_text(content)
    return p


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_PASSED = ValidationResult(passed=True, reviewed=0)


class _Pipeline(ExitStack):
    """
    Patch every external call process_application makes, exposing each mock as
    an attribute so tests can assert on the stage they care about.
    """

    def __init__(
        self,
        tailored: str = "# Tailored\n",
        audit: AuditReport | None = None,
        validation: ValidationResult = _PASSED,
        pages: int | list[int] = 1,
    ):
        super().__init__()
        self._audit = audit if audit is not None else AuditReport(markdown="# Audit")
        self._tailored = tailored
        self._validation = validation
        self._pages = pages

    def __enter__(self) -> "_Pipeline":
        super().__enter__()
        page_kwargs = (
            {"side_effect": iter(self._pages)}
            if isinstance(self._pages, list)
            else {"return_value": self._pages}
        )
        self.audit = self.enter_context(
            patch("job_processor.audit_resume", return_value=self._audit)
        )
        self.tailor = self.enter_context(
            patch("job_processor.tailor_resume", return_value=self._tailored)
        )
        self.fact_check = self.enter_context(
            patch("job_processor.fact_check", return_value=self._validation)
        )
        self.page_count = self.enter_context(
            patch("job_processor.get_page_count", **page_kwargs)
        )
        self.pdf = self.enter_context(patch("job_processor.generate_resume_pdf"))
        return self


@pytest.fixture(autouse=True)
def _isolated_dirs(tmp_path, monkeypatch):
    """Keep every test's writes inside tmp_path, never in the real data/ dir."""
    monkeypatch.setattr(job_processor, "_OUTPUT_DIR", tmp_path / "out")
    monkeypatch.setattr(job_processor, "_AUDIT_DIR", tmp_path / "audits")


# ---------------------------------------------------------------------------
# _slug
# ---------------------------------------------------------------------------

class TestSlug:
    @pytest.mark.parametrize("raw, expected", [
        ("Data Scientist", "Data_Scientist"),
        ("Data_Scientist", "Data_Scientist"),
        ("Sr. Data Scientist (II)", "Sr_Data_Scientist_II"),
        ("  spaced  out  ", "spaced_out"),
        ("///", "Untitled"),
    ])
    def test_produces_filename_safe_text(self, raw, expected):
        assert _slug(raw) == expected


# ---------------------------------------------------------------------------
# run_audit
# ---------------------------------------------------------------------------

class TestRunAudit:
    def test_writes_report_and_returns_path(self, tmp_path):
        resume = _make_resume(tmp_path)
        report = AuditReport(markdown="# ATS Audit\n", current_score=61)
        with patch("job_processor.audit_resume", return_value=report):
            returned, path = run_audit("jd", "Stripe", "Data Scientist", resume)
        assert returned is report
        assert path.read_text() == "# ATS Audit\n"
        assert path.name.endswith("_Stripe_Data_Scientist_ats_audit.md")

    def test_skipped_audit_writes_nothing(self, tmp_path):
        resume = _make_resume(tmp_path)
        report = AuditReport(markdown="", skipped=True, skip_reason="503")
        with patch("job_processor.audit_resume", return_value=report):
            _, path = run_audit("jd", "Acme", "Eng", resume)
        assert path is None
        assert not (tmp_path / "audits").exists()


# ---------------------------------------------------------------------------
# process_application
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
        with _Pipeline() as p:
            process_application(job_description="jd", company="Acme", role="Eng")
        assert p.tailor.call_args[0][0] == "# Default Resume\n- bullet\n"

    def test_runs_all_three_stages_in_order(self, tmp_path):
        resume = _make_resume(tmp_path)
        with _Pipeline() as p:
            result = process_application(
                job_description="jd", company="Acme", role="Eng", resume_path=resume
            )
        p.audit.assert_called_once()
        p.tailor.assert_called_once()
        p.fact_check.assert_called_once()
        assert result.audit_path is not None

    def test_audit_report_is_handed_to_the_tailor(self, tmp_path):
        resume = _make_resume(tmp_path)
        report = AuditReport(markdown="# Audit", directives=["Do the thing."])
        with _Pipeline(audit=report) as p:
            process_application(
                job_description="jd", company="Acme", role="Eng", resume_path=resume
            )
        assert p.tailor.call_args.kwargs["audit"] is report

    def test_fact_check_receives_master_and_tailored(self, tmp_path):
        resume = _make_resume(tmp_path, "# Master\n\n- original bullet\n")
        with _Pipeline(tailored="# Tailored\n\n- edited bullet\n") as p:
            process_application(
                job_description="jd", company="Acme", role="Eng", resume_path=resume
            )
        master_arg, tailored_arg, _ = p.fact_check.call_args[0]
        assert master_arg == "# Master\n\n- original bullet\n"
        assert tailored_arg == "# Tailored\n\n- edited bullet\n"

    def test_no_audit_skips_stage_one(self, tmp_path):
        resume = _make_resume(tmp_path)
        with _Pipeline() as p:
            result = process_application(
                job_description="jd", company="Acme", role="Eng",
                resume_path=resume, audit=False,
            )
        p.audit.assert_not_called()
        assert p.tailor.call_args.kwargs["audit"] is None
        assert result.audit_path is None

    def test_no_factcheck_skips_stage_three(self, tmp_path):
        resume = _make_resume(tmp_path)
        with _Pipeline() as p:
            process_application(
                job_description="jd", company="Acme", role="Eng",
                resume_path=resume, factcheck=False,
            )
        p.fact_check.assert_not_called()

    def test_writes_output_files(self, tmp_path):
        resume = _make_resume(tmp_path)
        with _Pipeline(tailored="# Tailored\n- bullet\n") as p:
            result = process_application(
                job_description="jd",
                company="Stripe",
                role="Data Scientist",
                resume_path=resume,
            )
        assert result.md_path.read_text() == "# Tailored\n- bullet\n"
        assert result.md_path.suffix == ".md"
        assert result.pdf_path.suffix == ".pdf"
        assert result.md_path.stem == "Jeffrey_Ding_CV_Data_Scientist"
        assert result.md_path.stem == result.pdf_path.stem
        p.pdf.assert_called_once_with(
            "# Tailored\n- bullet\n", str(result.pdf_path)
        )

    def test_no_pdf_writes_markdown_only(self, tmp_path):
        resume = _make_resume(tmp_path)
        with _Pipeline() as p:
            result = process_application(
                job_description="jd", company="Acme", role="Eng",
                resume_path=resume, export_pdf=False,
            )
        p.pdf.assert_not_called()
        assert result.pdf_path is None
        assert result.md_path.exists()

    def test_header_role_is_stamped_from_the_job_title(self, tmp_path):
        resume = _make_resume(tmp_path)
        tailored = "# Jane Doe\n\n**Data Analyst** | jane@example.com\n"
        with _Pipeline(tailored=tailored):
            result = process_application(
                job_description="jd", company="Acme", role="ML Engineer",
                resume_path=resume,
            )
        assert "**ML Engineer** |" in result.md_path.read_text()

    def test_dropped_skills_are_restored_before_export(self, tmp_path):
        master = "## Technical Skills\n\n- **Languages:** Python, R, SAS\n"
        resume = _make_resume(tmp_path, master)
        tailored = "## Technical Skills\n\n- **Languages:** Python\n"
        with _Pipeline(tailored=tailored):
            result = process_application(
                job_description="jd", company="Acme", role="Eng", resume_path=resume
            )
        assert "**Languages:** Python, R, SAS" in result.md_path.read_text()

    def test_warns_about_leftover_placeholders(self, tmp_path, capsys):
        resume = _make_resume(tmp_path)
        with _Pipeline(tailored="## S\n- Cut latency by [X]%.\n"):
            process_application(
                job_description="jd", company="Acme", role="Eng", resume_path=resume
            )
        assert "Unfilled placeholders" in capsys.readouterr().out

    @pytest.mark.parametrize("user_input, expected_bullet, reverted", [
        ("y", "good bullet", True),
        ("n", "bad bullet",  False),
    ])
    def test_revert_decision_flows_to_output(
        self, tmp_path, user_input, expected_bullet, reverted
    ):
        resume = _make_resume(tmp_path)
        violations = [{"original": "good bullet", "tailored": "bad bullet"}]
        validation = ValidationResult(
            passed=False, violations=violations, reviewed=1
        )
        with _Pipeline(
            tailored="## S\n- bad bullet\n", validation=validation
        ) as p, patch("builtins.input", return_value=user_input):
            result = process_application(
                job_description="jd",
                company="Acme",
                role="Eng",
                resume_path=resume,
            )
        assert expected_bullet in result.md_path.read_text()
        if reverted:
            assert "good bullet" in p.pdf.call_args[0][0]

    def test_duplicate_bullets_removed_before_export(self, tmp_path):
        resume = _make_resume(tmp_path)
        tailored = (
            "## Experience\n### Acme\n- repeated point\n- other point\n"
            "- repeated point\n"
        )
        with _Pipeline(tailored=tailored) as p:
            result = process_application(
                job_description="jd", company="Acme", role="Eng", resume_path=resume
            )
        written = result.md_path.read_text()
        assert written.count("- repeated point") == 1
        assert "- other point" in written
        assert p.pdf.call_args[0][0].count("- repeated point") == 1

    def test_creates_output_dir_if_missing(self, tmp_path, monkeypatch):
        resume = _make_resume(tmp_path)
        nested_out = tmp_path / "nested" / "out"
        monkeypatch.setattr(job_processor, "_OUTPUT_DIR", nested_out)
        with _Pipeline():
            process_application(
                job_description="jd", company="Acme", role="Eng", resume_path=resume
            )
        assert nested_out.exists()

    def test_trim_loop_runs_when_overflow_detected(self, tmp_path):
        """If get_page_count reports > 1 page, bullets should be trimmed."""
        resume = _make_resume(tmp_path)
        long_md = (
            "# Name\n\n"
            "## Projects\n\n"
            "### Alpha\n\n- Alpha bullet one.\n- Alpha bullet two.\n\n"
            "### Beta\n\n- Beta bullet one.\n- Beta bullet two.\n"
        )
        # 2 pages on the first check, 1 page after the first trim
        with _Pipeline(tailored=long_md, pages=[2, 1]):
            result = process_application(
                job_description="jd", company="Acme", role="Eng", resume_path=resume
            )
        assert result.md_path.read_text().count("- ") < long_md.count("- ")


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

    def test_removed_project_leaves_a_blank_line_before_the_next_section(self):
        md = (
            "# Name\n\n"
            "## Projects\n\n"
            "### Alpha\n\n- Alpha bullet.\n\n"
            "### Beta\n\n- Beta bullet.\n\n"
            "## Certifications\n\n- A cert.\n"
        )
        result = _trim_one_bullet(md)
        assert "### Beta" not in result
        assert "- Alpha bullet.\n\n## Certifications" in result

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
