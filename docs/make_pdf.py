"""DOCUMENTATION.md → Техническая_документация.pdf (A4, обложка, номера страниц);
с --brief — BRIEF.md → Краткое_описание.pdf (компактная вёрстка, без обложки и разрывов страниц).

    uv run --no-project --with markdown --with websockets python docs/make_pdf.py
    uv run --no-project --with markdown --with websockets python docs/make_pdf.py --brief

Нужен установленный Chrome или Edge (печать через DevTools Protocol, docs/cdp.py). В конвейере не используется.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import re
import tempfile
from pathlib import Path

import markdown
from markdown.extensions.toc import slugify_unicode

from cdp import Browser

ROOT = Path(__file__).resolve().parents[1]
DOCS = {
    "full": (ROOT / "DOCUMENTATION.md", ROOT / "Техническая_документация.pdf", "LinQ Safety · техническая документация"),
    "brief": (ROOT / "BRIEF.md", ROOT / "Краткое_описание.pdf", "LinQ Safety · краткое описание"),
}

CSS = """
@page { size: A4; }
:root { --ink: #17212f; --text: #2f3a48; --muted: #6b7686; --line: #dfe4ea; --soft: #f5f7fa; --blue: #2f64d6; }
* { box-sizing: border-box; }
html { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
body { margin: 0; color: var(--text); background: #fff;
  font: 9.6pt/1.55 'Golos Text', 'Segoe UI', Arial, sans-serif; }
h1, h2, h3, h4 { color: var(--ink); line-height: 1.25; font-weight: 600; }
h2 { break-before: page; font-size: 20pt; margin: 0 0 14pt; padding-bottom: 8pt; border-bottom: 2.5pt solid var(--ink); }
h3 { font-size: 12.5pt; margin: 18pt 0 6pt; break-after: avoid; }
h4 { font-size: 10.5pt; margin: 12pt 0 4pt; break-after: avoid; }
p { margin: 0 0 7pt; }
ul, ol { margin: 0 0 8pt; padding-left: 16pt; }
li { margin: 0 0 3pt; }
a { color: var(--blue); text-decoration: none; }
strong { color: var(--ink); font-weight: 600; }
code { font: 8.2pt 'JetBrains Mono', Consolas, monospace; background: #eef1f5; border-radius: 3pt; padding: 0.5pt 3pt; color: #243041; }
pre { background: var(--soft); border: 0.6pt solid var(--line); border-radius: 5pt; padding: 8pt 10pt; margin: 0 0 10pt;
  white-space: pre-wrap; word-break: break-word; break-inside: avoid; font-size: 7pt; line-height: 1.38; }
pre code { background: none; padding: 0; font-size: 7pt; line-height: 1.38; color: #243041;
  /* в моноширинном шрифте должны быть и кириллица, и псевдографика — иначе схемы и дерево разъезжаются */
  font-family: Consolas, 'DejaVu Sans Mono', 'Courier New', monospace; font-variant-ligatures: none; }
table { width: 100%; border-collapse: collapse; margin: 2pt 0 12pt; font-size: 8.4pt; line-height: 1.42; }
th { text-align: left; font-weight: 600; color: var(--ink); background: var(--soft); border-bottom: 1pt solid #c9d1db; padding: 5pt 6pt; }
td { border-bottom: 0.6pt solid var(--line); padding: 4.5pt 6pt; vertical-align: top; }
tr { break-inside: avoid; }
td code, th code { font-size: 7.6pt; }
img { display: block; max-width: 100%; margin: 4pt auto 12pt; break-inside: avoid; }
img[src*="/img/ui_"] { border: 0.6pt solid var(--line); border-radius: 4pt; max-height: 205mm; width: auto; }
img[src*="diagrams/"] { border: 0.6pt solid var(--line); border-radius: 4pt; }
p:has(> img) { break-inside: avoid; }

.cover { break-after: page; height: 252mm; display: flex; flex-direction: column; }
.cover .logo { width: 46pt; height: 46pt; border-radius: 11pt; margin: 40pt 0 120pt;
  background: linear-gradient(135deg, #2f64d6 0 50%, #e0492f 50% 100%); }
.cover .kicker { letter-spacing: 2.4pt; font-size: 8.5pt; color: var(--muted); text-transform: uppercase; margin-bottom: 18pt; }
.cover h1 { font-size: 40pt; margin: 0 0 12pt; letter-spacing: -0.5pt; }
.cover h1 + p { font-size: 15pt; color: var(--ink); margin-bottom: 18pt; }
.cover h1 + p strong { font-weight: 400; }
.cover h1 + p + p { font-size: 11pt; color: var(--muted); max-width: 120mm; }
.cover table { margin-top: auto; font-size: 8.6pt; }
.cover table thead { display: none; }
.cover td:first-child { color: var(--muted); width: 34%; }
.toc ol { padding-left: 20pt; margin: 0; }
.toc li { border-bottom: 0.6pt solid var(--line); padding: 6pt 0; margin: 0; font-weight: 600; font-size: 10.5pt; }
.toc li a { color: var(--ink); }
.toc li::marker { color: var(--blue); }

/* краткое описание: шапка вместо обложки, главы идут подряд */
.brief { font-size: 9.4pt; line-height: 1.5; }
.brief h2 { break-before: auto; break-after: avoid; font-size: 14pt; margin: 14pt 0 7pt; padding-bottom: 5pt; border-bottom-width: 1.8pt; }
.brief p:has(> img) { margin: 0; }
.brief img { margin: 2pt auto 8pt; }
.brief img[src*="diagrams/"] { width: 88%; }
.brief img[src*="07-stek"] { width: 100%; }
.brief .cover { break-after: auto; height: auto; display: block; margin-bottom: 4pt; }
.brief .cover .logo { width: 26pt; height: 26pt; border-radius: 7pt; margin: 0 0 12pt; }
.brief .cover .kicker { margin-bottom: 8pt; }
.brief .cover h1 { font-size: 28pt; margin: 0 0 4pt; }
.brief .cover h1 + p { font-size: 13pt; margin-bottom: 4pt; }
.brief .cover h1 + p + p { font-size: 10pt; max-width: none; margin-bottom: 12pt; }
.brief .cover table { margin: 0; table-layout: fixed; }
.brief .cover thead { display: table-header-group; }
.brief .cover th { background: none; border-bottom: none; font-size: 21pt; font-weight: 700; color: var(--ink); padding: 8pt 8pt 0 0; }
.brief .cover td { border-bottom: 2pt solid var(--blue); color: var(--muted); font-size: 8.4pt; padding: 2pt 10pt 8pt 0; width: auto; }
.brief .cover td:first-child { width: auto; }
.brief .pair { display: flex; gap: 3%; margin: 2pt 0 8pt; }
.brief .pair img { width: 48.5%; max-height: none; margin: 0; }
"""


def build_html(src: Path, brief: bool) -> str:
    text = src.read_text(encoding="utf-8")
    body = markdown.markdown(text, extensions=["tables", "fenced_code", "sane_lists", "toc"],
                             extension_configs={"toc": {"slugify": slugify_unicode}})
    head, _, rest = body.partition("<h2")
    rest = "<h2" + rest
    # оглавление — отдельная страница со своим оформлением
    rest = re.sub(r'(<h2 id="[^"]*">Оглавление</h2>\s*<ol>.*?</ol>)', r'<section class="toc">\1</section>',
                  rest, count=1, flags=re.S)
    cover = (f'<section class="cover"><div class="logo"></div>'
             f'<div class="kicker">Хакатон «Открой Моспром» · кейс LinQ</div>{head}</section>')
    fonts = ("https://fonts.googleapis.com/css2?family=Golos+Text:wght@400;600&family=JetBrains+Mono:wght@400&display=swap")
    return (f'<!doctype html><html lang="ru"><head><meta charset="utf-8"><base href="{ROOT.as_uri()}/">'
            f'<title>LinQ Safety — техническая документация</title><link rel="stylesheet" href="{fonts}">'
            f'<style>{CSS}</style></head><body class="{"brief" if brief else "full"}">{cover}{rest}</body></html>')


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--brief", action="store_true", help="краткое описание BRIEF.md вместо полной документации")
    args = ap.parse_args()
    src, out, footer_text = DOCS["brief" if args.brief else "full"]
    html = build_html(src, args.brief)
    with tempfile.TemporaryDirectory() as tmp:
        page_file = Path(tmp) / "doc.html"
        page_file.write_text(html, encoding="utf-8")
        async with Browser(os.getenv("CHROME")) as browser:
            page = await browser.page(1240, 1754)
            await page.goto(page_file.as_uri(), 1.0)
            for _ in range(120):
                ready = await page.eval("document.readyState === 'complete' && [...document.images].every(i => i.complete)")
                if ready:
                    break
                await asyncio.sleep(0.5)
            await page.eval("document.fonts.ready.then(() => true)")
            footer = (f'<div style="width:100%;font:7.5pt \'Segoe UI\',Arial,sans-serif;color:#7d8796;padding:0 18mm;'
                      f'display:flex;justify-content:space-between"><span>{footer_text}</span>'
                      f'<span class="pageNumber"></span></div>')
            await page.pdf(out, paperWidth=8.27, paperHeight=11.69, marginTop=0.72, marginBottom=0.78,
                           marginLeft=0.71, marginRight=0.71, printBackground=True, displayHeaderFooter=True,
                           headerTemplate="<div></div>", footerTemplate=footer)
    print(out)


if __name__ == "__main__":
    asyncio.run(main())
