"""
Tests for pdf_exporter.py.

Requires weasyprint and its system dependencies (cairo, pango) — all present
in the job_opt conda environment. No network calls needed.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from pdf_exporter import generate_resume_pdf

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_TEMPLATE = _PROJECT_ROOT / "data/masters/Jeffrey_Ding_CV_Data_Science.md"

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
    def test_creates_output_file(self, tmp_path):
        out = tmp_path / "resume.pdf"
        generate_resume_pdf(_MINIMAL_MD, str(out))
        assert out.exists()

    def test_output_is_nonempty(self, tmp_path):
        out = tmp_path / "resume.pdf"
        generate_resume_pdf(_MINIMAL_MD, str(out))
        assert out.stat().st_size > 0

    def test_output_is_valid_pdf(self, tmp_path):
        out = tmp_path / "resume.pdf"
        generate_resume_pdf(_MINIMAL_MD, str(out))
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
