# Job Optimizer

[![CI](https://github.com/JeffHDing/job_opt/actions/workflows/ci.yml/badge.svg)](https://github.com/JeffHDing/job_opt/actions/workflows/ci.yml)
[![codecov](https://codecov.io/gh/JeffHDing/job_opt/branch/main/graph/badge.svg)](https://codecov.io/gh/JeffHDing/job_opt)

A CLI that tailors a master Markdown resume to a job description in three stages: an **ATS audit** that scores the resume and issues mechanical tailoring directives, a **tailor** pass that executes those directives, and a **fact-check** pass that catches anything the tailor claimed beyond what the master supports. The result is trimmed to one page and exported as an ATS-friendly PDF.

The premise is that a tailoring model left to its own devices will quietly invent things to hit keywords. So the model is never trusted twice: what the auditor asks for, the tailor must justify against the master, and what the tailor produces, the fact-checker re-derives from the master before it reaches the page.

---

## The three stages

### 1. Audit — `prompts/auditor_system.txt`

Scores the master resume against the job description exactly as an ATS would: literally, on the text present. A 100-point rubric covers hard skills (30), responsibility alignment (20), quantified impact (15), title match (10), depth and recency (10), hard qualifications (10), and parseability (5).

The report separates gaps that tailoring can close from gaps that need experience the candidate does not have, then states a projected score and whether 90%+ is honestly reachable. Its directives are restricted to a five-verb grammar — `MOVE`, `REORDER`, `REPLACE`, `DROP`, `SURFACE` — each of which must quote text that already appears in the master. There is deliberately no verb for "add a bullet" or "rename a role", because those cannot be expressed without fabricating.

Reports are saved to `data/audit_reports/YYYYMMDD_{Company}_{Role}_ats_audit.md`.

### 2. Tailor — `prompts/tailor_system.txt`

Receives the master resume, the job description, and the audit. It executes the audit's directives, skipping any it cannot carry out without a claim the master does not support. Its other rules cover structure preservation, an untouchable identity block (name, contact line, role titles, employers, dates), Technical Skills fidelity, keyword substitution over keyword appending, and hard one-page limits.

It is explicitly forbidden from emitting the auditor's `[X]%` placeholders, which are meant for the human to fill into the master.

### 3. Fact-check — `prompts/factcheck_system.txt`

Diffs the tailored resume against the master and sends only what changed for review, with the full master as the sole ground truth. The job description is given as motive, never as evidence.

Where a claim must be supported depends on the claim: work claims must be supported by the master's text for *that specific role or project* (a tool in the Skills section is not evidence it was used at a particular job), Skills claims must be supported anywhere in the master, and identity content must match verbatim. Each flagged edit comes back with a severity of `minor` (overstated scope) or `major` (would mislead an interviewer), and you review them one at a time.

---

## Guardrails

Model judgement handles the parts that need reading comprehension. Everything mechanically checkable is checked in Python, so it holds even when the model is wrong or the API call fails.

| Guardrail | How | Where |
|---|---|---|
| Identity content is verbatim | Non-bullet lines — headings, employers, dates, contact details — are diffed against the master and flagged if they appear nowhere in it | `resume_diff.find_changed_lines` |
| No invented skills | Every term added to a Technical Skills row must appear in the master as a whole word; violations are raised at `major` severity even when the model approved the edit | `resume_diff.find_unsupported_skills` |
| No dropped or duplicated skills | Each Skills row is normalised to hold exactly the terms the master files under it: dropped terms are appended back, terms the master files elsewhere are removed, and repeats are collapsed. Row membership is the master's, ordering is the tailor's | `resume_diff.normalize_skill_rows` |
| No leftover placeholders | The tailored output is scanned for `[X]`-style brackets, ignoring Markdown links | `audit.find_placeholders` |
| No duplicate bullets | Repeats within a section are stripped | `resume_diff.dedupe_bullets` |
| Job title matches the posting | Stamped into the header after the fact-check, so a tailor edit to that line is still caught | `job_processor._set_header_role` |
| One page | The PDF is rendered in memory and bullets are trimmed until it fits, least-important first | `job_processor._ensure_one_page` |

Stages 1 and 3 degrade rather than fail: a transient API error marks them skipped and the run continues, so a network blip never costs you the tailored resume. Stage 2 raises, because there is no output without it. Every call retries on 503 and 429 with exponential backoff.

---

## Repository structure

```
job_opt/
├── main.py                          # The single CLI entry point
├── src/
│   ├── job_processor.py             # Pipeline orchestration + post-processing
│   ├── llm_client.py                # The three Gemini agents
│   ├── audit.py                     # Audit report parsing (scores, directives)
│   ├── resume_diff.py               # Bullet/line parsing, diffing, revert, integrity checks
│   └── pdf_exporter.py              # Markdown → WeasyPrint PDF + page-count helper
├── prompts/
│   ├── auditor_system.txt           # Stage 1: ATS scoring + tailoring directives
│   ├── tailor_system.txt            # Stage 2: directive-driven rewriting
│   └── factcheck_system.txt         # Stage 3: hallucination detection
├── data/
│   ├── masters/                     # Master resumes (source of truth)
│   ├── job_descriptions/            # Job description text files
│   ├── audit_reports/               # Generated ATS audits (gitignored)
│   └── tailored_outputs/            # Generated .md/.pdf (gitignored)
├── tests/
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

Get a free key at [aistudio.google.com](https://aistudio.google.com/). The free tier allows ~500 requests/day. A full run costs 3 requests, one per stage, giving ~165 applications/day; `--no-audit` or `--no-factcheck` drops that to 2.

---

## Usage

The simplest workflow is clipboard-based:

1. Copy the full job description from the job board.
2. Run `python main.py`.
3. Enter the company and role title when prompted.
4. Press Enter to accept the clipboard preview.

```text
Company: Stripe
Role title: Data Scientist

Job description found in clipboard:
  "About the role..."

Use this job description? [Y/n]:
```

Type `n` to reject the clipboard and paste into the terminal instead, finishing with Ctrl-D (Ctrl-Z on Windows). Job-description input priority is `--jd`, then piped stdin, then the clipboard.

A run looks like this:

```text
Stage 1/3 — auditing master resume against the job description...
   Current ATS score:   63/100
   Projected after tailoring: 78/100
   ✗  90%+ NOT reachable without new experience — see 'Unclosable without new experience' in the report.
   4 tailoring directive(s) issued.
   Audit report → data/audit_reports/20260831_Stripe_Data_Scientist_ats_audit.md

Stage 2/3 — tailoring resume against 4 audit directive(s)...

Stage 3/3 — fact-checking against the master resume...

--- Fact-Check Report ---

✗  Fact-check failed — 2 unsupported edit(s) out of 5 reviewed (1 major):
   ...
```

Each flagged edit is then shown individually with `[y]es / [n]o / [a]ll / [q]uit reviewing`, where `a` reverts everything remaining and `q` keeps it.

### Scoring without tailoring

`--audit-only` runs stage 1 and stops. Use it to see where a resume stands before spending calls on tailoring, or to collect the audit's Quantification Requests — the bullets that need real numbers — and fold them into your master resume.

```bash
python main.py -c Stripe -r "Data Scientist" \
               -j data/job_descriptions/stripe_ds.txt --audit-only
```

### Other examples

```bash
# Read the job description from a file
python main.py -c Stripe -r "Data Scientist" -j data/job_descriptions/stripe_ds.txt

# Pipe a job description through stdin
pbpaste | python main.py -c Stripe -r "Data Scientist"

# Use a different master resume
python main.py -c Stripe -r "Data Scientist" --resume data/masters/my_other.md

# Iterate quickly: skip the audit and the PDF export
python main.py -c Stripe -r "Data Scientist" --no-audit --no-pdf
```

### All options

| Flag | Short | Default | Description |
|---|---|---|---|
| `--company` | `-c` | prompt | Company name, used in the audit report filename |
| `--role` | `-r` | prompt | Job title; also stamped into the resume header |
| `--jd` | `-j` | clipboard | Job description file; piped stdin also works |
| `--resume` | | `data/masters/Jeffrey_Ding_CV.md` | Master resume Markdown |
| `--audit-only` | | off | Run stage 1 and stop |
| `--no-audit` | | off | Skip stage 1; tailor without directives |
| `--no-factcheck` | | off | Skip stage 3 |
| `--no-pdf` | | off | Write Markdown only |

Outputs land in `data/tailored_outputs/Jeffrey_Ding_CV_{Role}.md` and `.pdf`.

---

## Testing

```bash
# Unit tests only (no API key, CI-safe)
pytest -m "not integration"

# Integration tests — 3 real Gemini calls, one per stage
pytest tests/test_llm_client.py -m integration -s

# Everything
pytest
```

| Mark | File | Needs API key? | Speed |
|---|---|---|---|
| *(none)* | `test_resume_diff.py` | No | Fast |
| *(none)* | `test_audit.py` | No | Fast |
| *(none)* | `test_job_processor.py` | No | Fast |
| *(none)* | `test_llm_client_unit.py` | No | Fast |
| *(none)* | `test_main.py` | No | Fast |
| *(none)* | `test_pdf_exporter.py` | No | Fast |
| `integration` | `test_llm_client.py` | Yes (`GEMINI_API_KEY`) | Slow, costs API quota |

The integration tests assert on prompt behaviour, not just plumbing: that the audit's scores parse and its projection beats its current score, that the tailor preserves every section and leaks neither placeholders nor the audit report into the resume, and that the fact-check returns a usable verdict.

CI runs `ruff check .` and `pytest -m "not integration" --cov` on every push and PR to `main`.

---

## Notes and limitations

- All three agents use `gemini-3.1-flash-lite`. The auditor does the most reasoning and benefits most from a stronger model; change `_AUDITOR_MODEL` in `src/llm_client.py` if you have the quota.
- A 90%+ score is often genuinely unreachable, and the audit says so rather than fabricating its way there. When it reports `Reachable: No`, the fix is in the master resume — usually real metrics from the Quantification Requests section — not in the tailoring.
- `normalize_skill_rows` only operates on Skills rows the tailor kept. A row deleted outright is left alone, since there is no reliable place to reinsert it.
- Job scraping (LinkedIn/Indeed) is not implemented.
