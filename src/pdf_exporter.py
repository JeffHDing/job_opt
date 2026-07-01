import markdown
from weasyprint import HTML, CSS
import logging

# Suppress overly verbose WeasyPrint font warnings
logging.getLogger('weasyprint').setLevel(logging.ERROR)

def generate_resume_pdf(markdown_text: str, output_path: str):
    """
    Converts semantic markdown text into a single-page, ATS-friendly PDF.

    Markdown encodes structure (headings, lists); CSS encodes the physical
    constraints that guarantee one-page fit and clean ATS parsing:
      - 0.5 in margins maximise usable area without crowding
      - 9.5 pt body keeps text readable while buying vertical space
      - page-break-inside: avoid keeps each role/project block intact
      - no floats, columns, or images — purely linear text flow
    """

    # 1. Translate Markdown → HTML
    raw_html = markdown.markdown(
        markdown_text,
        extensions=['tables', 'sane_lists']
    )

    # 2. CSS: tight but readable, one-page Letter
    resume_css = """
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
        font-size: 12pt;
    }
    h2 {
        font-size: 12pt;
        text-transform: uppercase;
        letter-spacing: 0.05em;
        border-bottom: 0.75pt solid #555555;
        padding-bottom: 1px;
        margin: 12px 0 4px 0;
        page-break-after: avoid;
    }
    h3 {
        font-size: 11pt;
        margin: 8px 0 1px 0;
        page-break-after: avoid;
    }
    /* Role/date lines rendered as italicised <p> after h3 */
    h3 + p {
        margin: 0 0 2px 0;
        font-style: italic;
        font-size: 10.5pt;
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

    # 3. Wrap in a minimal HTML shell
    full_html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <style>{resume_css}</style>
</head>
<body>{raw_html}</body>
</html>"""

    # 4. Render PDF — CSS already embedded in <style>; no second stylesheet needed
    HTML(string=full_html).write_pdf(output_path)
    print(f"PDF written → {output_path}")

