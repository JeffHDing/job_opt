"""
Unit tests for resume_diff.py.

"""
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from resume_diff import (
    ValidationResult,
    _closest_match,
    _token_overlap,
    find_changed_bullets,
    parse_bullets,
    report_and_maybe_revert,
    revert_violations,
)

# ---------------------------------------------------------------------------
# parse_bullets
# ---------------------------------------------------------------------------

class TestParseBullets:
    def test_h2_only(self):
        md = "## Skills\n- Python\n- SQL\n"
        result = parse_bullets(md)
        assert result == {"Skills": ["Python", "SQL"]}

    def test_h2_and_h3(self):
        md = "## Experience\n### Acme Corp\n- Did thing A\n- Did thing B\n"
        result = parse_bullets(md)
        assert result == {"Experience / Acme Corp": ["Did thing A", "Did thing B"]}

    def test_h3_resets_on_new_h2(self):
        md = (
            "## Experience\n### Acme\n- bullet A\n"
            "## Projects\n- bullet B\n"
        )
        result = parse_bullets(md)
        assert "Experience / Acme" in result
        assert "Projects" in result
        assert result["Projects"] == ["bullet B"]

    def test_multiple_h3_under_same_h2(self):
        md = (
            "## Experience\n"
            "### Job One\n- alpha\n"
            "### Job Two\n- beta\n"
        )
        result = parse_bullets(md)
        assert result["Experience / Job One"] == ["alpha"]
        assert result["Experience / Job Two"] == ["beta"]

    def test_ignores_non_bullet_lines(self):
        md = "## Skills\n\nSome prose line.\n- actual bullet\n"
        result = parse_bullets(md)
        assert result["Skills"] == ["actual bullet"]

    def test_empty_string(self):
        assert parse_bullets("") == {}

    def test_strips_bullet_prefix_whitespace(self):
        md = "## S\n-  leading space bullet\n"
        result = parse_bullets(md)
        assert result["S"] == ["leading space bullet"]


# ---------------------------------------------------------------------------
# _token_overlap
# ---------------------------------------------------------------------------

class TestTokenOverlap:
    def test_identical_strings(self):
        assert _token_overlap("foo bar baz", "foo bar baz") == pytest.approx(1.0)

    def test_no_overlap(self):
        assert _token_overlap("alpha beta", "gamma delta") == pytest.approx(0.0)

    def test_partial_overlap(self):
        score = _token_overlap("machine learning pipelines", "machine learning")
        assert 0.0 < score < 1.0

    def test_case_insensitive(self):
        assert _token_overlap("Python", "python") == pytest.approx(1.0)

    def test_both_empty(self):
        assert _token_overlap("", "") == pytest.approx(1.0)

    def test_one_empty(self):
        assert _token_overlap("foo", "") == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# _closest_match
# ---------------------------------------------------------------------------

class TestClosestMatch:
    def test_returns_best_candidate(self):
        candidates = ["did thing A", "did thing B completely different"]
        assert _closest_match("did thing A with extra", candidates) == "did thing A"

    def test_empty_candidates_returns_none(self):
        assert _closest_match("anything", []) is None

    def test_single_candidate(self):
        assert _closest_match("foo bar", ["foo bar baz"]) == "foo bar baz"


# ---------------------------------------------------------------------------
# find_changed_bullets
# ---------------------------------------------------------------------------

