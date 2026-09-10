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
from audit import AuditReport  # noqa: E402
from llm_client import (  # noqa: E402
    _get_client,
    _tailor_page_budget,
    _tailor_system_prompt,
    _with_retry,
    audit_resume,
    fact_check,
    tailor_resume,
)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent

_MASTER = "# Resume\n\n## Experience\n\n### Acme\n\n- Built a pipeline in Python\n"


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


def _mock_client(text: str) -> MagicMock:
    client = MagicMock()
    client.models.generate_content.return_value = _fake_response(text)
    return client


def _patch_client(text: str) -> tuple[MagicMock, object]:
    client = _mock_client(text)
    return client, patch("llm_client._get_client", return_value=client)


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
# Stage 1 — audit_resume
# ---------------------------------------------------------------------------

_AUDIT_MD = (
    "## 1. ATS Score\n\n**Overall ATS score: 61/100**\n\n"
    "## 4. Tailoring Directives\n\n1. [Skills] Lead with SQL.\n\n"
    "## 6. Projected Score\n\n"
    "**Projected ATS score after tailoring: 92/100**\n\n**Reachable:** `Yes`\n"
)


class TestAuditResume:
    def test_returns_parsed_report(self):
        _, patcher = _patch_client(_AUDIT_MD)
        with patcher:
            report = audit_resume(_MASTER, "jd")
        assert report.current_score == 61
        assert report.projected_score == 92
        assert report.directives == ["[Skills] Lead with SQL."]
        assert report.skipped is False

    def test_uses_auditor_model_and_prompt(self):
        client, patcher = _patch_client(_AUDIT_MD)
        with patcher:
            audit_resume(_MASTER, "jd")
        kwargs = client.models.generate_content.call_args.kwargs
        assert kwargs["model"] == llm_client._AUDITOR_MODEL
        assert kwargs["config"].system_instruction == llm_client._AUDITOR_SYSTEM_PROMPT

    def test_user_message_includes_resume_and_jd(self):
        client, patcher = _patch_client(_AUDIT_MD)
        with patcher:
            audit_resume("# My Resume", "Looking for a Pythonista")
        contents = client.models.generate_content.call_args.kwargs["contents"]
        assert "## Master Resume" in contents
        assert "My Resume" in contents
        assert "## Job Description" in contents
        assert "Looking for a Pythonista" in contents

    def test_api_failure_returns_skipped_report_instead_of_raising(self):
        client = MagicMock()
        client.models.generate_content.side_effect = RuntimeError("network blip")
        with patch("llm_client._get_client", return_value=client):
            report = audit_resume(_MASTER, "jd")
        assert report.skipped is True
        assert "RuntimeError" in report.skip_reason


# ---------------------------------------------------------------------------
# Stage 2 — tailor_resume
# ---------------------------------------------------------------------------

class TestTailorResume:
    def test_returns_stripped_markdown(self):
        _, patcher = _patch_client("  # Tailored\n\n- bullet  \n")
        with patcher:
            assert tailor_resume(_MASTER, "jd") == "# Tailored\n\n- bullet"

    def test_uses_tailor_model_and_prompt(self):
        client, patcher = _patch_client("# Tailored")
        with patcher:
            tailor_resume(_MASTER, "jd")
        kwargs = client.models.generate_content.call_args.kwargs
        assert kwargs["model"] == llm_client._TAILOR_MODEL
        instruction = kwargs["config"].system_instruction
        assert "12 pt Times New Roman" in instruction
        assert "2-page limit" in instruction

    def test_page_limit_is_injected_into_the_prompt(self):
        client, patcher = _patch_client("# Tailored")
        with patcher:
            tailor_resume(_MASTER, "jd", max_pages=1)
        instruction = (
            client.models.generate_content.call_args.kwargs["config"].system_instruction
        )
        assert "1-page limit" in instruction
        assert "≤ 3 roles" in instruction
        assert "≤ 20 bullets" in instruction


class TestTailorPageBudget:
    def test_one_page_matches_the_original_caps(self):
        assert _tailor_page_budget(1) == {
            "max_pages": 1,
            "max_exp_roles": 3,
            "max_exp_bullets": 4,
            "max_projects": 5,
            "max_bullets": 20,
        }

    def test_two_pages_scales_the_caps(self):
        budget = _tailor_page_budget(2)
        assert budget["max_exp_roles"] == 4
        assert budget["max_exp_bullets"] == 5
        assert budget["max_projects"] == 10
        assert budget["max_bullets"] == 40

    def test_formatted_prompt_has_no_leftover_placeholders(self):
        prompt = _tailor_system_prompt(2)
        assert "{" not in prompt
        assert "2-page limit" in prompt
        assert "12 pt Times New Roman" in prompt

    def test_audit_report_is_appended_to_the_prompt(self):
        client, patcher = _patch_client("# Tailored")
        audit = AuditReport(markdown="## 4. Tailoring Directives\n\n1. Do the thing.")
        with patcher:
            tailor_resume(_MASTER, "jd", audit=audit)
        contents = client.models.generate_content.call_args.kwargs["contents"]
        assert "## ATS Audit" in contents
        assert "1. Do the thing." in contents

    def test_no_audit_section_when_audit_omitted(self):
        client, patcher = _patch_client("# Tailored")
        with patcher:
            tailor_resume(_MASTER, "jd")
        assert "## ATS Audit" not in (
            client.models.generate_content.call_args.kwargs["contents"]
        )

    def test_skipped_audit_is_not_sent(self):
        client, patcher = _patch_client("# Tailored")
        audit = AuditReport(markdown="partial", skipped=True, skip_reason="503")
        with patcher:
            tailor_resume(_MASTER, "jd", audit=audit)
        assert "## ATS Audit" not in (
            client.models.generate_content.call_args.kwargs["contents"]
        )

    def test_api_failure_propagates(self):
        client = MagicMock()
        client.models.generate_content.side_effect = RuntimeError("network blip")
        with patch("llm_client._get_client", return_value=client):
            with pytest.raises(RuntimeError):
                tailor_resume(_MASTER, "jd")


