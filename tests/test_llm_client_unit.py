"""
Unit tests for llm_client.py – no network calls required.

All Gemini API interactions are mocked so these run in CI without a key.
"""
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest
from google.genai.errors import ClientError, ServerError

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import llm_client  # noqa: E402
from llm_client import (  # noqa: E402
    _cli_main,
    _get_client,
    _validate_changes,
    _with_retry,
    review_resume,
    tailor_resume,
)
from resume_diff import BulletChange, ValidationResult  # noqa: E402

_PROJECT_ROOT = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _server_err(code: int) -> ServerError:
    """Build a ServerError with a .code attribute without touching the API."""
    err = ServerError.__new__(ServerError)
    err.code = code
    return err


def _client_err(code: int) -> ClientError:
    err = ClientError.__new__(ClientError)
    err.code = code
    return err


def _fake_response(text: str) -> MagicMock:
    r = MagicMock()
    r.text = text
    return r


# ---------------------------------------------------------------------------
# _get_client
# ---------------------------------------------------------------------------

class TestGetClient:
    def setup_method(self):
        llm_client._client = None

    def teardown_method(self):
        llm_client._client = None

    def test_raises_when_api_key_missing(self, monkeypatch):
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        with pytest.raises(EnvironmentError, match="GEMINI_API_KEY"):
            _get_client()

    def test_creates_client_with_api_key(self, monkeypatch):
        monkeypatch.setenv("GEMINI_API_KEY", "test-key")
        mock_client = MagicMock()
        with patch("llm_client.genai.Client", return_value=mock_client) as MockClient:
            result = _get_client()
        MockClient.assert_called_once_with(api_key="test-key")
        assert result is mock_client

    def test_returns_cached_singleton(self, monkeypatch):
        monkeypatch.setenv("GEMINI_API_KEY", "test-key")
        mock_client = MagicMock()
        with patch("llm_client.genai.Client", return_value=mock_client) as MockClient:
            first = _get_client()
            second = _get_client()
        MockClient.assert_called_once()
        assert first is second


# ---------------------------------------------------------------------------
# _with_retry
# ---------------------------------------------------------------------------

class TestWithRetry:
    def test_returns_immediately_on_success(self):
        fn = MagicMock(return_value="ok")
        assert _with_retry(fn) == "ok"
        fn.assert_called_once()

    def test_retries_and_succeeds_on_503(self):
        fn = MagicMock(side_effect=[_server_err(503), "ok"])
        with patch("llm_client.time.sleep") as mock_sleep:
            result = _with_retry(fn)
        assert result == "ok"
        assert fn.call_count == 2
        mock_sleep.assert_called_once_with(5.0)

    def test_retries_and_succeeds_on_429(self):
        fn = MagicMock(side_effect=[_client_err(429), "ok"])
        with patch("llm_client.time.sleep") as mock_sleep:
            result = _with_retry(fn)
        assert result == "ok"
        assert fn.call_count == 2
        mock_sleep.assert_called_once_with(5.0)

    def test_raises_immediately_on_non_retryable_server_error(self):
        fn = MagicMock(side_effect=_server_err(500))
        with patch("llm_client.time.sleep"):
            with pytest.raises(ServerError):
                _with_retry(fn)
        fn.assert_called_once()

    def test_raises_immediately_on_non_retryable_client_error(self):
        fn = MagicMock(side_effect=_client_err(400))
        with patch("llm_client.time.sleep"):
            with pytest.raises(ClientError):
                _with_retry(fn)
        fn.assert_called_once()

    def test_raises_after_max_retries_503(self):
        fn = MagicMock(side_effect=_server_err(503))
        with patch("llm_client.time.sleep") as mock_sleep:
            with pytest.raises(ServerError):
                _with_retry(fn)
        assert fn.call_count == llm_client._RETRY_ATTEMPTS
        assert mock_sleep.call_args_list == [call(5.0), call(10.0)]

    def test_delay_doubles_between_retries(self):
        fn = MagicMock(side_effect=_client_err(429))
        delays = []
        with patch("llm_client.time.sleep", side_effect=lambda d: delays.append(d)):
            with pytest.raises(ClientError):
                _with_retry(fn)
        assert delays == [5.0, 10.0]


