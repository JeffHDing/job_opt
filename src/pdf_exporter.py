import markdown
from weasyprint import HTML, CSS
import logging

# Suppress overly verbose WeasyPrint font warnings
logging.getLogger('weasyprint').setLevel(logging.ERROR)

def generate_resume_pdf(markdown_text: str, output_path: str):
    """
    Converts semantic markdown text into a geometrically absolute PDF.
    
    The intuition here is bridging two formats: Markdown organizes the logic 
    and structure (what is a header, what is a list), while WeasyPrint applies 
    the physical constraints (margins, font sizes) to make it ATS-friendly.
    """
    
    # 1. Translate Markdown to HTML
    raw_html = markdown.markdown(
        markdown_text, 
        extensions=['tables', 'sane_lists']
    )

    # 2. Define the CSS Injection
    resume_css = """
    @page {
        size: Letter;
        margin: 1in;
    }
    body {
        font-family: "Times New Roman", Times, serif;
        font-size: 10pt;
        color: #333333;
        line-height: 1.15;
    }
    h1 {
        font-size: 24pt;
        text-align: center;
        margin-bottom: 4px;
    }
    h2 {
        font-size: 12pt;
        border-bottom: 1px solid #cccccc;
        padding-bottom: 2px;
        margin-top: 10px;
        margin-bottom: 8px;
    }
    h3 {
        font-size: 10pt;
        margin-bottom: 2px;
    }
    p {
        margin-top: 0;
        margin-left: 0;
        margin-bottom: 8px;
    }
    ul {
        margin-top: 0;
        margin-left: 0;
        padding-left: 24px;
        margin-bottom: 8px;
    }
    li {
        margin-bottom: 4px;
    }
    """

    # 3. Wrap the HTML
    full_html = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head><style>{resume_css}</style></head>
    <body>{raw_html}</body>
    </html>
    """

    # 4. Compile the PDF
    HTML(string=full_html).write_pdf(
        output_path,
        stylesheets=[CSS(string=resume_css)]
    )
    print(f"Successfully compiled PDF: {output_path}")

if __name__ == "__main__":
    # A quick guiding step for testing the exporter in isolation
    with open("data/templates/Jeffrey_Ding_CV_Data_Science.md", "r", encoding="utf-8") as file:
        text = file.read()
    generate_resume_pdf(text, "data/tailored_outputs/test_outputs.pdf")
