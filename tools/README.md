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
