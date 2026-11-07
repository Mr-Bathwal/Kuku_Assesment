# tools/

Optional. Nothing here is needed to run CUTLIST, which is Python standard
library and has no dependencies.

## The write-up

    pip install markdown
    npm install                  # playwright-core; needs Chrome installed

    python tools/mkdoc.py        # SOLUTION.md + evaluation.json -> _solution.html
    node tools/topdf.js          # _solution.html -> docs/SOLUTION.pdf

The prose lives in `docs/SOLUTION.md` and that is the only source for it.
`mkdoc.py` holds the layout and draws every figure from `out/evaluation.json`
and `out/promos.json` at build time, so the document cannot quote a number
the last run did not produce — the same rule the prototype follows. Re-run
the pipeline, rebuild, and the charts move with it.

The brief caps the write-up at two A4 pages, and the layout is built to that
rather than flowing and happening to land there. `TYPE_PT` in `mkdoc.py` is
the knob if the prose grows. After changing it, check the page count:

    python -c "import re,pathlib; print(len(re.findall(rb'/Type\s*/Page[^s]', pathlib.Path('docs/SOLUTION.pdf').read_bytes())))"

## The prototype

    node tools/uitest.js                     # the local file
    node tools/uitest.js https://host/path/  # the deployed site

A browser smoke test. The Python suite cannot press a key, and the two bugs
this one caught were both things only a keyboard finds: Escape had two
listeners, so dismissing the shortcuts panel silently threw you out of the
review desk; and `aspect-ratio` does nothing on an inline element, so every
tile on the cut sheet had collapsed to a sliver. It checks the build, every
shortcut, the JSON export, sideways scroll at three widths, and reduced
motion. 25 checks.
