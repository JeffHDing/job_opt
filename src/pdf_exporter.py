import logging
import re

import markdown
from weasyprint import HTML

# Suppress overly verbose WeasyPrint font warnings
logging.getLogger('weasyprint').setLevel(logging.ERROR)

_RESUME_CSS = """
@font-face {
    font-family: "Times New Roman";
    src: local("Times New Roman"), local("TimesNewRomanPSMT");
}
@page {
    size: Letter;
    margin: 0.5in 0.6in;
}
body {
    font-family: "Times New Roman", Times, "Liberation Serif", serif;
    font-size: 12pt;
    color: #000000;
    line-height: 1.15;
}
h1 {
    font-family: "Times New Roman", Times, "Liberation Serif", serif;
    font-size: 18pt;
    font-weight: bold;
    text-align: center;
    margin: 0 0 2px 0;
    padding: 0;
}
/* Role title under the name — italic, like the academic CV */
h1 + p {
    text-align: center;
    margin: 0 0 2px 0;
    font-size: 12pt;
    font-style: italic;
    font-weight: normal;
}
h1 + p strong {
    font-style: italic;
    font-weight: normal;
}
/* Contact line is the second <p> after h1 */
h1 + p + p {
    text-align: center;
    margin: 0 0 8px 0;
    font-size: 12pt;
    font-style: normal;
    font-weight: normal;
}
h1 + p + p a {
    color: #0563C1;
}
h2 {
    font-size: 12pt;
    font-weight: bold;
    text-transform: uppercase;
    letter-spacing: 0.12em;
    border-bottom: 1pt solid #000000;
    padding-bottom: 1px;
    margin: 12px 0 6px 0;
    page-break-after: avoid;
}
h3 {
    font-size: 12pt;
    font-weight: bold;
    margin: 8px 0 1px 0;
    page-break-after: avoid;
}
.entry-header {
    display: flex;
    justify-content: space-between;
    align-items: baseline;
    gap: 12px;
    margin: 8px 0 0 0;
    page-break-after: avoid;
    page-break-inside: avoid;
}
.entry-header h3 {
    margin: 0;
    flex: 1 1 auto;
}
.entry-header .dates {
    font-size: 12pt;
    font-weight: bold;
    font-style: normal;
    white-space: nowrap;
    flex: 0 0 auto;
}
.entry-sub {
    display: flex;
    justify-content: space-between;
    align-items: baseline;
    gap: 12px;
    margin: 0 0 2px 0;
    font-style: normal;
    font-size: 12pt;
    page-break-after: avoid;
}
.entry-sub.has-loc,
.entry-sub.has-loc .loc {
    font-style: italic;
}
.entry-sub .org {
    flex: 1 1 auto;
}
.entry-sub .loc {
    flex: 0 0 auto;
    white-space: nowrap;
    font-style: italic;
}
/* Role/date lines rendered as italicised <p> after h3 (unparsed entries) */
h3 + p {
    margin: 0 0 2px 0;
    font-style: italic;
    font-size: 12pt;
}
p {
    margin: 0 0 4px 0;
}
ul {
    margin: 1px 0 4px 0;
    padding-left: 18px;
}
li {
    margin-bottom: 3px;
}
ul.skills {
    list-style: none;
    padding-left: 0;
}
ul.skills li {
    margin-bottom: 2px;
    padding-left: 0;
}
strong {
    font-weight: bold;
}
/* Keep each sub-section (role/project) on the same page when possible */
h3, li {
    page-break-inside: avoid;
}
a {
    color: #000000;
    text-decoration: none;
}
u {
    text-decoration: none;
}
"""

_MONTH = (
    r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?"
)
_DATE_RANGE_RE = re.compile(
    rf"^(?:{_MONTH}\s+\d{{4}}|\d{{4}})\s*[-–—]\s*"
    rf"(?:{_MONTH}\s+\d{{4}}|\d{{4}}|Present|Current)$",
    re.IGNORECASE,
)
_H3_ENTRY_RE = re.compile(
    r"<h3>(.*?)</h3>\s*<p>(.*?)</p>",
    re.DOTALL | re.IGNORECASE,
)


def _plain(html_fragment: str) -> str:
    return re.sub(r"<[^>]+>", "", html_fragment).strip()


def _format_entries(raw_html: str) -> str:
    """
    Lift trailing date ranges onto the h3 line (right-aligned) and, when the
    subtitle is `org | location | date`, put the location on the right too —
    the layout the academic CV uses.
    """

    def repl(match: re.Match) -> str:
        title, body = match.group(1), match.group(2)
        parts = [part.strip() for part in re.split(r"\s*\|\s*", body)]
        if len(parts) < 2 or not _DATE_RANGE_RE.fullmatch(_plain(parts[-1])):
            return match.group(0)

        date = _plain(parts[-1])
        rest = parts[:-1]
        header = (
            f'<div class="entry-header"><h3>{title}</h3>'
            f'<span class="dates">{date}</span></div>'
        )
        if (
            len(rest) == 2
            and "GPA" not in _plain(rest[1]).upper()
        ):
            org, loc = rest
            sub = (
                f'<div class="entry-sub has-loc"><span class="org">{org}</span>'
                f'<span class="loc">{_plain(loc)}</span></div>'
            )
        else:
            sub = (
                f'<div class="entry-sub"><span class="org">'
                f'{" | ".join(rest)}</span></div>'
            )
        return header + sub

    return _H3_ENTRY_RE.sub(repl, raw_html)


def _style_skill_lists(raw_html: str) -> str:
    return re.sub(
        r"(<h2>[^<]*Skills[^<]*</h2>\s*)<ul>",
        r'\1<ul class="skills">',
        raw_html,
        count=1,
        flags=re.IGNORECASE,
    )


def _build_html(markdown_text: str) -> str:
    raw_html = markdown.markdown(markdown_text, extensions=['tables', 'sane_lists'])
    raw_html = _format_entries(raw_html)
    raw_html = _style_skill_lists(raw_html)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <style>{_RESUME_CSS}</style>
</head>
<body>{raw_html}</body>
</html>"""


def get_page_count(markdown_text: str) -> int:
    """Render markdown in-memory and return the number of PDF pages."""
    document = HTML(string=_build_html(markdown_text)).render()
    return len(document.pages)


def generate_resume_pdf(markdown_text: str, output_path: str) -> int:
    """
    Converts semantic markdown text into an ATS-friendly PDF.

    Returns the number of pages rendered. Callers that need to guarantee
    a page limit should check the return value and trim accordingly.

    Markdown encodes structure (headings, lists); CSS encodes the physical
    constraints:
      - 0.5 in vertical / 0.6 in horizontal margins
      - 12 pt Times New Roman body, matching a conventional academic CV
      - dates and locations are right-aligned on entry header rows
      - page-break-inside: avoid keeps each role/project block intact
      - no floats, columns, or images — purely linear text flow
    """
    document = HTML(string=_build_html(markdown_text)).render()
    document.write_pdf(output_path)
    page_count = len(document.pages)
    suffix = "s" if page_count != 1 else ""
    print(f"PDF written → {output_path}  ({page_count} page{suffix})")
    return page_count
