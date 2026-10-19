"""Optional draft-only cover-letter and interview-prep stages."""
from __future__ import annotations

from llm_client import generate_cover_letter, generate_interview_prep


def create_optional_package(
    master_resume: str,
    job_description: str,
    tailored_resume: str,
    *,
    cover_letter: bool = False,
    interview_prep: bool = False,
) -> dict[str, str]:
    artifacts: dict[str, str] = {}
    if cover_letter:
        artifacts["cover_letter"] = generate_cover_letter(
            master_resume, job_description, tailored_resume
        )
    if interview_prep:
        artifacts["interview_prep"] = generate_interview_prep(
            master_resume, job_description, tailored_resume
        )
    return artifacts