class TestFindChangedBullets:
    MASTER = (
        "## Experience\n### Acme\n"
        "- Built a pipeline in Python\n"
        "- Managed a team of five\n"
    )

    def test_no_changes(self):
        assert find_changed_bullets(self.MASTER, self.MASTER) == []

    def test_detects_single_change(self):
        tailored = (
            "## Experience\n### Acme\n"
            "- Built a data pipeline in Python\n"
            "- Managed a team of five\n"
        )
        changes = find_changed_bullets(self.MASTER, tailored)
        assert len(changes) == 1
        assert changes[0].tailored == "Built a data pipeline in Python"
        assert changes[0].original == "Built a pipeline in Python"

    def test_closest_match_selection(self):
        tailored = (
            "## Experience\n### Acme\n"
            "- Built a data pipeline in Python\n"
            "- Managed a large team of five\n"
        )
        changes = find_changed_bullets(self.MASTER, tailored)
        sections = {c.tailored: c.original for c in changes}
        assert (
            sections["Built a data pipeline in Python"] == "Built a pipeline in Python"
        )
        assert sections["Managed a large team of five"] == "Managed a team of five"

    def test_new_section_bullet_flagged(self):
        tailored = (
            "## Experience\n### Acme\n"
            "- Built a pipeline in Python\n"
            "- Managed a team of five\n"
            "## Projects\n- New project bullet\n"
        )
        changes = find_changed_bullets(self.MASTER, tailored)
        assert any(c.tailored == "New project bullet" for c in changes)

    def test_change_section_is_recorded(self):
        tailored = (
            "## Experience\n### Acme\n"
            "- Built a data pipeline in Python\n"
            "- Managed a team of five\n"
        )
        changes = find_changed_bullets(self.MASTER, tailored)
        assert changes[0].section == "Experience / Acme"


# ---------------------------------------------------------------------------
# revert_violations
# ---------------------------------------------------------------------------

class TestRevertViolations:
    def test_reverts_flagged_bullet(self):
        md = "## Section\n- foo BAZ bar\n- unchanged\n"
        violations = [{"original": "foo bar", "tailored": "foo BAZ bar"}]
        result = revert_violations(md, violations)
        assert "foo BAZ bar" not in result
        assert "- foo bar" in result
        assert "- unchanged" in result

    def test_preserves_unflagged_bullets(self):
        md = "## S\n- keep this\n- also keep\n"
        result = revert_violations(md, [])
        assert result == md

    def test_reverts_multiple_violations(self):
        md = "## S\n- bad bullet one\n- bad bullet two\n"
        violations = [
            {"original": "good bullet one", "tailored": "bad bullet one"},
            {"original": "good bullet two", "tailored": "bad bullet two"},
        ]
        result = revert_violations(md, violations)
        assert "bad bullet one" not in result
        assert "bad bullet two" not in result
        assert "- good bullet one" in result
        assert "- good bullet two" in result

    def test_reverts_only_first_occurrence(self):
        """Same tailored text appearing twice — only the first should be reverted."""
        md = "## S\n- dup bullet\n## T\n- dup bullet\n"
        violations = [{"original": "orig bullet", "tailored": "dup bullet"}]
        result = revert_violations(md, violations)
        lines = [
            ln.strip()
            for ln in result.splitlines()
            if ln.strip().startswith("- ")
        ]
        assert lines.count("- orig bullet") == 1
        assert lines.count("- dup bullet") == 1

    def test_preserves_indentation(self):
        md = "## S\n  - indented bullet\n"
        violations = [{"original": "original", "tailored": "indented bullet"}]
        result = revert_violations(md, violations)
        assert "  - original" in result

    def test_empty_violations_list(self):
        md = "## S\n- some bullet\n"
        assert revert_violations(md, []) == md

    def test_skips_violation_with_missing_keys(self):
        md = "## S\n- some bullet\n"
        violations = [{"original": "", "tailored": "some bullet"}]
        result = revert_violations(md, violations)
        assert "- some bullet" in result


# ---------------------------------------------------------------------------
# ValidationResult.summary
# ---------------------------------------------------------------------------

class TestValidationResultSummary:
    def test_passed(self):
        r = ValidationResult(passed=True, violations=[])
        assert r.summary().startswith("✓")

    def test_passed_shows_zero_violations(self):
        r = ValidationResult(passed=True, violations=[])
        assert "0 changed bullets" in r.summary()

    def test_skipped(self):
        r = ValidationResult(passed=True, skipped=True, skip_reason="validate=False")
        assert r.summary().startswith("⚠")
        assert "validate=False" in r.summary()

    def test_failed_lists_reasons(self):
        r = ValidationResult(
            passed=False,
            violations=[
                {
                    "reason": "Added SQL",
                    "original": "Python",
                    "tailored": "Python, SQL",
                },
            ],
        )
        summary = r.summary()
        assert summary.startswith("✗")
        assert "Added SQL" in summary
        assert "Python, SQL" in summary

    def test_failed_missing_reason_key(self):
        r = ValidationResult(
            passed=False, violations=[{"original": "a", "tailored": "b"}]
        )
        assert "(no reason given)" in r.summary()


