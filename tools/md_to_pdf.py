"""Markdown to PDF converter.

Converts Markdown -> HTML -> PDF using headless Chromium via Playwright.

Usage:
  python tools/md_to_pdf.py docs/project_report.md docs/project_report.pdf

Notes:
- Requires: markdown, playwright
- First-time Playwright setup also requires: python -m playwright install chromium
"""

from __future__ import annotations

import argparse
from pathlib import Path

import markdown as md
from playwright.sync_api import sync_playwright


_HTML_TEMPLATE = """<!doctype html>
<html lang=\"en\">
<head>
  <meta charset=\"utf-8\" />
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
  <title>{title}</title>
  <style>
    @page {{ size: A4; margin: 18mm 16mm; }}
    html, body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Arial, sans-serif; font-size: 11pt; line-height: 1.45; color: #111; }}
    h1, h2, h3, h4 {{ line-height: 1.15; margin: 1.1em 0 0.4em; }}
    h1 {{ font-size: 22pt; }}
    h2 {{ font-size: 16pt; border-bottom: 1px solid #ddd; padding-bottom: 4px; }}
    h3 {{ font-size: 13pt; }}
    p {{ margin: 0.55em 0; }}
    blockquote {{ margin: 0.8em 0; padding: 0.2em 0.9em; border-left: 3px solid #ddd; color: #333; }}
    code, pre {{ font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, 'Liberation Mono', monospace; }}
    code {{ background: #f5f5f5; padding: 0.1em 0.25em; border-radius: 3px; }}
    pre {{ background: #f5f5f5; padding: 10px 12px; overflow-x: auto; border-radius: 6px; }}
    pre code {{ background: transparent; padding: 0; }}
    ul, ol {{ margin: 0.5em 0 0.5em 1.3em; }}
    li {{ margin: 0.25em 0; }}
    table {{ border-collapse: collapse; width: 100%; margin: 0.9em 0; }}
    th, td {{ border: 1px solid #ddd; padding: 6px 8px; vertical-align: top; }}
    th {{ background: #f3f3f3; }}
    hr {{ border: 0; border-top: 1px solid #ddd; margin: 1.2em 0; }}
    a {{ color: inherit; text-decoration: none; }}
  </style>
</head>
<body>
{body}
</body>
</html>
"""


def convert_markdown_to_html(markdown_text: str, title: str) -> str:
    body = md.markdown(
        markdown_text,
        extensions=[
            "fenced_code",
            "tables",
            "toc",
            "sane_lists",
        ],
        output_format="html5",
    )
    return _HTML_TEMPLATE.format(title=title, body=body)


def render_pdf_from_html(html: str, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.set_content(html, wait_until="networkidle")
        page.emulate_media(media="screen")
        page.pdf(
            path=str(output_path),
            format="A4",
            print_background=True,
            display_header_footer=False,
        )
        browser.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Convert Markdown to PDF via Playwright.")
    parser.add_argument("input_md", type=Path, help="Input Markdown file")
    parser.add_argument("output_pdf", type=Path, help="Output PDF file")
    args = parser.parse_args()

    markdown_text = args.input_md.read_text(encoding="utf-8")
    title = args.input_md.stem
    html = convert_markdown_to_html(markdown_text, title=title)
    render_pdf_from_html(html, args.output_pdf)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
