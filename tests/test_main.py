import io

import main
import pyperclip


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
