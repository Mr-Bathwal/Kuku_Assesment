# tools/

Optional. Nothing here is needed to run CUTLIST, which is Python standard
library and has no dependencies.

These two regenerate `docs/SOLUTION.pdf` from `docs/SOLUTION.md`:

    pip install markdown
    npm install                  # playwright-core; needs Chrome installed

    python tools/mkpdf.py        # SOLUTION.md -> docs/_solution.html
    node tools/topdf.js          # _solution.html -> docs/SOLUTION.pdf

The print CSS lives in `mkpdf.py` rather than in a file of its own, because
it exists only to hold one document to two A4 pages, which is the brief's
limit. If the write-up grows, that stylesheet is the knob.

---

`uitest.js` is a browser smoke test for the prototype. The Python suite
cannot press a key, and the two bugs it caught were both things only a
keyboard finds - Escape had two listeners, so dismissing the shortcuts
panel silently threw you out of the desk; and `aspect-ratio` does nothing
on an inline element, so every tile on the cut sheet had collapsed.

    npm install
    node tools/uitest.js

It loads the page over `file://`, which is how a reviewer opens it, and
checks the build, every keyboard shortcut, the export, sideways scroll at
three widths, and reduced motion. 25 checks.
