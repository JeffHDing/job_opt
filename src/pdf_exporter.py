import logging

import markdown
from weasyprint import HTML

# Suppress overly verbose WeasyPrint font warnings
logging.getLogger('weasyprint').setLevel(logging.ERROR)

_RESUME_CSS = """
@page {
    size: Letter;
    margin: 0.5in 0.55in;
}
body {
    font-family: Arial, Helvetica, sans-serif;
    font-size: 10pt;
    color: #111111;
    line-height: 1.15;
}
h1 {
    font-size: 18pt;
    text-align: center;
    margin: 0 0 3px 0;
    padding: 0;
}
/* Contact line sits directly under the name */
h1 + p {
    text-align: center;
    margin: 0 0 6px 0;
    font-size: 10pt;
}
h2 {
    font-size: 11pt;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    border-bottom: 0.75pt solid #555555;
    padding-bottom: 1px;
    margin: 12px 0 4px 0;
    page-break-after: avoid;
}
h3 {
    font-size: 10pt;
    margin: 8px 0 1px 0;
    page-break-after: avoid;
}
/* Role/date lines rendered as italicised <p> after h3 */
h3 + p {
    margin: 0 0 2px 0;
    font-style: italic;
    font-size: 10pt;
}
p {
    margin: 0 0 4px 0;
}
ul {
    margin: 1px 0 4px 0;
    padding-left: 18px;
}
li {
    margin-bottom: 2px;
}
/* Keep each sub-section (role/project) on the same page when possible */
h3, li {
    page-break-inside: avoid;
}
a {
    color: #111111;
    text-decoration: none;
}
"""


def _build_html(markdown_text: str) -> str:
    raw_html = markdown.markdown(markdown_text, extensions=['tables', 'sane_lists'])
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
    one-page output should check the return value and trim accordingly.

    Markdown encodes structure (headings, lists); CSS encodes the physical
    constraints:
      - 0.5 in margins maximise usable area without crowding
      - 10 pt body keeps text readable while buying vertical space
      - page-break-inside: avoid keeps each role/project block intact
      - no floats, columns, or images — purely linear text flow
    """
    document = HTML(string=_build_html(markdown_text)).render()
    document.write_pdf(output_path)
    page_count = len(document.pages)
    print(f"PDF written → {output_path}  ({page_count} page{'s' if page_count != 1 else ''})")
    return page_count
