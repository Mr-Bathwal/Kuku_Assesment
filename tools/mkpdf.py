"""
docs/SOLUTION.md -> docs/_solution.html -> docs/SOLUTION.pdf

    python tools/mkpdf.py && node tools/topdf.js

Optional, and the only part of this repo with dependencies (`markdown` for
this step, `playwright-core` plus an installed Chrome for the next). CUTLIST
itself is standard library.

The print CSS lives here rather than in a separate file because it exists
only to make one document fit on two A4 pages, which is the brief's limit.
If the write-up grows, this is the knob.
"""

from __future__ import annotations

import pathlib
import sys

try:
    import markdown
except ImportError:                                   # pragma: no cover
    sys.exit("pip install markdown")

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC = ROOT / "docs" / "SOLUTION.md"
OUT = ROOT / "docs" / "_solution.html"

CSS = """
@page { size: A4; margin: 13mm 14mm; }
* { box-sizing: border-box; }
body { font-family:"Segoe UI",Calibri,sans-serif; font-size:8.4pt; line-height:1.42; color:#14161a; margin:0; }
h1 { font-size:16pt; margin:0 0 2pt; font-weight:600; letter-spacing:-.3pt; }
h1 + p { color:#4f4a43; margin:0 0 7pt; }
h2 { font-size:10pt; margin:9pt 0 3pt; font-weight:600; color:#0b1220;
     border-bottom:.6pt solid #c9c4b8; padding-bottom:1.5pt; }
p, li { margin:0 0 3.5pt; }
ul { margin:0 0 4pt; padding-left:13pt; }
li { margin-bottom:2.5pt; }
code { font-family:Consolas,monospace; font-size:7.6pt; background:#efece4; padding:0 2px; }
strong { font-weight:600; }
table { border-collapse:collapse; width:100%; margin:4pt 0 6pt; font-size:7.9pt; }
th { text-align:left; border-bottom:.8pt solid #14161a; padding:2.5pt 5pt 2.5pt 0; font-weight:600; }
td { border-bottom:.4pt solid #ddd8cc; padding:2.5pt 5pt 2.5pt 0; }
td:not(:first-child), th:not(:first-child) { text-align:right; font-family:Consolas,monospace; }
hr { border:0; border-top:.5pt solid #c9c4b8; margin:6pt 0 4pt; }
hr + p { font-size:6.9pt; color:#6a655c; line-height:1.3; }
a { color:#14161a; text-decoration:none; }
"""


def main() -> int:
    body = markdown.markdown(
        SRC.read_text(encoding="utf-8"),
        extensions=["tables", "sane_lists"],
    )
    OUT.write_text(
        "<!doctype html><html><head><meta charset='utf-8'><style>"
        + CSS.strip()
        + "</style></head><body>"
        + body
        + "</body></html>",
        encoding="utf-8",
    )
    print(f"wrote {OUT.relative_to(ROOT)}  ({len(body):,} chars of html)")
    print("now run: node tools/topdf.js")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
