"""
Unit tests for audit.py — parsing the ATS auditor's Markdown report.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from audit import (  # noqa: E402
    TARGET_SCORE,
    AuditReport,
    find_placeholders,
    parse_audit_report,
    parse_directives,
)

_FULL_REPORT = """## 1. ATS Score

| Dimension | Score | Justification |
|---|---|---|
| Hard skills & tools | 18/30 | Missing "Snowflake" and "dbt". |

**Overall ATS score: 62/100**

**Verdict:** Clears a loose screen but not a competitive one.

## 2. Keyword Match

| JD term (exact string) | Present? | Where |
|---|---|---|
| SQL | Yes | Technical Skills |

## 3. Gap Analysis

- `Closeable from the master resume:` A/B testing sits in Tools & Frameworks.
- `Unclosable without new experience:` No Snowflake anywhere.

## 4. Tailoring Directives

1. [Technical Skills] Move "SQL" to the front of the Programming row.
   — lifts: Hard skills & tools
2. [Experience / Data Manager] Promote the causal inference bullet to the top.
3. [Projects] Drop the NYC collision project. — lifts: Core responsibility

## 5. Quantification Requests

- `Original:` Managed the simultaneous conduct of 15+ clinical trials.
- `Rewrite:` Managed [N] clinical trials, cutting activation time by [X]%.

## 6. Projected Score

**Projected ATS score after tailoring: 88/100**

**Reachable:** `No` — Snowflake and dbt are genuinely absent.
"""


class TestParseAuditReport:
    def test_parses_both_scores(self):
        report = parse_audit_report(_FULL_REPORT)
        assert report.current_score == 62
        assert report.projected_score == 88

    def test_parses_reachable_verdict(self):
        assert parse_audit_report(_FULL_REPORT).reachable is False

    def test_keeps_raw_markdown(self):
        assert parse_audit_report(_FULL_REPORT).markdown == _FULL_REPORT

    def test_missing_scores_are_none(self):
        report = parse_audit_report("## 1. ATS Score\n\nNo numbers here.\n")
        assert report.current_score is None
        assert report.projected_score is None
        assert report.reachable is None

    def test_out_of_range_score_is_rejected(self):
        report = parse_audit_report("**Overall ATS score: 620/100**")
        assert report.current_score is None

    @pytest.mark.parametrize("verdict, expected", [
        ("**Reachable:** `Yes`", True),
        ("**Reachable:** yes, easily", True),
        ("**Reachable:** `No`", False),
    ])
    def test_reachable_accepts_formatting_variants(self, verdict, expected):
        assert parse_audit_report(verdict).reachable is expected


class TestParseDirectives:
    def test_extracts_numbered_directives(self):
        directives = parse_directives(_FULL_REPORT)
        assert len(directives) == 3
        assert directives[0].startswith('[Technical Skills] Move "SQL"')
        assert directives[2].startswith("[Projects] Drop")

    def test_folds_continuation_lines_into_their_directive(self):
        assert "— lifts: Hard skills & tools" in parse_directives(_FULL_REPORT)[0]

    def test_stops_at_the_next_section(self):
        assert not any("Quantification" in d for d in parse_directives(_FULL_REPORT))
        assert not any("Rewrite" in d for d in parse_directives(_FULL_REPORT))

    def test_returns_empty_when_section_absent(self):
        assert parse_directives("## 1. ATS Score\n\n1. Not a directive.\n") == []


class TestAuditReportSummary:
    def test_skipped_report(self):
        summary = AuditReport(markdown="", skipped=True, skip_reason="503").summary()
        assert summary.startswith("⚠")
        assert "503" in summary

    def test_reports_scores_and_directive_count(self):
        summary = parse_audit_report(_FULL_REPORT).summary()
        assert "62/100" in summary
        assert "88/100" in summary
        assert "3 tailoring directive(s)" in summary

    def test_flags_unreachable_target(self):
        assert "NOT reachable" in parse_audit_report(_FULL_REPORT).summary()

    def test_flags_reachable_target(self):
        report = AuditReport(markdown="", current_score=70, projected_score=93)
        assert f"{TARGET_SCORE}%+ reachable" in report.summary()

    def test_warns_when_score_unparseable(self):
        assert "Could not parse" in AuditReport(markdown="junk").summary()


class TestTargetReachable:
    def test_prefers_explicit_verdict_over_projection(self):
        report = AuditReport(markdown="", projected_score=95, reachable=False)
        assert report.target_reachable is False

    def test_falls_back_to_projected_score(self):
        assert AuditReport(markdown="", projected_score=91).target_reachable is True
        assert AuditReport(markdown="", projected_score=80).target_reachable is False

    def test_unknown_when_nothing_to_go_on(self):
        assert AuditReport(markdown="").target_reachable is None


class TestFindPlaceholders:
    def test_finds_bracketed_placeholders(self):
        found = find_placeholders("Cut latency by [X]% across [N] pipelines.")
        assert found == ["[X]", "[N]"]

    def test_ignores_markdown_links(self):
        md = "[<u>LinkedIn</u>](https://example.com) | [GitHub](https://example.com)"
        assert find_placeholders(md) == []

    def test_clean_resume_has_none(self):
        assert find_placeholders("- Built a pipeline in Python.") == []