# ---------------------------------------------------------------------------
# report_and_maybe_revert
# ---------------------------------------------------------------------------

class TestReportAndMaybeRevert:
    def test_passed_result_returns_unchanged_without_prompting(self, capsys):
        result = ValidationResult(passed=True, violations=[])
        input_fn = MagicMock(side_effect=AssertionError("should not prompt"))
        out = report_and_maybe_revert("# Resume\n- bullet\n", result, input_fn=input_fn)
        assert out == "# Resume\n- bullet\n"
        input_fn.assert_not_called()
        assert "Validation Report" in capsys.readouterr().out

    def test_skipped_result_returns_unchanged_without_prompting(self):
        result = ValidationResult(passed=False, skipped=True, skip_reason="timeout")
        input_fn = MagicMock(side_effect=AssertionError("should not prompt"))
        out = report_and_maybe_revert("# Resume\n- bullet\n", result, input_fn=input_fn)
        assert out == "# Resume\n- bullet\n"
        input_fn.assert_not_called()

    def test_failed_result_user_accepts_revert(self, capsys):
        md = "## S\n- bad bullet\n"
        violations = [{"original": "good bullet", "tailored": "bad bullet"}]
        result = ValidationResult(passed=False, violations=violations)
        out = report_and_maybe_revert(md, result, input_fn=lambda _: "y")
        assert "- good bullet" in out
        assert "bad bullet" not in out
        assert "Reverted 1 edit(s) to originals." in capsys.readouterr().out

    def test_failed_result_user_declines_revert(self):
        md = "## S\n- bad bullet\n"
        violations = [{"original": "good bullet", "tailored": "bad bullet"}]
        result = ValidationResult(passed=False, violations=violations)
        out = report_and_maybe_revert(md, result, input_fn=lambda _: "n")
        assert out == md

    def test_failed_result_reverts_only_accepted_bullets(self, capsys):
        md = (
            "## S\n"
            "- bad bullet one\n"
            "- bad bullet two\n"
        )
        violations = [
            {"original": "good bullet one", "tailored": "bad bullet one", "reason": "r1"},
            {"original": "good bullet two", "tailored": "bad bullet two", "reason": "r2"},
        ]
        result = ValidationResult(passed=False, violations=violations)
        answers = iter(["y", "n"])
        out = report_and_maybe_revert(
            md, result, input_fn=lambda _: next(answers)
        )
        assert "- good bullet one" in out
        assert "- bad bullet two" in out
        assert "bad bullet one" not in out
        captured = capsys.readouterr().out
        assert "Edit 1 of 2:" in captured
        assert "Edit 2 of 2:" in captured
        assert "Reverted 1 edit(s) to originals." in captured

    def test_failed_result_eof_stops_review_without_reverting_rest(self):
        md = (
            "## S\n"
            "- bad bullet one\n"
            "- bad bullet two\n"
        )
        violations = [
            {"original": "good bullet one", "tailored": "bad bullet one"},
            {"original": "good bullet two", "tailored": "bad bullet two"},
        ]
        result = ValidationResult(passed=False, violations=violations)
        prompts = iter(["y"])

        def _input(_):
            try:
                return next(prompts)
            except StopIteration:
                raise EOFError

        out = report_and_maybe_revert(md, result, input_fn=_input)
        assert "- good bullet one" in out
        assert "- bad bullet two" in out

    def test_failed_result_eof_on_first_prompt_reverts_nothing(self):
        md = "## S\n- bad bullet\n"
        violations = [{"original": "good bullet", "tailored": "bad bullet"}]
        result = ValidationResult(passed=False, violations=violations)

        def _raise(_):
            raise EOFError

        out = report_and_maybe_revert(md, result, input_fn=_raise)
        assert out == md

    def test_default_input_fn_is_builtin_input(self, monkeypatch):
        md = "## S\n- bad bullet\n"
        violations = [{"original": "good bullet", "tailored": "bad bullet"}]
        result = ValidationResult(passed=False, violations=violations)
        monkeypatch.setattr("builtins.input", lambda _: "y")
        out = report_and_maybe_revert(md, result)
        assert "- good bullet" in out