# ---------------------------------------------------------------------------
# Stage 3 — fact_check
# ---------------------------------------------------------------------------

_CHANGED = "# Resume\n\n## Experience\n\n### Acme\n\n- Built a Kafka pipeline\n"


class TestFactCheck:
    def test_identical_resume_passes_without_an_api_call(self):
        client, patcher = _patch_client("[]")
        with patcher:
            result = fact_check(_MASTER, _MASTER, "jd")
        assert result.passed is True
        assert result.reviewed == 0
        client.models.generate_content.assert_not_called()

    def test_all_supported_returns_passed(self):
        verdicts = [{"original": "a", "tailored": "b", "supported": True}]
        _, patcher = _patch_client(json.dumps(verdicts))
        with patcher:
            result = fact_check(_MASTER, _CHANGED, "jd")
        assert result.passed is True
        assert result.violations == []
        assert result.reviewed == 1

    def test_unsupported_edit_returns_failed(self):
        verdicts = [{
            "original": "Built a pipeline in Python",
            "tailored": "Built a Kafka pipeline",
            "supported": False,
            "severity": "major",
            "reason": "Kafka is not in the master.",
        }]
        _, patcher = _patch_client(json.dumps(verdicts))
        with patcher:
            result = fact_check(_MASTER, _CHANGED, "jd")
        assert result.passed is False
        assert len(result.major_violations) == 1

    def test_message_carries_the_full_master_as_ground_truth(self):
        client, patcher = _patch_client("[]")
        with patcher:
            fact_check(_MASTER, _CHANGED, "jd text")
        contents = client.models.generate_content.call_args.kwargs["contents"]
        assert "## Master Resume" in contents
        assert "Built a pipeline in Python" in contents
        assert "## Edits to Review" in contents
        assert "Kind: bullet" in contents

    def test_requests_structured_json(self):
        client, patcher = _patch_client("[]")
        with patcher:
            fact_check(_MASTER, _CHANGED, "jd")
        config = client.models.generate_content.call_args.kwargs["config"]
        assert config.response_mime_type == "application/json"
        assert config.response_schema is llm_client._FACTCHECK_SCHEMA

    def test_json_decode_error_skips(self):
        _, patcher = _patch_client("not valid json {{")
        with patcher:
            result = fact_check(_MASTER, _CHANGED, "jd")
        assert result.passed is True
        assert result.skipped is True
        assert "JSONDecodeError" in result.skip_reason

    def test_generic_exception_skips(self):
        client = MagicMock()
        client.models.generate_content.side_effect = RuntimeError("network blip")
        with patch("llm_client._get_client", return_value=client):
            result = fact_check(_MASTER, _CHANGED, "jd")
        assert result.passed is True
        assert result.skipped is True
        assert "RuntimeError" in result.skip_reason


_SKILLS_MASTER = (
    "## Technical Skills\n\n- **Languages:** Python, R\n\n"
    "## Experience\n\n### Acme\n\n- Built a pipeline in Python\n"
)
_SKILLS_PADDED = _SKILLS_MASTER.replace(
    "- **Languages:** Python, R", "- **Languages:** Python, R, Rust"
)


class TestFactCheckSkillsIntegrity:
    """Padded Technical Skills rows are caught without trusting the model."""

    def test_flagged_even_when_the_model_approves(self):
        verdicts = [{
            "original": "- **Languages:** Python, R",
            "tailored": "- **Languages:** Python, R, Rust",
            "supported": True,
        }]
        _, patcher = _patch_client(json.dumps(verdicts))
        with patcher:
            result = fact_check(_SKILLS_MASTER, _SKILLS_PADDED, "jd")
        assert result.passed is False
        assert "'Rust'" in result.violations[0]["reason"]

    def test_not_duplicated_when_the_model_flags_it_too(self):
        verdicts = [{
            "original": "**Languages:** Python, R",
            "tailored": "**Languages:** Python, R, Rust",
            "supported": False,
            "severity": "major",
            "reason": "Rust is not in the master.",
        }]
        _, patcher = _patch_client(json.dumps(verdicts))
        with patcher:
            result = fact_check(_SKILLS_MASTER, _SKILLS_PADDED, "jd")
        assert len(result.violations) == 1

    def test_survives_a_skipped_model_call(self):
        client = MagicMock()
        client.models.generate_content.side_effect = RuntimeError("network blip")
        with patch("llm_client._get_client", return_value=client):
            result = fact_check(_SKILLS_MASTER, _SKILLS_PADDED, "jd")
        assert result.skipped is True
        assert result.passed is False
        assert len(result.violations) == 1
