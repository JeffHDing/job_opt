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
from job_processor import process_application  # noqa: E402
from resume_diff import ValidationResult  # noqa: E402


def _make_resume(tmp_path: Path, content: str = "# Resume\n\n- bullet\n") -> Path:
    p = tmp_path / "resume.md"
    p.write_text(content)
    return p


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
        with patch(
            "job_processor.tailor_resume",
            return_value=("# Tailored\n", validation),
        ) as mock_tailor, \
             patch("job_processor.generate_resume_pdf"):
            process_application(job_description="jd", company="Acme", role="Eng")
        assert mock_tailor.call_args[0][0] == "# Default Resume\n- bullet\n"

    def test_writes_md_and_pdf_to_output_dir(self, tmp_path, monkeypatch):
        resume = _make_resume(tmp_path)
        monkeypatch.setattr(job_processor, "_OUTPUT_DIR", tmp_path / "out")
        validation = ValidationResult(passed=True, skipped=False)
        with patch(
            "job_processor.tailor_resume",
            return_value=("# Tailored\n- bullet\n", validation),
        ), patch("job_processor.generate_resume_pdf") as mock_pdf:
            md_path, pdf_path = process_application(
                job_description="jd",
                company="Acme",
                role="Engineer",
                resume_path=resume,
            )
        assert md_path.exists()
        assert md_path.read_text() == "# Tailored\n- bullet\n"
        assert md_path.suffix == ".md"
        assert pdf_path.suffix == ".pdf"
        mock_pdf.assert_called_once_with("# Tailored\n- bullet\n", str(pdf_path))

    def test_output_filename_includes_company_and_role(self, tmp_path, monkeypatch):
        resume = _make_resume(tmp_path)
        monkeypatch.setattr(job_processor, "_OUTPUT_DIR", tmp_path / "out")
        validation = ValidationResult(passed=True, skipped=False)
        with patch(
            "job_processor.tailor_resume", return_value=("# Out\n", validation)
        ), patch("job_processor.generate_resume_pdf"):
            md_path, pdf_path = process_application(
                job_description="jd",
                company="Stripe",
                role="Data_Scientist",
                resume_path=resume,
            )
        assert "Stripe_Data_Scientist" in md_path.name
        assert "Stripe_Data_Scientist" in pdf_path.name
        assert md_path.stem == pdf_path.stem

    def test_validate_flag_passed_through(self, tmp_path, monkeypatch):
        resume = _make_resume(tmp_path)
        monkeypatch.setattr(job_processor, "_OUTPUT_DIR", tmp_path / "out")
        validation = ValidationResult(passed=True, skipped=True, skip_reason="x")
        with patch(
            "job_processor.tailor_resume", return_value=("# Out\n", validation)
        ) as mock_tailor, patch("job_processor.generate_resume_pdf"):
            process_application(
                job_description="jd",
                company="Acme",
                role="Eng",
                resume_path=resume,
                validate=False,
            )
        assert mock_tailor.call_args.kwargs["validate"] is False

    def test_applies_revert_when_judge_flags_violations(self, tmp_path, monkeypatch):
        resume = _make_resume(tmp_path)
        monkeypatch.setattr(job_processor, "_OUTPUT_DIR", tmp_path / "out")
        violations = [{"original": "good bullet", "tailored": "bad bullet"}]
        validation = ValidationResult(passed=False, violations=violations)
        with patch(
            "job_processor.tailor_resume",
            return_value=("## S\n- bad bullet\n", validation),
        ), patch("job_processor.generate_resume_pdf") as mock_pdf, \
             patch("builtins.input", return_value="y"):
            md_path, _ = process_application(
                job_description="jd",
                company="Acme",
                role="Eng",
                resume_path=resume,
            )
        assert "good bullet" in md_path.read_text()
        mock_pdf.assert_called_once()
        assert "good bullet" in mock_pdf.call_args[0][0]

    def test_keeps_tailored_text_when_revert_declined(self, tmp_path, monkeypatch):
        resume = _make_resume(tmp_path)
        monkeypatch.setattr(job_processor, "_OUTPUT_DIR", tmp_path / "out")
        violations = [{"original": "good bullet", "tailored": "bad bullet"}]
        validation = ValidationResult(passed=False, violations=violations)
        with patch(
            "job_processor.tailor_resume",
            return_value=("## S\n- bad bullet\n", validation),
        ), patch("job_processor.generate_resume_pdf"), \
             patch("builtins.input", return_value="n"):
            md_path, _ = process_application(
                job_description="jd",
                company="Acme",
                role="Eng",
                resume_path=resume,
            )
        assert "bad bullet" in md_path.read_text()

    def test_creates_output_dir_if_missing(self, tmp_path, monkeypatch):
        resume = _make_resume(tmp_path)
        nested_out = tmp_path / "nested" / "out"
        monkeypatch.setattr(job_processor, "_OUTPUT_DIR", nested_out)
        validation = ValidationResult(passed=True, skipped=False)
        with patch(
            "job_processor.tailor_resume", return_value=("# Out\n", validation)
        ), patch("job_processor.generate_resume_pdf"):
            process_application(
                job_description="jd", company="Acme", role="Eng", resume_path=resume
            )
        assert nested_out.exists()
