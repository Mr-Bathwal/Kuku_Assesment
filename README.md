# CUTLIST

**Promo cut sheets for microdrama, straight from the screenplay.**

Reads a show's screenplays and returns a ranked list of 20–60 second promo
clips — the right moments, and the exact frames to cut on — with the hook,
the cliffhanger, a reason, and an EDL an editor can drop into Premiere.

Kuku AI Generalist assignment, **Problem 1**. Run on the supplied input
pack: *I Married a Broken Soldier. He was a Duke*, 50 episodes.

```
50 episodes · 3,727 timed beats · 102.7 minutes of screenplay
    ↓  1.6 seconds, no API key, no pip install
156 verified promo candidates · 20 exported with EDLs
```

---

## Run it

Python 3.10+. **No dependencies** — standard library only.

```bash
# the supplied input pack (not in this repo - see Confidentiality below)
python -m cutlist run data/scripts --show "I Married a Broken Soldier"
python -m cutlist eval data/scripts          # the quality numbers

# a different show entirely, three episodes, included here and runnable now
python -m cutlist run data/sample --out out-sample --show "The Last Shift" --top 6 --no-web

python -m unittest discover tests            # 44 tests
open web/index.html                          # the prototype
```

`web/index.html` opens straight off the filesystem - no server, no build
step. The pipeline writes the page's data as a JS global as well as JSON,
because browsers block `fetch()` over `file://` and a reviewer should be
able to double-click a file.

Everything works with no API key: the rules alone produce the full ranked
cut list. To add the model review pass, set three variables:

```bash
# any OpenAI-compatible endpoint — OpenAI, Groq, Together, OpenRouter, Ollama
export CUTLIST_PROVIDER=chat
export CUTLIST_BASE_URL=https://api.groq.com/openai/v1
export CUTLIST_MODEL=llama-3.3-70b-versatile
export CUTLIST_API_KEY=...

# or
export CUTLIST_PROVIDER=anthropic   CUTLIST_MODEL=claude-sonnet-5
export CUTLIST_PROVIDER=gemini      CUTLIST_MODEL=gemini-2.0-flash
```

The model is one environment variable. Nothing else changes.

---

## What it produces

| File | For |
|---|---|
| `out/promos.json` | everything, structured |
| `out/cutlist.csv` | the sheet a marketing lead schedules a week of posts from |
| `out/cutsheet.md` | human-readable, one promo per section |
| `out/edl/P001.edl` … | CMX3600 edit decision lists — import straight into Premiere / Resolve / Avid |
| `out/evaluation.json` | the quality measurements |
| `web/index.html` | the prototype: the scroll film, then the review desk |

---

## The page

`web/index.html` is two things in one file, and `Esc` moves between them.

**The film** presents the corpus and the argument: an SMPTE leader, the
spend that makes promo selection worth automating, all fifty episodes as a
scroll-driven 35mm reel, the pipeline, and the grounding wall - 61,612
cells, one per expressible timestamp, with the 3,419 real beat starts lit.

**The desk** is the actual tool: a keyboard-driven review queue. `Enter`
approves, `R` rejects, `J/K/L` scrubs, `I/O` nudge an in- or out-point by
exactly one beat boundary, `E` exports the decisions as JSON.

Two rules hold the page together. **Every number, curve and lit cell is
read from the run** - the same `promos.json` that sits beside the EDLs - so
the page cannot say something the pipeline did not. And **there is no stock
imagery and no fabricated stills**: there is no video of this show, so the
frames are the episodes' own pressure curves, the perforations are drawn
from SMPTE ST 139 Table 1, and the leader keeps SMPTE RP 428-6 timing.

No framework, no build step, no runtime dependency - about 3,400 lines of plain
HTML, CSS and JavaScript. Measured at 1600x1000 in Chrome, the reel holds a
16.7ms median frame through a continuous scroll. Reduced motion, `file://`,
a 1100px window and a 390px phone are all checked.

---

## Running it on a show it has never seen

The brief says a shortlisted solution gets run on a new input during the
interview, so that is tested rather than asserted. `data/sample/` is three
episodes of an original contemporary thriller I wrote for the purpose - a
different genre, different writers, different vocabulary, nothing in the
lexicons tuned for it. The pack's screenplays are not in this repo; these
are, so a fresh clone produces a real run immediately:

```bash
python -m cutlist run data/sample --out out-sample --show "The Last Shift" --top 6 --no-web
```

```
3 episodes · 104 beats · 4.6 minutes
    ↓  0.03 seconds
11 verified candidates · 6 exported with EDLs
```

