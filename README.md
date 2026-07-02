# Job Optimizer

[![CI](https://github.com/JeffHDing/job_opt/actions/workflows/ci.yml/badge.svg)](https://github.com/JeffHDing/job_opt/actions/workflows/ci.yml)
[![codecov](https://codecov.io/gh/JeffHDing/job_opt/branch/main/graph/badge.svg)](https://codecov.io/gh/JeffHDing/job_opt)

An LLM-powered CLI tool that tailors a master Markdown resume to a specific job description using the Gemini API, runs a second judge pass to flag unsupported edits, and exports the result as a one-page ATS-friendly PDF.

---

## Repository Structure

```
job_opt/
├── main.py                          # Top-level CLI entry point
├── src/
│   ├── job_processor.py             # Pipeline orchestrator: tailor → validate → PDF
│   ├── llm_client.py                # Gemini API calls: tailor + judge validation
│   ├── resume_diff.py               # Pure-Python bullet parser, differ, revert utils
│   └── pdf_exporter.py              # Markdown → WeasyPrint PDF renderer
├── prompts/
│   ├── tailor_system.txt            # System prompt for the tailor pass
│   └── judge_system.txt             # System prompt for the judge pass
├── data/
│   ├── masters/                     # Master resumes (source of truth)
│   ├── job_descriptions/            # Job description text files
│   └── tailored_outputs/            # Generated .md and .pdf files land here
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

WeasyPrint requires system libraries. On macOS: `brew install cairo pango`. On Ubuntu: `apt install libcairo2 libpango-1.0-0`.

### Configure your API key

```bash
cp .env.example .env
# Edit .env and set GEMINI_API_KEY=<your key>
```

Get a free key at [aistudio.google.com](https://aistudio.google.com/). The free tier supports ~500 requests/day; each tailoring run costs 2 requests (1 tailor + 1 judge), giving ~250 runs/day.

---

## Usage

### Tailor a resume and export a PDF

```bash
python main.py --company <Name> --role <Title> --jd <file>
```

**Examples:**

```bash
# From a job description file
python main.py --company Stripe --role Data_Scientist \
               --jd data/job_descriptions/stripe_ds.txt

# Paste the job description interactively (Ctrl-D to finish)
python main.py --company Stripe --role Data_Scientist

# Use a different master resume
python main.py --company Stripe --role Data_Scientist \
               --jd data/job_descriptions/stripe_ds.txt \
               --resume data/masters/my_other_resume.md

# Skip the judge validation pass (faster, 1 API call)
python main.py --company Stripe --role Data_Scientist \
               --jd data/job_descriptions/stripe_ds.txt \
               --no-validate
```

Outputs are saved to `data/tailored_outputs/YYYYMMDD_{Company}_{Role}.md` and `.pdf`.

When the judge flags unsupported edits, the CLI prompts you to revert those bullets to their originals before writing the files.

### All options

| Flag | Short | Default | Description |
|---|---|---|---|
| `--company` | `-c` | *(required)* | Company name (e.g. `Stripe`) |
| `--role` | `-r` | *(required)* | Job title, underscores for spaces (e.g. `Data_Scientist`) |
| `--jd` | `-j` | stdin | Path to job description text file |
| `--resume` | | `data/masters/Jeffrey_Ding_CV_Data_Science.md` | Master resume Markdown file |
| `--no-validate` | | off | Skip the judge validation step |

---

## How It Works

1. **Tailor** — `llm_client.tailor_resume()` sends the master resume + job description to `gemini-3.1-flash-lite` with the system prompt in `prompts/tailor_system.txt`: preserve structure, reorder bullets, substitute keywords only when directly supported by the original text.
2. **Diff** — `resume_diff.find_changed_bullets()` compares the tailored output against the master and extracts only the changed bullets (original + tailored pairs).
3. **Validate** — A second Gemini call (prompt in `prompts/judge_system.txt`) reviews the changed bullets and the job description, flagging any edits that add unsupported claims.
4. **Revert** — If violations are found, the CLI prompts to revert flagged bullets to their originals via `resume_diff.revert_violations()`.
5. **Export** — `pdf_exporter.generate_resume_pdf()` converts the final Markdown to a single-page Letter PDF via WeasyPrint (no floats, no images — purely linear for ATS parsing).

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

# Integration tests (real Gemini API calls)
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
| `job_processor.py` | Complete — full pipeline orchestrator |
| `main.py` | Complete — CLI entry point wired to full pipeline |
| `prompts/` | Complete — tailor and judge system prompts externalized |
| Job scraping (LinkedIn/Indeed) | Not yet implemented |