# ---------------------------------------------------------------------------
# _validate_changes (judge call)
# ---------------------------------------------------------------------------

class TestValidateChanges:
    def _mock_client(self, response_text: str) -> MagicMock:
        client = MagicMock()
        client.models.generate_content.return_value = _fake_response(response_text)
        return client

    def test_no_changes_returns_passed_without_api_call(self):
        client = MagicMock()
        result = _validate_changes([], "some jd", client)
        assert result.passed is True
        client.models.generate_content.assert_not_called()

    def test_all_supported_returns_passed(self):
        verdicts = [
            {"supported": True, "bullet": "b1"},
            {"supported": True, "bullet": "b2"},
        ]
        client = self._mock_client(json.dumps(verdicts))
        changes = [BulletChange(section="Exp", original="old", tailored="new")]
        result = _validate_changes(changes, "jd text", client)
        assert result.passed is True
        assert result.violations == []

    def test_violation_returns_failed(self):
        verdicts = [{"supported": False, "bullet": "fabricated"}]
        client = self._mock_client(json.dumps(verdicts))
        changes = [BulletChange(section="Exp", original="old", tailored="fabricated")]
        result = _validate_changes(changes, "jd text", client)
        assert result.passed is False
        assert len(result.violations) == 1

    def test_json_decode_error_skips(self):
        client = self._mock_client("not valid json {{")
        changes = [BulletChange(section="Exp", original="old", tailored="new")]
        result = _validate_changes(changes, "jd", client)
        assert result.passed is True
        assert result.skipped is True
        assert "JSONDecodeError" in result.skip_reason

    def test_generic_exception_skips(self):
        client = MagicMock()
        client.models.generate_content.side_effect = RuntimeError("network blip")
        changes = [BulletChange(section="Exp", original="old", tailored="new")]
        result = _validate_changes(changes, "jd", client)
        assert result.passed is True
        assert result.skipped is True
        assert "RuntimeError" in result.skip_reason


# ---------------------------------------------------------------------------
# tailor_resume
# ---------------------------------------------------------------------------

class TestTailorResume:
    def _mock_tailor_response(self, text: str) -> MagicMock:
        client = MagicMock()
        client.models.generate_content.return_value = _fake_response(text)
        return client

    def test_validate_false_skips_judge(self):
        client = self._mock_tailor_response("# Tailored\n\n- bullet")
        with patch("llm_client._get_client", return_value=client), \
             patch("llm_client._validate_changes") as mock_judge:
            tailored, result = tailor_resume(
                "# Master\n\n- bullet", "jd", validate=False
            )
        mock_judge.assert_not_called()
        assert result.skipped is True
        assert result.skip_reason == "validate=False"
        assert "Tailored" in tailored

    def test_validate_true_no_changes(self):
        master = "# Resume\n\n## Exp\n- Same bullet\n"
        client = self._mock_tailor_response(master)
        with patch("llm_client._get_client", return_value=client), \
             patch("llm_client._validate_changes") as mock_judge:
            tailor_resume(master, "jd", validate=True)
        mock_judge.assert_called_once()
        changes_passed = mock_judge.call_args[0][0]
        assert changes_passed == []

    def test_validate_true_with_changes(self):
        master = "# Resume\n\n## Exp\n- Old bullet\n"
        tailored_text = "# Resume\n\n## Exp\n- New bullet\n"
        client = self._mock_tailor_response(tailored_text)
        validation = ValidationResult(passed=True)
        with patch("llm_client._get_client", return_value=client), \
             patch(
                 "llm_client._validate_changes", return_value=validation
             ) as mock_judge:
            tailored, result = tailor_resume(master, "jd", validate=True)
        mock_judge.assert_called_once()
        assert result is validation
        assert "New bullet" in tailored

    def test_editor_feedback_included_in_user_message(self):
        client = self._mock_tailor_response("# Resume\n\n## Exp\n- bullet\n")
        passed = ValidationResult(passed=True)
        with patch("llm_client._get_client", return_value=client), \
             patch("llm_client._validate_changes", return_value=passed):
            tailor_resume(
                "# Resume\n\n## Exp\n- bullet\n",
                "jd",
                validate=True,
                editor_feedback="## 6. Top 5 Priorities\n1. Do X.",
            )
        sent_contents = client.models.generate_content.call_args.kwargs["contents"]
        assert "Recruiter Feedback" in sent_contents
        assert "Do X." in sent_contents

    def test_no_editor_feedback_omits_section(self):
        client = self._mock_tailor_response("# Resume\n\n## Exp\n- bullet\n")
        passed = ValidationResult(passed=True)
        with patch("llm_client._get_client", return_value=client), \
             patch("llm_client._validate_changes", return_value=passed):
            tailor_resume("# Resume\n\n## Exp\n- bullet\n", "jd", validate=True)
        sent_contents = client.models.generate_content.call_args.kwargs["contents"]
        assert "Recruiter Feedback" not in sent_contents

    def test_blank_editor_feedback_omits_section(self):
        client = self._mock_tailor_response("# Resume\n\n## Exp\n- bullet\n")
        passed = ValidationResult(passed=True)
        with patch("llm_client._get_client", return_value=client), \
             patch("llm_client._validate_changes", return_value=passed):
            tailor_resume(
                "# Resume\n\n## Exp\n- bullet\n",
                "jd",
                validate=True,
                editor_feedback="   ",
            )
        sent_contents = client.models.generate_content.call_args.kwargs["contents"]
        assert "Recruiter Feedback" not in sent_contents


