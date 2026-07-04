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
        assert parse_bullets("## Skills\n- Python\n- SQL\n") == {
            "Skills": ["Python", "SQL"]
        }

    def test_h2_and_h3(self):
        md = "## Experience\n### Acme Corp\n- Did thing A\n- Did thing B\n"
        assert parse_bullets(md) == {
            "Experience / Acme Corp": ["Did thing A", "Did thing B"]
        }

    def test_h3_resets_on_new_h2(self):
        md = "## Experience\n### Acme\n- bullet A\n## Projects\n- bullet B\n"
        result = parse_bullets(md)
        assert result["Experience / Acme"] == ["bullet A"]
        assert result["Projects"] == ["bullet B"]

    def test_multiple_h3_under_same_h2(self):
        md = "## Experience\n### Job One\n- alpha\n### Job Two\n- beta\n"
        result = parse_bullets(md)
        assert result["Experience / Job One"] == ["alpha"]
        assert result["Experience / Job Two"] == ["beta"]

    def test_ignores_non_bullet_lines(self):
        md = "## Skills\n\nSome prose line.\n- actual bullet\n"
        assert parse_bullets(md) == {"Skills": ["actual bullet"]}

    def test_empty_string(self):
        assert parse_bullets("") == {}

    def test_strips_bullet_prefix_whitespace(self):
        assert parse_bullets("## S\n-  leading space bullet\n") == {
            "S": ["leading space bullet"]
        }


# ---------------------------------------------------------------------------
# _token_overlap
# ---------------------------------------------------------------------------

class TestTokenOverlap:
    @pytest.mark.parametrize("a, b, expected", [
        ("foo bar baz", "foo bar baz", pytest.approx(1.0)),  # identical
        ("alpha beta",  "gamma delta", pytest.approx(0.0)),  # disjoint
        ("Python",      "python",      pytest.approx(1.0)),  # case-insensitive
        ("",            "",            pytest.approx(1.0)),  # both empty
        ("foo",         "",            pytest.approx(0.0)),  # one empty
    ])
    def test_score(self, a, b, expected):
        assert _token_overlap(a, b) == expected

    def test_partial_overlap_is_between_zero_and_one(self):
        score = _token_overlap("machine learning pipelines", "machine learning")
        assert 0.0 < score < 1.0


# ---------------------------------------------------------------------------
# _closest_match
# ---------------------------------------------------------------------------

class TestClosestMatch:
    def test_returns_best_candidate(self):
        candidates = ["did thing A", "did thing B completely different"]
        assert _closest_match("did thing A with extra", candidates) == "did thing A"

    def test_empty_candidates_returns_none(self):
        assert _closest_match("anything", []) is None


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

    def test_detects_single_change_with_correct_section(self):
        tailored = (
            "## Experience\n### Acme\n"
            "- Built a data pipeline in Python\n"
            "- Managed a team of five\n"
        )
        changes = find_changed_bullets(self.MASTER, tailored)
        assert len(changes) == 1
        assert changes[0].tailored == "Built a data pipeline in Python"
        assert changes[0].original == "Built a pipeline in Python"
        assert changes[0].section == "Experience / Acme"

    def test_closest_match_selection(self):
        tailored = (
            "## Experience\n### Acme\n"
            "- Built a data pipeline in Python\n"
            "- Managed a large team of five\n"
        )
        changes = find_changed_bullets(self.MASTER, tailored)
        by_tailored = {c.tailored: c.original for c in changes}
        assert by_tailored["Built a data pipeline in Python"] == (  # noqa: E501
            "Built a pipeline in Python"
        )
        assert by_tailored["Managed a large team of five"] == "Managed a team of five"

    def test_new_section_bullet_flagged(self):
        tailored = self.MASTER + "## Projects\n- New project bullet\n"
        changes = find_changed_bullets(self.MASTER, tailored)
        assert any(c.tailored == "New project bullet" for c in changes)


# ---------------------------------------------------------------------------
# revert_violations
# ---------------------------------------------------------------------------

class TestRevertViolations:
    def test_reverts_flagged_bullet(self):
        result = revert_violations(
            "## Section\n- foo BAZ bar\n- unchanged\n",
            [{"original": "foo bar", "tailored": "foo BAZ bar"}],
        )
        assert "foo BAZ bar" not in result
        assert "- foo bar" in result
        assert "- unchanged" in result

    def test_empty_violations_returns_unchanged(self):
        md = "## S\n- keep this\n- also keep\n"
        assert revert_violations(md, []) == md

    def test_reverts_multiple_violations(self):
        md = "## S\n- bad bullet one\n- bad bullet two\n"
        violations = [
            {"original": "good bullet one", "tailored": "bad bullet one"},
            {"original": "good bullet two", "tailored": "bad bullet two"},
        ]
        result = revert_violations(md, violations)
        assert "- good bullet one" in result
        assert "- good bullet two" in result
        assert "bad bullet" not in result

    def test_reverts_only_first_occurrence_of_duplicate(self):
        """Same tailored text in two sections — only first occurrence is reverted."""
        result = revert_violations(
            "## S\n- dup bullet\n## T\n- dup bullet\n",
            [{"original": "orig bullet", "tailored": "dup bullet"}],
        )
        bullets = [
            ln.strip() for ln in result.splitlines() if ln.strip().startswith("- ")
        ]
        assert bullets.count("- orig bullet") == 1
        assert bullets.count("- dup bullet") == 1

    def test_preserves_indentation(self):
        result = revert_violations(
            "## S\n  - indented bullet\n",
            [{"original": "original", "tailored": "indented bullet"}],
        )
        assert "  - original" in result

    def test_skips_violation_with_empty_original(self):
        md = "## S\n- some bullet\n"
        reverted = revert_violations(md, [{"original": "", "tailored": "some bullet"}])
        assert "- some bullet" in reverted


