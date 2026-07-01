# Job Optimizer

An LLM-powered CLI tool that tailors a master Markdown resume to a specific job description using the Gemini API, runs a second judge pass to flag unsupported edits, and exports the result as a one-page ATS-friendly PDF.

---

## Repository Structure

```
job_opt/
├── main.py                          # Top-level CLI entry point
├── src/
│   ├── llm_client.py                # Gemini API calls: tailor + judge validation
│   ├── resume_diff.py               # Pure-Python bullet parser, differ, revert utils
│   └── pdf_exporter.py              # Markdown → WeasyPrint PDF renderer
├── data/
│   ├── templates/
│   │   └── Jeffrey_Ding_CV_Data_Science.md   # Master resume (source of truth)
│   └── tailored_outputs/            # Generated PDFs land here
├── tests/
│   ├── test_resume_diff.py          # Unit tests (no API key required)
│   └── test_llm_client.py           # Integration tests (requires GEMINI_API_KEY)
├── env.yml                          # Conda environment spec
└── .env.example                     # API key template
```

---

## Setup

### 1. Create the Conda environment

```bash
conda env create -f env.yml
conda activate job_opt
```

Dependencies: `python 3.12`, `google-genai`, `markdown`, `weasyprint`, `python-dotenv`, `pytest`.

### 2. Configure your API key

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

### Export a Markdown resume to PDF

```bash
python src/pdf_exporter.py   # renders the default template to data/tailored_outputs/test_outputs.pdf
```

### Top-level CLI (orchestration stub)

```bash
python main.py --company Google --role Data_Scientist
# Then paste the job description and press Ctrl-D
```

> Note: `main.py` currently stubs out the processing step. The live pipeline runs through `src/llm_client.py` directly.

---

## How It Works

1. **Tailor** — `llm_client.tailor_resume()` sends the master resume + job description to `gemini-3.1-flash-lite` with a strict system prompt: preserve structure, reorder bullets, substitute keywords only when directly supported by the original text.
2. **Validate** — `resume_diff.find_changed_bullets()` diffs the tailored output against the master, then a second Gemini judge call reviews only the changed bullets and flags any that add unsupported claims.
3. **Revert** — If violations are found, the CLI prompts to revert flagged bullets to their originals via `resume_diff.revert_violations()`.
4. **Export** — `pdf_exporter.generate_resume_pdf()` converts the final Markdown to a single-page Letter PDF via WeasyPrint (no floats, no images — purely linear for ATS parsing).

---

## Testing

```bash
# Unit tests only (no API key, runs instantly)
pytest tests/test_resume_diff.py

# Integration tests (real Gemini API calls — requires GEMINI_API_KEY)
pytest tests/test_llm_client.py -m integration

# All tests
pytest
```

---

## Current State

| Component | Status |
|---|---|
| `resume_diff.py` | Complete — fully unit-tested |
| `pdf_exporter.py` | Complete — renders ATS-friendly PDF |
| `llm_client.py` | Complete — tailor + judge + retry logic |
| `main.py` | Stub — CLI scaffolding present, pipeline not yet wired |
| `masters_manager.py` | Empty — planned module for managing multiple master resumes |
| Job scraping (LinkedIn/Indeed) | Not yet implemented |
