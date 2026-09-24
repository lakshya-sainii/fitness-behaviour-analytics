"""Export the executed notebook to self-contained HTML and print-ready PDF."""

from pathlib import Path
import nbformat
from nbconvert import HTMLExporter

PRINT_CSS = """
@page { size: A4 landscape; margin: 15mm 13mm 16mm;
 @bottom-left { content: "Bellabeat | Fitbit analytics | 2016 observational sample"; font-size: 8pt; color: #53616e; }
 @bottom-right { content: counter(page); font-size: 8pt; color: #53616e; }
}
body { font-family: DejaVu Sans, sans-serif; font-size: 9pt; color: #172b3a; background: white; }
.jp-Notebook { padding: 0 !important; }
.jp-Cell { padding: 0 !important; margin: 0 0 8px !important; overflow: visible !important; }
.jp-InputPrompt, .jp-OutputPrompt { display: none !important; }
.jp-Cell-inputWrapper, .jp-Cell-outputWrapper, .jp-OutputArea-child { display: block !important; }
.jp-InputArea-editor { border: 0 !important; background: #f2f5f7 !important; }
.jp-RenderedHTMLCommon { font-size: 9pt; line-height: 1.4; }
h1 { font-size: 23pt; color: #0072b2; } h2 { font-size: 17pt; color: #0072b2; }
h3 { font-size: 12pt; } h1,h2,h3 { break-after: avoid; }
pre, code { font-family: DejaVu Sans Mono, monospace; font-size: 7pt !important; white-space: pre-wrap !important; overflow-wrap: anywhere; }
pre { padding: 7px; max-height: none !important; overflow: visible !important; }
table { width: 100% !important; table-layout: auto; font-size: 7pt !important; border-collapse: collapse; }
th, td { padding: 4px !important; overflow-wrap: anywhere; word-break: normal; border-bottom: 1px solid #dce3e8; }
th { background: #e7f1f6; text-align: left; }
tr { break-inside: avoid; } thead { display: table-header-group; }
.jp-RenderedImage { break-inside: avoid; }
.jp-RenderedImage img { max-width: 100% !important; max-height: 154mm !important; width: auto !important; height: auto !important; display: block; margin: auto; }
.jp-OutputArea-output, .jp-RenderedHTMLCommon, .jp-RenderedText { overflow: visible !important; max-height: none !important; }
a { color: #0072b2; text-decoration: none; }
"""


def export_notebook(base: Path) -> bool:
    """Keep the HTML even if optional system PDF dependencies are unavailable."""
    notebook = nbformat.read(base / "Bellabeat_Fitbit_EDA.ipynb", as_version=4)
    body, _ = HTMLExporter(template_name="lab").from_notebook_node(notebook)
    body = body.replace("</head>", "<style>" + PRINT_CSS + "</style></head>")
    html_path = base / "Bellabeat_Fitbit_EDA.html"
    html_path.write_text(body, encoding="utf-8")
    try:
        from weasyprint import HTML

        HTML(string=body, base_url=str(base)).write_pdf(
            base / "Bellabeat_Fitbit_EDA.pdf"
        )
    except (ImportError, OSError) as exc:
        print(f"PDF export unavailable: {exc}; the self-contained HTML is retained.")
        return False
    return True


if __name__ == "__main__":
    export_notebook(Path(__file__).resolve().parent)
