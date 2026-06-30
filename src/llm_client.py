import os
from pathlib import Path

from dotenv import load_dotenv
from google import genai
from google.genai import types

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_PROJECT_ROOT / ".env")

# ---------------------------------------------------------------------------
# Model config
# ---------------------------------------------------------------------------
_MODEL = "gemini-2.5-flash"

_SYSTEM_PROMPT = """\
You are an expert resume writer and ATS optimisation specialist.

Your job is to tailor a master resume (in Markdown) to a specific job description
while following these rules:

1. **Preserve structure exactly** — keep the same Markdown headings, sections,
   and list format as the input resume. Do not add, remove, or rename sections.
2. **Reorder and reweight bullet points** — move the most relevant bullets to the
   top within each section. Cut bullets only when they are genuinely irrelevant
   and space is needed; never fabricate experience.
3. **Mirror keywords** — naturally incorporate high-signal keywords from the job
   description (skills, tools, methodologies) into existing bullets where truthful.
4. **Stay factual** — never invent metrics, titles, dates, or tools that are not
   already present in the master resume.
5. **Output only Markdown** — return the tailored resume as clean Markdown with
   no commentary, preamble, or code fences.
"""

# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------

def _get_client() -> genai.Client:
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise EnvironmentError(
            "GEMINI_API_KEY is not set. Copy .env.example to .env and add your key, "
            "or export it: export GEMINI_API_KEY='your-key'"
        )
    return genai.Client(api_key=api_key)


def tailor_resume(master_resume_md: str, job_description: str) -> str:
    """
    Sends the master resume + job description to Gemini and returns a
    tailored Markdown resume string.

    The two inputs are kept as separate user-turn parts so the model treats
    them as distinct context blocks rather than one fused string — this
    improves keyword-matching fidelity in practice.
    """
    client = _get_client()

    user_message = (
        "## Master Resume\n\n"
        f"{master_resume_md.strip()}\n\n"
        "## Job Description\n\n"
        f"{job_description.strip()}"
    )

    response = client.models.generate_content(
        model=_MODEL,
        config=types.GenerateContentConfig(
            system_instruction=_SYSTEM_PROMPT,
            temperature=0.3,      # low temp → consistent, conservative edits
            max_output_tokens=4096,
        ),
        contents=user_message,
    )

    return response.text.strip()


# ---------------------------------------------------------------------------
# Smoke test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys
    from pathlib import Path

    resume_path = Path("data/templates/Jeffrey_Ding_CV_Data_Science.md")
    if not resume_path.exists():
        print(f"Resume not found at {resume_path}", file=sys.stderr)
        sys.exit(1)

    sample_jd = """\
    We are looking for a Data Scientist with strong Python and SQL skills.
    Experience with machine learning pipelines, cloud platforms (AWS/GCP),
    and communicating insights to non-technical stakeholders is required.
    Familiarity with clinical or healthcare data is a plus.
    """

    print("Calling Gemini API...", flush=True)
    result = tailor_resume(resume_path.read_text(), sample_jd)
    print("\n--- Tailored Resume ---\n")
    print(result)