Its top pick opens on a phone slammed onto a table and cuts out on
*"What was her name?"* - a hook in the first second and an unanswered
question at the out-point, which is the shape the brief describes. Outputs
are in `out-sample/`.

Writing that test found real overfitting: `"duke": 0.35` was sitting in the
reveal lexicon, learned from the period setting of the supplied pack and
worth nothing on a contemporary thriller. Removing it moved the gold-set
score by **0.000**, which is the tell that it was never earning its place.
`tests/test_new_input.py` now introspects every lexicon and fails if a
proper noun from either show appears in one.

---

## How it works

The idea the whole thing rests on: **taste is a model's job, arithmetic is
not.** Where a clip starts and stops, how much dialogue is in it, how many
people a stranger has to keep track of — all countable, free, instant, and
impossible to hallucinate. The model is spent only on what counting cannot
judge.

```
screenplays ──▶ parse ──▶ signals ──▶ candidates ──▶ verify ──▶ judge ──▶ export
               exact     rules        beat-snapped   grounding  taste      JSON
               timing    lexicons     windows + NMS  checks     (optional) CSV/EDL
```

1. **parse** — 3,727 blocks into typed, timed beats. Strict: it fails loudly
   rather than guessing. Dialogue keeps its actor direction (`Cold,
   Commanding`), which turns out to be the richest signal in the corpus.
2. **signals** — per-beat scores from hand-built lexicons: shock, reveal,
   threat, emotional heat, questions, cliffhanger sound and shot grammar,
   resolution, and context debt. Each records *which beat fired it*.
3. **candidates** — every window whose in- and out-points are real beat
   boundaries, 20–60s, scored on five axes (hook / cliff / intensity /
   standalone / shape), then non-maximum suppression so the list is ten
   different promos rather than ten crops of one.
4. **verify** — every cut point re-checked against the parsed script before
   anything is written. This caught real bugs during the build.
5. **judge** — the top 25 go to a model, which scores and writes the *why*.
   **It is never given a timestamp field**, so a hallucinated cut point
   cannot exist.
6. **export** — JSON, CSV, markdown, EDL.

Also generates **stitched** promos: the hardest hook in the show cut
straight to someone else's cliffhanger, across episodes. The brief allows
it; the genre does it constantly.

---

## Is it any good?

Measured against **six episodes I cut by hand before running the tool on
them**, plus three baselines (`python -m cutlist eval data/scripts`):

| system | mean IoU | gold covered |
|---|---|---|
| **cutlist** | **0.380** | 0.425 |
| last-40-seconds | 0.349 | 0.500 |
| densest-dialogue | 0.090 | 0.133 |
| random | 0.015 | 0.026 |

It beats the trivial baseline, but not by much — and `last-40s` is a
genuinely strong baseline, because microdrama episodes are *written* to end
on a cliffhanger. The honest numbers, the ablation, and where it picks
badly are in [`docs/SOLUTION.md`](docs/SOLUTION.md).

---

## Layout

```
cutlist/parse.py       screenplay  -> typed, timed beats
cutlist/signals.py     lexicons and per-beat scoring
cutlist/candidates.py  window generation, five-axis scoring, suppression
cutlist/verify.py      grounding checks
cutlist/judge.py       swappable model layer (+ offline fallback)
cutlist/export.py      JSON / CSV / markdown / EDL
cutlist/evaluate.py    gold set, baselines, ablation, stability
web/index.html         the prototype - the film, then the desk
web/film.css           Act I
web/app.css            Act II, the desk
web/reel.js            scroll engine, the 35mm reel, the grounding wall
web/app.js             the review desk
web/backdrop.js        the canvas atmosphere layer
web/promos.js          generated: the run, as a JS global
docs/SOLUTION.md       the two-page write-up
docs/RESEARCH.md       sourced evidence behind the design choices
```

---

## Confidentiality

The brief says: *"The input pack is Kuku's own content, shared just for this
assignment. You're welcome to use it with AI tools for your work, but please
don't publish or share it."* This repository is public, so:

- **The screenplays are not here.** `data/scripts/` is gitignored. Clone this
  and the pack-based commands will not run until you drop the pack in.
- **`out/all-candidates.json` is not here either.** It holds every one of the
  156 windows with all their beats - 38% of the pack, verbatim. It is a debug
  artefact rather than a required deliverable, so it stays local.
- **`out/` is here**, because the brief requires a folder of unedited outputs.
  The twenty exported promos quote about **4.5%** of the pack: the least that
  can be published while still handing over a working deliverable.
- **`data/sample/` is mine**, written for this submission, and carries no Kuku
  content at all.

If you would rather see the full candidate dump, it is produced by any local
run and I can share it directly.