# ---------------------------------------------------------------------------
# ValidationResult.summary
# ---------------------------------------------------------------------------

class TestValidationResultSummary:
    def test_passed(self):
        summary = ValidationResult(passed=True, violations=[]).summary()
        assert summary.startswith("✓")
        assert "0 changed bullets" in summary

    def test_skipped(self):
        summary = ValidationResult(
            passed=True, skipped=True, skip_reason="validate=False"
        ).summary()
        assert summary.startswith("⚠")
        assert "validate=False" in summary

    def test_failed_lists_reasons(self):
        summary = ValidationResult(
            passed=False,
            violations=[{
                "reason": "Added SQL", "original": "Python", "tailored": "Python, SQL",
            }],
        ).summary()
        assert summary.startswith("✗")
        assert "Added SQL" in summary
        assert "Python, SQL" in summary

    def test_failed_missing_reason_key(self):
        summary = ValidationResult(
            passed=False, violations=[{"original": "a", "tailored": "b"}]
        ).summary()
        assert "(no reason given)" in summary


# ---------------------------------------------------------------------------
# report_and_maybe_revert
# ---------------------------------------------------------------------------

_SINGLE_VIOLATION_MD = "## S\n- bad bullet\n"
_SINGLE_VIOLATION = [
    {"original": "good bullet", "tailored": "bad bullet", "reason": "r"}
]


@pytest.fixture
def single_violation_result():
    return ValidationResult(passed=False, violations=_SINGLE_VIOLATION)


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

    def test_user_accepts_revert(self, capsys, single_violation_result):
        out = report_and_maybe_revert(
            _SINGLE_VIOLATION_MD, single_violation_result, input_fn=lambda _: "y"
        )
        assert "- good bullet" in out
        assert "bad bullet" not in out
        assert "Reverted 1 edit(s)" in capsys.readouterr().out

    def test_user_declines_revert(self, single_violation_result):
        out = report_and_maybe_revert(
            _SINGLE_VIOLATION_MD, single_violation_result, input_fn=lambda _: "n"
        )
        assert out == _SINGLE_VIOLATION_MD

    def test_reverts_only_accepted_bullets(self, capsys):
        md = "## S\n- bad bullet one\n- bad bullet two\n"
        violations = [
            {"original": "good bullet one", "tailored": "bad bullet one",
             "reason": "r1"},
            {"original": "good bullet two", "tailored": "bad bullet two",
             "reason": "r2"},
        ]
        result = ValidationResult(passed=False, violations=violations)
        answers = iter(["y", "n"])
        out = report_and_maybe_revert(md, result, input_fn=lambda _: next(answers))
        assert "- good bullet one" in out
        assert "- bad bullet two" in out
        assert "bad bullet one" not in out
        captured = capsys.readouterr().out
        assert "Edit 1 of 2:" in captured
        assert "Edit 2 of 2:" in captured
        assert "Reverted 1 edit(s)" in captured

    @pytest.mark.parametrize("prompts, expect_revert", [
        (["y"],  True),   # EOF after accepting first → first reverted, second not
        ([],     False),  # EOF on very first prompt → nothing reverted
    ])
    def test_eof_stops_review(self, prompts, expect_revert):
        md = "## S\n- bad bullet one\n- bad bullet two\n"
        violations = [
            {"original": "good bullet one", "tailored": "bad bullet one",
             "reason": "r1"},
            {"original": "good bullet two", "tailored": "bad bullet two",
             "reason": "r2"},
        ]
        result = ValidationResult(passed=False, violations=violations)
        it = iter(prompts)

        def _input(_):
            try:
                return next(it)
            except StopIteration:
                raise EOFError

        out = report_and_maybe_revert(md, result, input_fn=_input)
        assert ("- good bullet one" in out) == expect_revert
        assert "- bad bullet two" in out  # second violation never touched

    @pytest.mark.parametrize("junk_then_valid, expect_revert", [
        (["", "maybe", "YES", "y"], True),   # junk then accept
        (["x", "n"],               False),  # junk then decline
    ])
    def test_invalid_input_reprompts(
        self, capsys, junk_then_valid, expect_revert, single_violation_result
    ):
        answers = iter(junk_then_valid)
        out = report_and_maybe_revert(
            _SINGLE_VIOLATION_MD,
            single_violation_result,
            input_fn=lambda _: next(answers),
        )
        assert ("- good bullet" in out) == expect_revert
        assert "Please enter 'y' or 'n'" in capsys.readouterr().out

    def test_invalid_input_then_eof_does_not_revert(self, single_violation_result):
        calls = iter(["?"])

        def _input(_):
            try:
                return next(calls)
            except StopIteration:
                raise EOFError

        out = report_and_maybe_revert(
            _SINGLE_VIOLATION_MD, single_violation_result, input_fn=_input
        )
        assert out == _SINGLE_VIOLATION_MD