# ---------------------------------------------------------------------------
# review_resume (editor call)
# ---------------------------------------------------------------------------

class TestReviewResume:
    def _mock_client(self, text: str) -> MagicMock:
        client = MagicMock()
        client.models.generate_content.return_value = _fake_response(text)
        return client

    def test_returns_stripped_model_text(self):
        client = self._mock_client("  ## 1. Match Analysis\n...  \n")
        with patch("llm_client._get_client", return_value=client):
            feedback = review_resume("# Resume\n- bullet", "jd text")
        assert feedback == "## 1. Match Analysis\n..."

    def test_uses_editor_model_and_system_prompt(self):
        client = self._mock_client("feedback")
        with patch("llm_client._get_client", return_value=client):
            review_resume("# Resume", "jd")
        _, kwargs = client.models.generate_content.call_args
        assert kwargs["model"] == llm_client._EDITOR_MODEL
        assert kwargs["config"].system_instruction == llm_client._EDITOR_SYSTEM_PROMPT

    def test_user_message_includes_resume_and_jd(self):
        client = self._mock_client("feedback")
        with patch("llm_client._get_client", return_value=client):
            review_resume("# My Resume", "Looking for a Pythonista")
        sent_contents = client.models.generate_content.call_args.kwargs["contents"]
        assert "My Resume" in sent_contents
        assert "Looking for a Pythonista" in sent_contents
        assert "## Master Resume" in sent_contents
        assert "## Job Description" in sent_contents


# ---------------------------------------------------------------------------
# _cli_main
# ---------------------------------------------------------------------------

