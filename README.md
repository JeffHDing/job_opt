# Job Optimizer

[![CI](https://github.com/JeffHDing/job_opt/actions/workflows/ci.yml/badge.svg)](https://github.com/JeffHDing/job_opt/actions/workflows/ci.yml)
[![codecov](https://codecov.io/gh/JeffHDing/job_opt/branch/main/graph/badge.svg)](https://codecov.io/gh/JeffHDing/job_opt)

An LLM-powered CLI tool that tailors a master Markdown resume to a specific job description using the Gemini API, runs a second judge pass to flag unsupported edits, auto-trims to one page if needed, and exports the result as an ATS-friendly PDF.

---

## Repository Structure

```
job_opt/
├── main.py                          # Top-level CLI entry point: tailor + validate + PDF
├── src/
│   ├── job_processor.py             # Pipeline orchestrator: tailor → validate → PDF
│   ├── llm_client.py                # Gemini API calls (tailor/judge/editor) + standalone CLI
│   ├── resume_diff.py               # Pure-Python bullet parser, differ, revert utils
│   └── pdf_exporter.py              # Markdown → WeasyPrint PDF renderer + page-count helper
├── prompts/
│   ├── tailor_system.txt            # System prompt for the tailor pass
│   ├── judge_system.txt             # System prompt for the judge pass
│   └── editor_system.txt            # System prompt for the standalone editor/review pass
├── data/
│   ├── masters/                     # Master resumes (source of truth)
│   ├── job_descriptions/            # Job description text files
│   ├── tailored_outputs/            # Generated .md/.pdf land here (gitignored)
│   └── review_feedback/             # Generated editor feedback reports (gitignored)
├── tests/
│   ├── test_resume_diff.py          # Unit tests for bullet diff/revert/report logic
│   ├── test_job_processor.py        # Unit tests for the pipeline orchestrator (mocked)
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

When the judge flags unsupported edits, the CLI walks you through each flagged bullet and asks whether to revert it before writing the files.

### All options

| Flag | Short | Default | Description |
|---|---|---|---|
| `--company` | `-c` | *(required)* | Company name (e.g. `Stripe`) |
| `--role` | `-r` | *(required)* | Job title, underscores for spaces (e.g. `Data_Scientist`) |
| `--jd` | `-j` | stdin | Path to job description text file |
| `--resume` | | `data/masters/Jeffrey_Ding_CV_Data_Science.md` | Master resume Markdown file |
| `--no-validate` | | off | Skip the judge validation step |

### Getting recruiter-style feedback (editor agent)

`llm_client.py` also exposes a standalone CLI for the "editor" agent — a
senior-recruiter persona that critiques your master resume against a job
description and writes a blunt, structured Markdown feedback report (match
analysis, quantification gaps, keyword gaps, STAR rewrites, ATS tips, and a
ranked top-5 priority list). It's independent of the `main.py` tailor/PDF
pipeline — nothing currently feeds this feedback back into tailoring.

```bash
python src/llm_client.py --review --resume data/masters/my_resume.md \
                          --jd data/job_descriptions/stripe_ds.txt
```

Saves to `data/review_feedback/YYYYMMDD_HHMMSS_review_feedback.md` unless
`--out FILE` is given. `llm_client.py` can also be run without `--review` to
tailor a resume without exporting a PDF (useful for quick iteration); see
`python src/llm_client.py --help` for its full flag set.

---

## How It Works

1. **Tailor** — `llm_client.tailor_resume()` sends the master resume + job description to `gemini-3.1-flash-lite` with the system prompt in `prompts/tailor_system.txt`. The prompt enforces 8 rules: preserve structure, preserve all Technical Skills entries (adding only skills explicitly present in Experience/Projects), reorder bullets by relevance, substitute keywords only when directly supported by the original text, stay factual, avoid redundancy, output clean Markdown, and respect hard one-page limits (≤3 experience roles × ≤4 bullets, ≤5 projects × ≤2 bullets, ≤20 total bullets across both sections).
2. **Diff** — `resume_diff.find_changed_bullets()` compares the tailored output against the master and extracts only the changed bullets (original + tailored pairs).
3. **Validate** — A second Gemini call (prompt in `prompts/judge_system.txt`) reviews the changed bullets and the job description, flagging any edits that add unsupported claims.
4. **Report + revert** — `resume_diff.report_and_maybe_revert()` prints the validation summary and, if violations were found, prompts bullet-by-bullet to revert each flagged edit to its original. This is shared by both `job_processor.py` and `llm_client.py`'s standalone CLI.
5. **Auto-trim** — `job_processor._ensure_one_page()` calls `pdf_exporter.get_page_count()` to render the Markdown in-memory and check the page count. If it overflows, `_trim_one_bullet()` removes one bullet at a time (last project bullet → last experience bullet → entire last project entry) until the output fits on one page, up to 8 trim passes.
6. **Export** — `pdf_exporter.generate_resume_pdf()` converts the final Markdown to a Letter PDF via WeasyPrint (no floats, no images — purely linear for ATS parsing).

Separately, `llm_client.review_resume()` (prompt in `prompts/editor_system.txt`) runs a senior-recruiter "editor" pass over the master resume and job description, producing a standalone feedback report — see [Getting recruiter-style feedback](#getting-recruiter-style-feedback-editor-agent) above. It does not currently feed into the tailor/validate/export pipeline.

Every Gemini call retries automatically on 503 (overload) and 429 (rate-limit) with exponential backoff.

The auto-trim loop in step 5 is a safety net — the tailor prompt's hard bullet-count limits (rule 8) should prevent overflow in most cases. Trimming kicks in when the rendered layout still overflows despite the LLM respecting the counts, e.g. due to long bullet text.

---

## Testing

Pytest markers are defined in `pyproject.toml`:

| Mark | File | Needs API key? | Speed |
|---|---|---|---|
| *(none)* | `test_resume_diff.py` | No | Fast |
| *(none)* | `test_job_processor.py` | No | Fast |
| *(none)* | `test_llm_client_unit.py` | No | Fast |
| *(none)* | `test_pdf_exporter.py` | No | Fast |
| `integration` | `test_llm_client.py` | Yes (`GEMINI_API_KEY`) | Slow (~24 s, costs API quota) |

```bash
# Unit tests only (no API key, CI-safe)
pytest -m "not integration"

# Individual modules
pytest tests/test_resume_diff.py
pytest tests/test_job_processor.py
pytest tests/test_llm_client_unit.py
pytest tests/test_pdf_exporter.py

# Integration tests (real Gemini API calls)
pytest tests/test_llm_client.py -m integration -s

# Everything
pytest
```

CI runs `ruff check .` and `pytest -m "not integration" --cov` on every push/PR to `main`. Coverage tracks all of `src/` — no modules are excluded.

---

## Current State

| Component | Status |
|---|---|
| `resume_diff.py` | Complete — bullet parser, differ, revert, interactive report; fully unit-tested including EOF and invalid-input edge cases |
| `pdf_exporter.py` | Complete — renders ATS-friendly PDF + `get_page_count()` in-memory helper; unit-tested |
| `llm_client.py` | Complete — tailor + judge + editor(review) + retry logic; unit- and integration-tested |
| `job_processor.py` | Complete — full pipeline orchestrator with auto-trim-to-one-page loop; unit-tested |
| `main.py` | Complete — CLI entry point wired to full pipeline |
| `prompts/tailor_system.txt` | Complete — 8 rules: structure preservation, Technical Skills fidelity, bullet reordering, keyword substitution, factuality, no redundancy, Markdown-only output, explicit one-page hard limits |
| `prompts/judge_system.txt` | Complete — validates changed bullets against job description |
| `prompts/editor_system.txt` | Complete — senior-recruiter feedback report |
| Editor feedback → tailor pipeline integration | Not implemented — `review_resume()` output is a standalone report only |
| Job scraping (LinkedIn/Indeed) | Not yet implemented |
