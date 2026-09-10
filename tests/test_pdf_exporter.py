"""
Tests for pdf_exporter.py.

Requires weasyprint and its system dependencies (cairo, pango) — all present
in the job_opt conda environment. No network calls needed.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from pdf_exporter import _RESUME_CSS, _build_html, generate_resume_pdf

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_TEMPLATE = _PROJECT_ROOT / "data/masters/Jeffrey_Ding_CV.md"

_MINIMAL_MD = """\
# Jane Smith

**Software Engineer**

## Experience

### Acme Corp

*Engineer* | 2020 - 2023

- Built things with Python.
- Shipped features on time.

## Skills

- Python, SQL, Git
"""


class TestGenerateResumePdf:
    def test_creates_valid_pdf(self, tmp_path):
        out = tmp_path / "resume.pdf"
        generate_resume_pdf(_MINIMAL_MD, str(out))
        assert out.exists()
        assert out.read_bytes().startswith(b"%PDF-")

    def test_creates_parent_dirs(self, tmp_path):
        out = tmp_path / "subdir" / "nested" / "resume.pdf"
        out.parent.mkdir(parents=True)
        generate_resume_pdf(_MINIMAL_MD, str(out))
        assert out.exists()

    def test_renders_template_resume(self, tmp_path):
        if not _TEMPLATE.exists():
            pytest.skip(f"Template not found: {_TEMPLATE}")
        out = tmp_path / "jeffrey.pdf"
        generate_resume_pdf(_TEMPLATE.read_text(), str(out))
        assert out.read_bytes().startswith(b"%PDF-")

    def test_empty_markdown_does_not_raise(self, tmp_path):
        out = tmp_path / "empty.pdf"
        generate_resume_pdf("", str(out))
        assert out.exists()

    def test_markdown_with_links(self, tmp_path):
        md = "# Name\n\n[Email](mailto:a@b.com) | [GitHub](https://github.com/user)\n"
        out = tmp_path / "links.pdf"
        generate_resume_pdf(md, str(out))
        assert out.read_bytes().startswith(b"%PDF-")


class TestResumeCss:
    def test_body_is_times_new_roman_at_12pt(self):
        assert "Times New Roman" in _RESUME_CSS
        assert "font-size: 12pt;" in _RESUME_CSS
        assert "Arial" not in _RESUME_CSS
        assert "Helvetica" not in _RESUME_CSS

    def test_section_headers_match_academic_cv(self):
        assert "text-transform: uppercase;" in _RESUME_CSS
        assert "letter-spacing: 0.12em;" in _RESUME_CSS


class TestBuildHtml:
    def test_right_aligns_experience_dates_and_locations(self):
        md = (
            "### Data Manager\n\n"
            "_Sunnybrook Research Institute_ | Toronto, ON | Feb 2022 - Feb 2024\n"
        )
        html = _build_html(md)
        assert 'class="entry-header"' in html
        assert 'class="dates"' in html
        assert "Feb 2022 - Feb 2024" in html
        assert 'class="loc"' in html
        assert "Toronto, ON" in html
        assert 'class="entry-sub has-loc"' in html
        assert "Sunnybrook Research Institute" in html

    def test_keeps_education_gpa_on_the_left(self):
        md = (
            "### Master of Data Science\n\n"
            "_University of British Columbia_ | Vancouver, BC | "
            "GPA: 3.7/4.0 | Sep 2025 - Jun 2026\n"
        )
        html = _build_html(md)
        assert "Sep 2025 - Jun 2026" in html
        assert 'class="dates"' in html
        assert 'class="entry-sub has-loc"' not in html
        assert "GPA: 3.7/4.0" in html

    def test_skills_list_has_no_bullets(self):
        md = (
            "## Technical Skills\n\n"
            "- **Languages:** Python, R\n"
        )
        html = _build_html(md)
        assert '<ul class="skills">' in html

    def test_leaves_projects_without_dates_alone(self):
        md = "### Resume Optimizer\n\n- Built a tailor.\n"
        html = _build_html(md)
        assert 'class="entry-header"' not in html
        assert "<h3>Resume Optimizer</h3>" in html
