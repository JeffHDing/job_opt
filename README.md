# Job Optimizer

[![CI](https://github.com/JeffHDing/job_opt/actions/workflows/ci.yml/badge.svg)](https://github.com/JeffHDing/job_opt/actions/workflows/ci.yml)
[![codecov](https://codecov.io/gh/JeffHDing/job_opt/branch/main/graph/badge.svg)](https://codecov.io/gh/JeffHDing/job_opt)

An LLM-powered CLI tool that tailors a master Markdown resume to a specific job description using the Gemini API, runs a second judge pass to flag unsupported edits, and exports the result as a one-page ATS-friendly PDF.

---

## Repository Structure

```
job_opt/
├── main.py                          # Top-level CLI entry point (stub)
├── src/
│   ├── llm_client.py                # Gemini API calls: tailor + judge validation
│   ├── resume_diff.py               # Pure-Python bullet parser, differ, revert utils
│   └── pdf_exporter.py              # Markdown → WeasyPrint PDF renderer
├── prompts/
│   ├── tailor_system.txt            # System prompt for the tailor pass
│   └── judge_system.txt             # System prompt for the judge pass
├── data/
│   ├── templates/
│   │   └── Jeffrey_Ding_CV_Data_Science.md   # Master resume (source of truth)
│   └── tailored_outputs/            # Generated PDFs land here
├── tests/
│   ├── test_resume_diff.py          # Unit tests for bullet diff/revert logic
│   ├── test_llm_client_unit.py      # Unit tests for llm_client (mocked API)
│   ├── test_llm_client.py           # Integration tests (requires GEMINI_API_KEY)
│   └── test_pdf_exporter.py         # PDF rendering tests
├── environment.yml                  # Conda environment spec
├── requirements-dev.txt             # Pip deps for CI / non-Conda setups
├── pyproject.toml                   # Ruff, pytest markers, coverage config
└── .env.example                     # API key template
```

---

## Setup

### Option A: Conda (recommended)

```bash
conda env create -f environment.yml
conda activate job_opt
```

### Option B: pip

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
```

WeasyPrint requires system libraries (Cairo, Pango). On macOS: `brew install cairo pango`. On Ubuntu: `apt install libcairo2 libpango-1.0-0`.

Dependencies: Python 3.12, `google-genai`, `markdown`, `weasyprint`, `python-dotenv`, `pytest`, `pytest-cov`, `ruff`.

### Configure your API key

```bash
cp .env.example .env
# Edit .env and set GEMINI_API_KEY=<your key>
```

Get a free key at [aistudio.google.com](https://aistudio.google.com/). The free tier supports ~500 requests/day; each tailoring run costs 2 requests (~250 applications/day).

---

## Usage

### Tailor a resume via the LLM client

```bash
# Read job description from a file
python src/llm_client.py --resume data/templates/Jeffrey_Ding_CV_Data_Science.md \
                         --jd /path/to/job_description.txt \
                         --out data/tailored_outputs/output.md

# Paste job description interactively (Ctrl-D to finish)
python src/llm_client.py --out data/tailored_outputs/output.md

# Skip the judge validation pass
python src/llm_client.py --jd jd.txt --no-validate
```

When the judge flags unsupported edits, the CLI prompts to revert flagged bullets to their originals.

### Export a Markdown resume to PDF

`pdf_exporter` is a library module (no standalone CLI). From the repo root:

```bash
PYTHONPATH=src python -c "
from pathlib import Path
from pdf_exporter import generate_resume_pdf
md = Path('data/templates/Jeffrey_Ding_CV_Data_Science.md').read_text()
generate_resume_pdf(md, 'data/tailored_outputs/output.pdf')
"
```

### Top-level CLI (orchestration stub)

```bash
python main.py --company Google --role Data_Scientist
# Then paste the job description and press Ctrl-D
```

> Note: `main.py` currently stubs out the processing step. The live pipeline runs through `src/llm_client.py` directly.

---

## How It Works

1. **Tailor** — `llm_client.tailor_resume()` sends the master resume + job description to `gemini-3.1-flash-lite` using the system prompt in `prompts/tailor_system.txt`: preserve structure, reorder bullets, substitute keywords only when directly supported by the original text.
2. **Validate** — `resume_diff.find_changed_bullets()` diffs the tailored output against the master, then a second Gemini judge call (prompt in `prompts/judge_system.txt`) reviews only the changed bullets and flags any that add unsupported claims.
3. **Revert** — If violations are found, the CLI prompts to revert flagged bullets to their originals via `resume_diff.revert_violations()`.
4. **Export** — `pdf_exporter.generate_resume_pdf()` converts the final Markdown to a single-page Letter PDF via WeasyPrint (no floats, no images — purely linear for ATS parsing).

Both Gemini calls retry automatically on 503 (overload) and 429 (rate-limit) with exponential backoff.

---

## Testing

Pytest markers are defined in `pyproject.toml`:

| Mark | File | Needs API key? | Speed |
|---|---|---|---|
| *(none)* | `test_resume_diff.py` | No | Fast |
| *(none)* | `test_llm_client_unit.py` | No | Fast |
| *(none)* | `test_pdf_exporter.py` | No | Fast |
| `integration` | `test_llm_client.py` | Yes (`GEMINI_API_KEY`) | Slow (~24 s, costs API quota) |

```bash
# Unit tests only (no API key, CI-safe)
pytest -m "not integration"

# Individual modules
pytest tests/test_resume_diff.py
pytest tests/test_llm_client_unit.py
pytest tests/test_pdf_exporter.py

# Integration tests only (real Gemini API calls)
pytest tests/test_llm_client.py -m integration -s

# Everything
pytest
```

CI runs `ruff check .` and `pytest -m "not integration" --cov` on every push/PR to `main`.

---

## Current State

| Component | Status |
|---|---|
| `resume_diff.py` | Complete — fully unit-tested |
| `pdf_exporter.py` | Complete — renders ATS-friendly PDF, unit-tested |
| `llm_client.py` | Complete — tailor + judge + retry logic, unit- and integration-tested |
| `prompts/` | Complete — tailor and judge system prompts externalized |
| `main.py` | Stub — CLI scaffolding present, pipeline not yet wired |
| Job scraping (LinkedIn/Indeed) | Not yet implemented |
