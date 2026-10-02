"""
Shared test bootstrap.

src/ modules import each other by bare name (e.g. `from resume_diff import ...`),
so src/ has to be on sys.path before any of them is imported. pytest loads
conftest.py ahead of the test modules, which makes this the one place that has
to know about it.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