class TestCLIMain:
    """Tests for the _cli_main() function (CLI entry point)."""

    def _make_resume(
        self, tmp_path: Path, content: str = "# Resume\n\n- bullet\n"
    ) -> Path:
        p = tmp_path / "resume.md"
        p.write_text(content)
        return p

    def _make_jd(
        self, tmp_path: Path, content: str = "Looking for a Python dev."
    ) -> Path:
        p = tmp_path / "jd.txt"
        p.write_text(content)
        return p

    def test_resume_not_found_exits(self, tmp_path, capsys):
        with pytest.raises(SystemExit) as exc:
            _cli_main([
                "--resume", str(tmp_path / "missing.md"),
                "--jd", str(tmp_path / "x.txt"),
            ])
        assert exc.value.code == 1
        assert "resume not found" in capsys.readouterr().err

    def test_jd_file_not_found_exits(self, tmp_path, capsys):
        resume = self._make_resume(tmp_path)
        with pytest.raises(SystemExit) as exc:
            _cli_main(["--resume", str(resume), "--jd", str(tmp_path / "missing.txt")])
        assert exc.value.code == 1
        assert "JD file not found" in capsys.readouterr().err

    def test_empty_jd_exits(self, tmp_path, capsys):
        resume = self._make_resume(tmp_path)
        jd = self._make_jd(tmp_path, content="   ")
        with pytest.raises(SystemExit) as exc:
            _cli_main(["--resume", str(resume), "--jd", str(jd)])
        assert exc.value.code == 1
        assert "job description is empty" in capsys.readouterr().err

    def test_successful_run_writes_out_file(self, tmp_path):
        resume = self._make_resume(tmp_path)
        jd = self._make_jd(tmp_path)
        out = tmp_path / "output.md"
        validation = ValidationResult(passed=True, skipped=False)
        validation.summary = MagicMock(return_value="All good.")
        with patch(
            "llm_client.tailor_resume", return_value=("# Tailored\n", validation)
        ):
            _cli_main(["--resume", str(resume), "--jd", str(jd), "--out", str(out)])
        assert out.exists()
        assert "Tailored" in out.read_text()

    def test_successful_run_prints_to_stdout(self, tmp_path, capsys):
        resume = self._make_resume(tmp_path)
        jd = self._make_jd(tmp_path)
        validation = ValidationResult(passed=True, skipped=False)
        validation.summary = MagicMock(return_value="All good.")
        with patch(
            "llm_client.tailor_resume", return_value=("# Tailored\n", validation)
        ):
            _cli_main(["--resume", str(resume), "--jd", str(jd)])
        out = capsys.readouterr().out
        assert "Tailored Resume" in out
        assert "# Tailored" in out

    def test_no_validate_flag(self, tmp_path):
        resume = self._make_resume(tmp_path)
        jd = self._make_jd(tmp_path)
        validation = ValidationResult(
            passed=True, skipped=True, skip_reason="validate=False"
        )
        validation.summary = MagicMock(return_value="Skipped.")
        with patch(
            "llm_client.tailor_resume", return_value=("# Out\n", validation)
        ) as mock_tr:
            _cli_main(["--resume", str(resume), "--jd", str(jd), "--no-validate"])
        # validate is always passed as a keyword arg by the CLI
        assert mock_tr.call_args.kwargs["validate"] is False

    def test_violations_user_reverts(self, tmp_path, capsys):
        resume = self._make_resume(tmp_path)
        jd = self._make_jd(tmp_path)
        violation = {"bullet": "fabricated", "reason": "hallucinated"}
        validation = ValidationResult(passed=False, violations=[violation])
        validation.summary = MagicMock(return_value="FAILED")
        with patch("llm_client.tailor_resume", return_value=("# Out\n", validation)), \
             patch(
                 "llm_client.revert_violations", return_value="# Reverted\n"
             ) as mock_rv, \
             patch("builtins.input", return_value="y"):
            _cli_main(["--resume", str(resume), "--jd", str(jd)])
        mock_rv.assert_called_once()
        assert "Reverted" in capsys.readouterr().out

    def test_violations_user_declines_revert(self, tmp_path):
        resume = self._make_resume(tmp_path)
        jd = self._make_jd(tmp_path)
        violation = {"bullet": "fabricated", "reason": "hallucinated"}
        validation = ValidationResult(passed=False, violations=[violation])
        validation.summary = MagicMock(return_value="FAILED")
        with patch("llm_client.tailor_resume", return_value=("# Out\n", validation)), \
             patch("llm_client.revert_violations") as mock_rv, \
             patch("builtins.input", return_value="n"):
            _cli_main(["--resume", str(resume), "--jd", str(jd)])
        mock_rv.assert_not_called()

    def test_violations_eof_on_input(self, tmp_path):
        resume = self._make_resume(tmp_path)
        jd = self._make_jd(tmp_path)
        violation = {"bullet": "fabricated"}
        validation = ValidationResult(passed=False, violations=[violation])
        validation.summary = MagicMock(return_value="FAILED")
        with patch("llm_client.tailor_resume", return_value=("# Out\n", validation)), \
             patch("llm_client.revert_violations") as mock_rv, \
             patch("builtins.input", side_effect=EOFError):
            _cli_main(["--resume", str(resume), "--jd", str(jd)])
        mock_rv.assert_not_called()

    def test_stdin_jd_tty(self, tmp_path, capsys):
        """When no --jd flag and stdin is a tty, it prints a prompt."""
        resume = self._make_resume(tmp_path)
        validation = ValidationResult(passed=True, skipped=False)
        validation.summary = MagicMock(return_value="OK")
        fake_stdin = MagicMock()
        fake_stdin.isatty.return_value = True
        fake_stdin.read.return_value = "A job description."
        with patch("llm_client.tailor_resume", return_value=("# Out\n", validation)), \
             patch("sys.stdin", fake_stdin):
            _cli_main(["--resume", str(resume)])
        out = capsys.readouterr().out
        assert "Paste job description" in out

    def test_stdin_jd_non_tty(self, tmp_path, capsys):
        """When no --jd flag and stdin is piped, no prompt is printed."""
        resume = self._make_resume(tmp_path)
        validation = ValidationResult(passed=True, skipped=False)
        validation.summary = MagicMock(return_value="OK")
        fake_stdin = MagicMock()
        fake_stdin.isatty.return_value = False
        fake_stdin.read.return_value = "A job description."
        with patch("llm_client.tailor_resume", return_value=("# Out\n", validation)), \
             patch("sys.stdin", fake_stdin):
            _cli_main(["--resume", str(resume)])
        out = capsys.readouterr().out
        assert "Paste job description" not in out

    def test_review_flag_prints_feedback_and_skips_tailor(self, tmp_path, capsys):
        resume = self._make_resume(tmp_path)
        jd = self._make_jd(tmp_path)
        with patch(
            "llm_client.review_resume", return_value="## 1. Match Analysis\n..."
        ) as mock_review, \
             patch("llm_client.tailor_resume") as mock_tailor:
            _cli_main(["--resume", str(resume), "--jd", str(jd), "--review"])
        mock_review.assert_called_once()
        mock_tailor.assert_not_called()
        out = capsys.readouterr().out
        assert "Editor Feedback" in out
        assert "Match Analysis" in out

    def test_review_flag_writes_to_out_file(self, tmp_path):
        resume = self._make_resume(tmp_path)
        jd = self._make_jd(tmp_path)
        out_file = tmp_path / "feedback.md"
        with patch("llm_client.review_resume", return_value="feedback text"), \
             patch("llm_client.tailor_resume") as mock_tailor:
            _cli_main([
                "--resume", str(resume), "--jd", str(jd),
                "--review", "--out", str(out_file),
            ])
        mock_tailor.assert_not_called()
        assert out_file.read_text() == "feedback text"

    def test_with_review_feeds_feedback_into_tailor(self, tmp_path):
        resume = self._make_resume(tmp_path)
        jd = self._make_jd(tmp_path)
        validation = ValidationResult(passed=True, skipped=False)
        validation.summary = MagicMock(return_value="OK")
        with patch(
            "llm_client.review_resume", return_value="## 6. Top 5 Priorities\n1. Fix X."
        ) as mock_review, \
             patch(
                 "llm_client.tailor_resume", return_value=("# Out\n", validation)
             ) as mock_tailor:
            _cli_main(["--resume", str(resume), "--jd", str(jd), "--with-review"])
        mock_review.assert_called_once()
        mock_tailor.assert_called_once()
        assert mock_tailor.call_args.kwargs["editor_feedback"] == (
            "## 6. Top 5 Priorities\n1. Fix X."
        )

    def test_review_and_with_review_mutually_exclusive(self, tmp_path, capsys):
        resume = self._make_resume(tmp_path)
        jd = self._make_jd(tmp_path)
        with pytest.raises(SystemExit):
            _cli_main([
                "--resume", str(resume), "--jd", str(jd),
                "--review", "--with-review",
            ])

    def test_no_review_flags_passes_none_as_editor_feedback(self, tmp_path):
        resume = self._make_resume(tmp_path)
        jd = self._make_jd(tmp_path)
        validation = ValidationResult(passed=True, skipped=False)
        validation.summary = MagicMock(return_value="OK")
        with patch("llm_client.review_resume") as mock_review, \
             patch(
                 "llm_client.tailor_resume", return_value=("# Out\n", validation)
             ) as mock_tailor:
            _cli_main(["--resume", str(resume), "--jd", str(jd)])
        mock_review.assert_not_called()
        assert mock_tailor.call_args.kwargs["editor_feedback"] is None
