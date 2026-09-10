"""
Unit tests for main.py — job description input and the CLI flag matrix.
"""
import io
from pathlib import Path
from unittest.mock import MagicMock, patch

import main
import pyperclip
import pytest

from job_processor import ApplicationResult

# ---------------------------------------------------------------------------
# Job description input
# ---------------------------------------------------------------------------

def test_clipboard_job_description_returns_nonempty_text(monkeypatch):
    monkeypatch.setattr(pyperclip, "paste", lambda: "A job description")

    assert main._clipboard_job_description() == "A job description"


def test_clipboard_job_description_handles_unavailable_clipboard(monkeypatch):
    def unavailable():
        raise pyperclip.PyperclipException("clipboard unavailable")

    monkeypatch.setattr(pyperclip, "paste", unavailable)

    assert main._clipboard_job_description() is None


def test_read_job_description_uses_confirmed_clipboard(monkeypatch):
    monkeypatch.setattr(
        main, "_clipboard_job_description", lambda: "Clipboard description"
    )
    monkeypatch.setattr(
        main, "_confirm_clipboard_job_description", lambda description: True
    )

    assert main._read_job_description() == "Clipboard description"


def test_read_job_description_falls_back_to_terminal_paste(monkeypatch):
    monkeypatch.setattr(
        main, "_clipboard_job_description", lambda: "Clipboard description"
    )
    monkeypatch.setattr(
        main, "_confirm_clipboard_job_description", lambda description: False
    )
    monkeypatch.setattr(main.sys, "stdin", io.StringIO("Pasted description"))

    assert main._read_job_description() == "Pasted description"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

@pytest.fixture
def jd_file(tmp_path) -> Path:
    path = tmp_path / "jd.txt"
    path.write_text("Looking for a Python dev.")
    return path


def _run(argv: list[str]) -> None:
    with patch.object(main.sys, "argv", ["main.py", *argv]):
        main.main()


def _result(tmp_path: Path) -> ApplicationResult:
    md_path = tmp_path / "out.md"
    md_path.write_text("# Tailored\n")
    return ApplicationResult(md_path=md_path, pdf_path=tmp_path / "out.pdf")


class TestCLI:
    def test_runs_the_full_pipeline_by_default(self, tmp_path, jd_file):
        with patch(
            "main.process_application", return_value=_result(tmp_path)
        ) as mock_process:
            _run(["-c", "Stripe", "-r", "Data Scientist", "-j", str(jd_file)])
        kwargs = mock_process.call_args.kwargs
        assert kwargs["company"] == "Stripe"
        assert kwargs["role"] == "Data Scientist"
        assert kwargs["job_description"] == "Looking for a Python dev."
        assert kwargs["audit"] is True
        assert kwargs["factcheck"] is True
        assert kwargs["export_pdf"] is True

    @pytest.mark.parametrize("flag, disabled_kwarg", [
        ("--no-audit", "audit"),
        ("--no-factcheck", "factcheck"),
        ("--no-pdf", "export_pdf"),
    ])
    def test_stage_flags_disable_their_stage(
        self, tmp_path, jd_file, flag, disabled_kwarg
    ):
        with patch(
            "main.process_application", return_value=_result(tmp_path)
        ) as mock_process:
            _run(["-c", "Acme", "-r", "Eng", "-j", str(jd_file), flag])
        assert mock_process.call_args.kwargs[disabled_kwarg] is False

    def test_audit_only_stops_after_stage_one(self, tmp_path, jd_file):
        audit_path = tmp_path / "audit.md"
        with patch(
            "main.run_audit", return_value=(MagicMock(), audit_path)
        ) as mock_audit, patch("main.process_application") as mock_process:
            _run(["-c", "Acme", "-r", "Eng", "-j", str(jd_file), "--audit-only"])
        mock_audit.assert_called_once()
        mock_process.assert_not_called()

    def test_audit_only_exits_nonzero_when_the_audit_fails(self, jd_file):
        with patch("main.run_audit", return_value=(MagicMock(), None)):
            with pytest.raises(SystemExit) as exc:
                _run(["-c", "Acme", "-r", "Eng", "-j", str(jd_file), "--audit-only"])
        assert exc.value.code == 1

    def test_audit_only_conflicts_with_no_audit(self, jd_file):
        with pytest.raises(SystemExit) as exc:
            _run([
                "-c", "Acme", "-r", "Eng", "-j", str(jd_file),
                "--audit-only", "--no-audit",
            ])
        assert exc.value.code == 2

    def test_missing_jd_file_exits(self, tmp_path, capsys):
        with pytest.raises(SystemExit) as exc:
            _run(["-c", "Acme", "-r", "Eng", "-j", str(tmp_path / "nope.txt")])
        assert exc.value.code == 1
        assert "JD file not found" in capsys.readouterr().err

    def test_empty_jd_exits(self, tmp_path, capsys):
        empty = tmp_path / "empty.txt"
        empty.write_text("   ")
        with pytest.raises(SystemExit) as exc:
            _run(["-c", "Acme", "-r", "Eng", "-j", str(empty)])
        assert exc.value.code == 1
        assert "job description is empty" in capsys.readouterr().err

    def test_missing_resume_exits(self, tmp_path, jd_file, capsys):
        with patch(
            "main.process_application",
            side_effect=FileNotFoundError("resume not found: x.md"),
        ):
            with pytest.raises(SystemExit) as exc:
                _run(["-c", "Acme", "-r", "Eng", "-j", str(jd_file)])
        assert exc.value.code == 1
        assert "resume not found" in capsys.readouterr().err

    def test_prompts_for_company_and_role_when_omitted(self, tmp_path, jd_file):
        answers = iter(["Stripe", "Data Scientist"])
        with patch(
            "main.process_application", return_value=_result(tmp_path)
        ) as mock_process, patch("builtins.input", lambda _: next(answers)):
            _run(["-j", str(jd_file)])
        assert mock_process.call_args.kwargs["company"] == "Stripe"
        assert mock_process.call_args.kwargs["role"] == "Data Scientist"

    def test_empty_company_is_rejected(self, jd_file):
        with patch("builtins.input", lambda _: ""):
            with pytest.raises(SystemExit) as exc:
                _run(["-j", str(jd_file)])
        assert exc.value.code == 2

    def test_piped_stdin_is_used_when_no_jd_flag(self, tmp_path):
        fake_stdin = MagicMock()
        fake_stdin.isatty.return_value = False
        fake_stdin.read.return_value = "Piped job description."
        with patch(
            "main.process_application", return_value=_result(tmp_path)
        ) as mock_process, patch.object(main.sys, "stdin", fake_stdin):
            _run(["-c", "Acme", "-r", "Eng"])
        assert (
            mock_process.call_args.kwargs["job_description"]
            == "Piped job description."
        )
