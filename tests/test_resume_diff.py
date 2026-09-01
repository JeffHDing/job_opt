"""
Unit tests for resume_diff.py.
"""
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from resume_diff import (
    NO_MASTER_MATCH,
    ValidationResult,
    _closest_match,
    _token_overlap,
    dedupe_bullets,
    find_changed_bullets,
    find_changed_lines,
    find_changes,
    find_unsupported_skills,
    parse_bullets,
    parse_content_lines,
    report_and_maybe_revert,
    restore_dropped_skills,
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

    def test_unrelated_candidates_return_none(self):
        candidates = ["Managed a team of five engineers across two offices"]
        assert _closest_match("Trained a CNN on retina scans", candidates) is None

    def test_threshold_is_configurable(self):
        candidates = ["Managed a team of five engineers across two offices"]
        assert _closest_match(
            "Trained a CNN on retina scans", candidates, min_overlap=0.0
        ) == candidates[0]


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
        assert by_tailored[
            "Built a data pipeline in Python"] == "Built a pipeline in Python"
        assert by_tailored["Managed a large team of five"] == "Managed a team of five"

    def test_new_section_bullet_flagged(self):
        tailored = self.MASTER + "## Projects\n- New project bullet\n"
        changes = find_changed_bullets(self.MASTER, tailored)
        assert any(c.tailored == "New project bullet" for c in changes)

    def test_unrelated_bullet_has_no_original(self):
        """A wholly new bullet must not be paired with an unrelated master one."""
        tailored = (
            "## Experience\n### Acme\n"
            "- Built a pipeline in Python\n"
            "- Managed a team of five\n"
            "- Trained a CNN on retina scans using Keras\n"
        )
        changes = find_changed_bullets(self.MASTER, tailored)
        assert len(changes) == 1
        assert changes[0].original == NO_MASTER_MATCH


# ---------------------------------------------------------------------------
# parse_content_lines / find_changed_lines
# ---------------------------------------------------------------------------

_MASTER_WITH_IDENTITY = (
    "# Jane Doe\n\n"
    "**Data Analyst** | jane@example.com\n\n"
    "## Experience\n\n"
    "### Data Manager\n\n"
    "_Acme Corp_ | Feb 2022 - Feb 2024\n\n"
    "- Built a pipeline in Python\n"
)


class TestParseContentLines:
    def test_collects_headings_and_metadata_but_not_bullets(self):
        assert parse_content_lines(_MASTER_WITH_IDENTITY) == [
            "# Jane Doe",
            "**Data Analyst** | jane@example.com",
            "## Experience",
            "### Data Manager",
            "_Acme Corp_ | Feb 2022 - Feb 2024",
        ]

    def test_empty_string(self):
        assert parse_content_lines("") == []


class TestFindChangedLines:
    def test_identical_documents_have_no_changes(self):
        assert find_changed_lines(
            _MASTER_WITH_IDENTITY, _MASTER_WITH_IDENTITY
        ) == []

    def test_detects_promoted_job_title(self):
        tailored = _MASTER_WITH_IDENTITY.replace(
            "### Data Manager", "### Senior Data Scientist"
        )
        changes = find_changed_lines(_MASTER_WITH_IDENTITY, tailored)
        assert len(changes) == 1
        assert changes[0].tailored == "### Senior Data Scientist"
        assert changes[0].kind == "line"

    def test_detects_shifted_date_range(self):
        tailored = _MASTER_WITH_IDENTITY.replace(
            "Feb 2022 - Feb 2024", "Feb 2020 - Feb 2024"
        )
        changes = find_changed_lines(_MASTER_WITH_IDENTITY, tailored)
        assert [c.tailored for c in changes] == [
            "_Acme Corp_ | Feb 2020 - Feb 2024"
        ]
        assert changes[0].original == "_Acme Corp_ | Feb 2022 - Feb 2024"

    def test_reordering_sections_is_not_a_change(self):
        reordered = (
            "# Jane Doe\n\n"
            "## Experience\n\n"
            "### Data Manager\n\n"
            "_Acme Corp_ | Feb 2022 - Feb 2024\n\n"
            "- Built a pipeline in Python\n\n"
            "**Data Analyst** | jane@example.com\n"
        )
        assert find_changed_lines(_MASTER_WITH_IDENTITY, reordered) == []

    def test_dropping_an_entry_is_not_a_change(self):
        trimmed = "# Jane Doe\n\n**Data Analyst** | jane@example.com\n"
        assert find_changed_lines(_MASTER_WITH_IDENTITY, trimmed) == []

    def test_invented_heading_has_no_original(self):
        tailored = _MASTER_WITH_IDENTITY + "\n### Kubernetes Platform Migration\n"
        changes = find_changed_lines(_MASTER_WITH_IDENTITY, tailored)
        assert len(changes) == 1
        assert changes[0].original == NO_MASTER_MATCH


class TestFindChanges:
    def test_returns_line_changes_before_bullet_changes(self):
        tailored = _MASTER_WITH_IDENTITY.replace(
            "### Data Manager", "### Senior Data Scientist"
        ).replace("Built a pipeline", "Built a Kafka pipeline")
        kinds = [c.kind for c in find_changes(_MASTER_WITH_IDENTITY, tailored)]
        assert kinds == ["line", "bullet"]


# ---------------------------------------------------------------------------
# find_unsupported_skills
# ---------------------------------------------------------------------------

_MASTER_WITH_SKILLS = (
    "## Technical Skills\n\n"
    "- **Programming & Databases:** Python, R, PostgreSQL\n"
    "- **Tools & Frameworks:** AWS, Git\n\n"
    "## Projects\n\n"
    "### Retina CNN\n\n"
    "- Trained a CNN on retina scans using Keras and TensorFlow.\n"
)


def _swap_skills_row(row: str) -> str:
    return _MASTER_WITH_SKILLS.replace(
        "- **Programming & Databases:** Python, R, PostgreSQL", row
    )


class TestFindUnsupportedSkills:
    def test_unchanged_skills_pass(self):
        assert find_unsupported_skills(
            _MASTER_WITH_SKILLS, _MASTER_WITH_SKILLS
        ) == []

    def test_reordering_a_row_is_supported(self):
        tailored = _swap_skills_row(
            "- **Programming & Databases:** PostgreSQL, Python, R"
        )
        assert find_unsupported_skills(_MASTER_WITH_SKILLS, tailored) == []

    def test_flags_a_term_found_nowhere_in_the_master(self):
        tailored = _swap_skills_row(
            "- **Programming & Databases:** SQL, Python, R, PostgreSQL"
        )
        violations = find_unsupported_skills(_MASTER_WITH_SKILLS, tailored)
        assert len(violations) == 1
        assert "'SQL'" in violations[0]["reason"]
        assert violations[0]["severity"] == "major"
        assert violations[0]["supported"] is False

    def test_promoting_a_term_used_in_a_project_is_supported(self):
        tailored = _swap_skills_row(
            "- **Programming & Databases:** Python, R, PostgreSQL, Keras"
        )
        assert find_unsupported_skills(_MASTER_WITH_SKILLS, tailored) == []

    def test_violation_reverts_the_whole_row(self):
        tailored = _swap_skills_row(
            "- **Programming & Databases:** Rust, Python, R, PostgreSQL"
        )
        violations = find_unsupported_skills(_MASTER_WITH_SKILLS, tailored)
        reverted = revert_violations(tailored, violations)
        assert "Rust" not in reverted
        assert "**Programming & Databases:** Python, R, PostgreSQL" in reverted

    def test_reports_every_added_term_in_one_violation(self):
        tailored = _swap_skills_row(
            "- **Programming & Databases:** Scala, Rust, Python, R, PostgreSQL"
        )
        reason = find_unsupported_skills(_MASTER_WITH_SKILLS, tailored)[0]["reason"]
        assert "'Scala'" in reason and "'Rust'" in reason
        assert "do not appear" in reason

    def test_dropped_row_is_not_flagged(self):
        tailored = "## Technical Skills\n\n- **Tools & Frameworks:** AWS, Git\n"
        assert find_unsupported_skills(_MASTER_WITH_SKILLS, tailored) == []

    def test_resume_without_a_skills_section_is_skipped(self):
        assert find_unsupported_skills("## Experience\n\n- did work\n", "x") == []


class TestRestoreDroppedSkills:
    def test_unchanged_skills_are_untouched(self):
        assert restore_dropped_skills(
            _MASTER_WITH_SKILLS, _MASTER_WITH_SKILLS
        ) == _MASTER_WITH_SKILLS

    def test_dropped_term_is_appended_to_its_row(self):
        tailored = _swap_skills_row("- **Programming & Databases:** Python, R")
        restored = restore_dropped_skills(_MASTER_WITH_SKILLS, tailored)
        assert "- **Programming & Databases:** Python, R, PostgreSQL" in restored

    def test_tailored_ordering_is_preserved(self):
        tailored = _swap_skills_row("- **Programming & Databases:** R, Python")
        restored = restore_dropped_skills(_MASTER_WITH_SKILLS, tailored)
        assert "- **Programming & Databases:** R, Python, PostgreSQL" in restored

    def test_added_terms_are_left_in_place(self):
        tailored = _swap_skills_row("- **Programming & Databases:** Python, Rust")
        restored = restore_dropped_skills(_MASTER_WITH_SKILLS, tailored)
        assert "- **Programming & Databases:** Python, Rust, R, PostgreSQL" in restored

    def test_deleted_row_is_left_alone(self):
        tailored = "## Technical Skills\n\n- **Tools & Frameworks:** AWS, Git\n"
        assert restore_dropped_skills(_MASTER_WITH_SKILLS, tailored) == tailored

    def test_other_sections_are_untouched(self):
        tailored = _swap_skills_row("- **Programming & Databases:** Python")
        restored = restore_dropped_skills(_MASTER_WITH_SKILLS, tailored)
        assert "- Trained a CNN on retina scans using Keras and TensorFlow." in restored

    def test_master_without_skills_section_is_a_noop(self):
        tailored = "## Technical Skills\n\n- **Languages:** Python\n"
        assert restore_dropped_skills("## Experience\n\n- did work\n", tailored) == (
            tailored
        )


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

    def test_drops_bullet_with_no_master_counterpart(self):
        result = revert_violations(
            "## S\n- keep this\n- fabricated bullet\n",
            [{"original": NO_MASTER_MATCH, "tailored": "fabricated bullet"}],
        )
        assert "fabricated bullet" not in result
        assert NO_MASTER_MATCH not in result
        assert "- keep this\n" in result

    def test_revert_does_not_duplicate_existing_bullet(self):
        """The original is already in the section, so the flagged bullet is dropped."""
        result = revert_violations(
            "## Experience\n### Acme\n- shared original\n- reworded bullet\n",
            [{"original": "shared original", "tailored": "reworded bullet"}],
        )
        assert result.count("- shared original") == 1
        assert "reworded bullet" not in result

    def test_two_violations_reverting_to_same_original_collapse(self):
        result = revert_violations(
            "## Experience\n### Acme\n- reworded one\n- reworded two\n",
            [
                {"original": "shared original", "tailored": "reworded one"},
                {"original": "shared original", "tailored": "reworded two"},
            ],
        )
        assert result.count("- shared original") == 1

    def test_same_original_in_different_sections_is_kept(self):
        result = revert_violations(
            "## S\n- reworded one\n## T\n- reworded two\n",
            [
                {"original": "shared original", "tailored": "reworded one"},
                {"original": "shared original", "tailored": "reworded two"},
            ],
        )
        assert result.count("- shared original") == 2

    def test_reverts_a_heading_without_adding_a_bullet_marker(self):
        result = revert_violations(
            "## Experience\n\n### Senior Data Scientist\n\n- kept bullet\n",
            [{
                "original": "### Data Manager",
                "tailored": "### Senior Data Scientist",
            }],
        )
        assert "### Data Manager" in result
        assert "- ### Data Manager" not in result
        assert "Senior Data Scientist" not in result

    def test_drops_invented_heading_with_no_master_counterpart(self):
        result = revert_violations(
            "## Projects\n\n### Invented Project\n\n- kept bullet\n",
            [{"original": NO_MASTER_MATCH, "tailored": "### Invented Project"}],
        )
        assert "Invented Project" not in result
        assert "- kept bullet" in result


# ---------------------------------------------------------------------------
# dedupe_bullets
# ---------------------------------------------------------------------------

class TestDedupeBullets:
    def test_removes_repeat_within_section(self):
        md = "## Experience\n### Acme\n- same point\n- other\n- same point\n"
        assert dedupe_bullets(md) == (
            "## Experience\n### Acme\n- same point\n- other\n"
        )

    def test_keeps_same_bullet_in_different_sections(self):
        md = "## S\n- shared\n## T\n- shared\n"
        assert dedupe_bullets(md) == md

    def test_keeps_same_bullet_under_different_h3(self):
        md = "## Experience\n### Acme\n- shared\n### Globex\n- shared\n"
        assert dedupe_bullets(md) == md

    def test_leaves_clean_markdown_untouched(self):
        md = "# Name\n\n## Skills\n\n- Python\n- SQL\n\n## Experience\n\n- Did work\n"
        assert dedupe_bullets(md) == md

    def test_preserves_trailing_newline_absence(self):
        assert dedupe_bullets("## S\n- a\n- a") == "## S\n- a\n"


# ---------------------------------------------------------------------------
# ValidationResult.summary
# ---------------------------------------------------------------------------

class TestValidationResultSummary:
    def test_passed(self):
        summary = ValidationResult(passed=True, violations=[], reviewed=4).summary()
        assert summary.startswith("✓")
        assert "4 changed item(s)" in summary

    def test_skipped(self):
        summary = ValidationResult(
            passed=True, skipped=True, skip_reason="factcheck=False"
        ).summary()
        assert summary.startswith("⚠")
        assert "factcheck=False" in summary

    def test_failed_lists_reasons(self):
        summary = ValidationResult(
            passed=False,
            reviewed=3,
            violations=[{
                "reason": "Added SQL",
                "original": "Python",
                "tailored": "Python, SQL",
                "severity": "major",
            }],
        ).summary()
        assert summary.startswith("✗")
        assert "1 unsupported edit(s) out of 3 reviewed" in summary
        assert "(1 major)" in summary
        assert "[major] Added SQL" in summary
        assert "Python, SQL" in summary

    def test_failed_missing_reason_key(self):
        summary = ValidationResult(
            passed=False, violations=[{"original": "a", "tailored": "b"}]
        ).summary()
        assert "(no reason given)" in summary

    def test_major_violations_filters_by_severity(self):
        result = ValidationResult(
            passed=False,
            violations=[
                {"tailored": "a", "severity": "major"},
                {"tailored": "b", "severity": "minor"},
            ],
        )
        assert [v["tailored"] for v in result.major_violations] == ["a"]


# ---------------------------------------------------------------------------
# report_and_maybe_revert
# ---------------------------------------------------------------------------

_SINGLE_VIOLATION_MD = "## S\n- bad bullet\n"
_SINGLE_VIOLATION = [
    {"original": "good bullet",
    "tailored": "bad bullet",
    "reason": "r"}
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
        assert "Fact-Check Report" in capsys.readouterr().out

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
            {"original": "good bullet one",
            "tailored": "bad bullet one",
             "reason": "r1"},
            {"original": "good bullet two",
            "tailored": "bad bullet two",
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

    def test_revert_all_applies_to_remaining_edits(self, capsys):
        md = "## S\n- bad bullet one\n- bad bullet two\n- bad bullet three\n"
        violations = [
            {"original": f"good bullet {n}", "tailored": f"bad bullet {n}",
             "reason": "r"}
            for n in ("one", "two", "three")
        ]
        result = ValidationResult(passed=False, violations=violations)
        answers = iter(["n", "a"])
        out = report_and_maybe_revert(md, result, input_fn=lambda _: next(answers))
        assert "- bad bullet one" in out
        assert "- good bullet two" in out
        assert "- good bullet three" in out
        assert "Reverting all 2 remaining edit(s)" in capsys.readouterr().out

    def test_quit_keeps_remaining_edits(self, capsys):
        md = "## S\n- bad bullet one\n- bad bullet two\n"
        violations = [
            {"original": f"good bullet {n}", "tailored": f"bad bullet {n}",
             "reason": "r"}
            for n in ("one", "two")
        ]
        result = ValidationResult(passed=False, violations=violations)
        out = report_and_maybe_revert(md, result, input_fn=lambda _: "q")
        assert out == md
        assert "Keeping all remaining edits" in capsys.readouterr().out

    @pytest.mark.parametrize("prompts, expect_revert", [
        (["y"],  True),   # EOF after accepting first → first reverted, second not
        ([],     False),  # EOF on very first prompt → nothing reverted
    ])
    def test_eof_declines_the_revert(self, prompts, expect_revert):
        md = "## S\n- bad bullet one\n- bad bullet two\n"
        violations = [
            {"original": "good bullet one",
            "tailored": "bad bullet one",
             "reason": "r1"},
            {"original": "good bullet two",
            "tailored": "bad bullet two",
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
        assert "Please enter 'y', 'n', 'a', or 'q'" in capsys.readouterr().out

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
