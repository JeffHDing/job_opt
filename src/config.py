"""
config.py — the project's filesystem layout and shared defaults.

Every path the pipeline reads or writes is named here once, so that moving the
data directory or renaming the master resume is a one-line change rather than a
search across the CLI, the orchestrator, the client, and the tests.
"""
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

PROMPTS_DIR = PROJECT_ROOT / "prompts"
DATA_DIR = PROJECT_ROOT / "data"
DEFAULT_RESUME = DATA_DIR / "masters" / "Jeffrey_Ding_CV.md"
OUTPUT_DIR = DATA_DIR / "tailored_outputs"
AUDIT_DIR = DATA_DIR / "audit_reports"

# Tailored outputs are named "<stem>_<Role>.md" / ".pdf".
OUTPUT_STEM = DEFAULT_RESUME.stem

# The page budget the tailor writes to and the PDF trimmer enforces.
DEFAULT_MAX_PAGES = 2


def display_path(path: Path) -> Path:
    """Shorten *path* for printing, relative to the project root where possible."""
    try:
        return path.relative_to(PROJECT_ROOT)
    except ValueError:
        return path
