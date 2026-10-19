# Copilot instructions

## Commands

Run commands from the repository root with Python 3.12.

```text
# Install dependencies
python -m pip install -r requirements-dev.txt

# Lint (same check used by CI)
ruff check .

# Fast, offline test suite (same test selection used by CI)
python -m pytest -m "not integration" --cov --cov-report=term-missing

# Full suite, including Gemini integration tests
python -m pytest

# Run one test file
python -m pytest tests/test_resume_diff.py

# Run one test class or test
python -m pytest tests/test_job_processor.py::TestProcessApplication
python -m pytest tests/test_main.py::test_clipboard_job_description_returns_nonempty_text
```

Integration tests in `tests/test_llm_client.py` make real Gemini calls and
require `GEMINI_API_KEY`; they consume API quota. Use the offline selection for
normal development and CI-safe validation. `weasyprint` also needs its Cairo
and Pango system dependencies when installing outside the Conda environment;
`environment.yml` provides the recommended Python 3.12 Conda setup.

## Architecture

- `main.py` is the only CLI entry point. It resolves company, role, job
  description, and resume arguments, then calls `run_audit()` or
  `process_application()`.
- `src/job_processor.py` owns the end-to-end workflow:
  1. audit the master resume,
  2. tailor it using the audit directives,
  3. fact-check changes against the master,
  4. apply deterministic cleanup and page trimming,
  5. write Markdown and optionally render a PDF.
- `src/llm_client.py` is the Gemini boundary. It loads the three system
  prompts, caches one client, retries only 503/429 failures with exponential
  backoff, and treats audit/fact-check failures as skipped advisory stages.
  Tailoring failures propagate because that stage must produce the resume.
- `src/audit.py` parses the auditor's constrained Markdown into `AuditReport`
  data and detects leftover `[X]`-style placeholders.
- `src/resume_diff.py` contains pure-Python resume parsing, change matching,
  skill integrity checks, duplicate removal, and interactive revert behavior.
  It distinguishes bullet edits (matched within their section) from identity
  and other non-bullet lines (matched globally).
- `src/pdf_exporter.py` converts Markdown to linear, ATS-friendly HTML/PDF
  using WeasyPrint and the fixed resume CSS. `job_processor.py` repeatedly
  renders in memory and trims least-important bullets until the requested page
  limit is met.
- `src/config.py` is the single source for project paths and defaults.
  Prompt files live in `prompts/`; the master resume is under
  `data/masters/`; generated audits and tailored outputs are written under
  `data/` and are ignored by Git.

## Repository-specific conventions

- The master resume is the sole factual source. The job description can
  motivate wording or prioritization but never supplies evidence for a claim.
  Preserve identity lines (name, contact details, role/project titles,
  employers, dates, degrees, certifications) verbatim.
- The auditor's section 4 is a mechanical work order. Its directives use only
  `MOVE`, `REORDER`, `REPLACE`, `DROP`, and `SURFACE`, and quoted source text
  must already exist in the master. Quantification placeholders from the audit
  are for the human and must not reach tailored output.
- Keep Markdown structure ATS-parseable: standard headings, plain `-` bullets,
  no tables/columns/images in resume output, and preserve sections/list format.
  Technical Skills rows are treated as a set: preserve every master skill in
  its original row and spelling, avoid duplicate aliases, and do not invent
  unsupported terms.
- Deterministic validation is intentionally applied in addition to model
  review. Before output, the pipeline stamps the requested role title, restores
  or normalizes Technical Skills membership, removes duplicate bullets, warns
  about placeholders, and enforces the PDF page budget.
- LLM prompt files are part of the behavior and are loaded at import time.
  Changes to `prompts/*.txt` should be tested through the corresponding
  `llm_client` behavior; mock Gemini calls in unit tests rather than requiring
  a key.
- Internal modules use bare imports such as `from resume_diff import ...`,
  rather than package-qualified imports. Run tools from the repository root;
  `main.py` and `tests/conftest.py` explicitly place `src/` on `sys.path`.
- Tests isolate filesystem writes with `tmp_path` and mock Gemini, PDF
  rendering, and interactive review for unit coverage. Keep generated outputs
  out of the real `data/` directories during tests.

## Git

- Do not create commits unless explicitly requested.
- Do not modify unrelated files or revert unrelated worktree changes.
- In the final handoff, summarize the files changed and validation performed.
