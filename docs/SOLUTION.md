# CUTLIST — finding the promos

**Problem 1.** A tool that reads a microdrama screenplay and returns ranked
20–60s promo clips with exact cut points. Run on all 50 episodes of *I
Married a Broken Soldier. He was a Duke*.
Repo: **github.com/Mr-Bathwal/Kuku_Assesment** · Prototype: `web/index.html`,
opens off the filesystem, no server · Raw outputs: `out/` · Run steps: `README.md`

## Why this problem

Marketing was **₹1,105 crore of Kuku's FY26 spend — 74.5% of revenue and
77.7% of total expenditure, about ₹3 crore a day.**¹ Microdrama apps run
roughly **5,770 deduplicated ad creatives a month each**, and one hit show
has run **98,000**.² The ad-intelligence teardown of the biggest spender is
blunt about what wins: *"not long videos about its overall plot, but
under-1-minute clips of exciting moments."*² That is precisely this
output. Promo selection is a hand step sitting on top of the largest cost
line in the company — and Kuku ships **200–250 shows a month, targeting
1,000**, with dedicated promo editors *per language*.³ Problems 2 and 3 are
real, but neither touches a ₹3-crore-a-day lever.

## What I assumed, where the brief was silent

- **A cut may only land on a beat boundary** written in the screenplay —
  never mid-line. This is the central design constraint, not a detail.
- **Promos are mostly one continuous stretch.** Microdrama episodes are
  written as one location, one beat, so a promo is a *trim of a scene*, not
  an assembly.⁴ I still generate stitched promos — the brief allows them —
  but conservatively: one hook, one cliffhanger, nothing between.
- **Timecodes are MM:SS.cc, 30fps** for EDL export.
- **No video exists**, only screenplays, so everything is judged from text.
- **"Best" means best for cold acquisition** — a stranger mid-scroll — not
  best scene.

## How it works

**Taste is a model's job; arithmetic is not.** Where a clip starts and
stops, how much dialogue is in it, how many names a stranger must track —
countable, free, instant, impossible to hallucinate. The model is spent
only on what counting cannot judge.

`parse → signals → candidates → verify → judge → export`

**Parse** turns 3,727 blocks into typed, timed beats. Dialogue keeps its
actor direction (`Cold, Commanding`) — 620 distinct tags, and the richest
signal in the corpus. **Signals** score each beat from hand-built lexicons
(shock, reveal, threat, emotional heat, questions, cliffhanger sound *and*
shot grammar, resolution, context debt), each recording which beat fired
it. **Candidates** generates every window with real beat boundaries at both
ends, 20–60s, scored on five axes — **hook** (is there something in the
first 3 seconds), **cliff** (does it break before the answer), **intensity**,
**standalone** (can a stranger follow it), **shape** — then suppresses
near-duplicates so the list is ten promos, not ten crops of one.

**Standalone is the axis most tools skip**, and the reason good scenes make
bad promos: it counts speaking characters (two in confrontation is ideal,
five is not), phrases pointing off-screen, and *series baggage* — a
character first met in episode 38 carries 37 episodes of history a cold
viewer does not have.

**The model never receives a timestamp field.** It is shown a window the
parser already chose and asked only to score hook/cliff/standalone and
write the *why*. A hallucinated cut point is structurally unable to exist.
For scale: across this show there are **3,419 real beat starts among 61,612
expressible timestamps — a model free-handing an in-point would be wrong
94.4% of the time.** Then `verify` re-checks every cut against the script
anyway, before anything is written.

**Output** is JSON, a CSV to schedule from, a markdown cut sheet, and a
**CMX3600 EDL per promo** that imports straight into Premiere or Resolve —
the cuts arrive on the timeline, already named and in order.

## How I know it's good — and where it isn't

I hand-cut the best promo in **six episodes, chosen and labelled before
running the tool on them** (`cutlist/evaluate.py`), then measured:

| | mean IoU | gold covered | hits @ IoU ≥ 0.5 |
|---|---|---|---|
| **cutlist** | **0.380** | 0.425 | 2/6 |
| last-40-seconds | 0.349 | 0.500 | **3/6** |
| densest-dialogue | 0.090 | 0.133 | 0/6 |
| random | 0.015 | 0.026 | 0/6 |

**It beats the trivial baseline, and not by much.** `last-40s` is strong
because microdramas are *written* to end on a cliffhanger, and it still
covers more of my hand-cut windows than I do. What it cannot do is rank,
cut shorter than 40s, find a second promo in an episode, stitch across
episodes, or say why — it returns 50 undifferentiated windows. CUTLIST
returns 156 verified, ranked, diverse candidates with reasons, in 1.6s.

**It runs on a show it has never seen.** `data/sample/` is three episodes of
an original thriller I wrote for the purpose — different genre, different
vocabulary, nothing tuned for it. 104 beats, 0.03s, 11 verified candidates;
the top pick opens on a phone slammed onto a table and cuts out on *"What was
her name?"* Writing that test found real overfitting: `"duke": 0.35` sat in
the reveal lexicon, learned from this pack's period setting. Removing it moved
the gold score by **0.000** — it was never earning its place.

**Measurement found three real bugs**, each worth more than the tuning:
the cliffhanger scorer read only dialogue and sound, so it scored **0.00 on
all six hand-cut out-points** — in a screenplay the last beat before a cut
is almost always a camera direction, and the shot holding on a reaction
*is* the cliffhanger; every hyphenated lexicon term (`close-up`, `push-in`)
silently matched nothing; and sound was the only beat kind never scored for
shock, so episode 18's falling roof registered as ambience. Fixing those
took the score from **0.227 → 0.380**.

**Where it picks badly.**

- *Lexicon collisions.* "He **strikes** flint and steel over dry kindling"
  scored as hard as a slap and put a man lighting a campfire near the top.
  Damped by checking the object the verb lands on — a partial fix, not a
  real one.
- *Ablation is inconclusive on two axes.* Dropping **hook** or **standalone**
  *improves* agreement by +0.118 — but it changes only 3 of 6 episodes, two
  up and one down. At n=6 that is noise. I kept both: the 3-second hook is
  the primary variable in every industry account of this format,² and I'd
  rather be wrong on six labels than ship a promo finder that ignores the
  opening.
- *Six labels is a small gold set*, labelled by me, who also wrote the
  scorer. Real validation is editor A/B against posted performance.
- *It cannot see.* A silent held look can be the best promo in an episode
  and will score near zero.
- *Spoilers are unguarded.* Nothing stops it proposing the episode-45
  reveal as promo #1.
- *Stitched promos are the weakest output* — the research says the form
  runs on continuous trims,⁴ and mine are plausible rather than proven.

Weights are stable: **98% of picks unchanged** when every weight is jittered ±20%.

## Scaling to every show Kuku makes

The rules path is **1.6s per 50-episode show and costs nothing** — 225
shows a month is **6 minutes of compute**; the 1,000-show target is 27
minutes. The model pass is the only variable cost and it is deliberately
small: only the top 25 candidates are reviewed, at ~852 input + 120 output
tokens each — **21K input tokens per show**, ~4.8M a month at today's rate,
21M at the target. Cents, not rupees, per show. Provider is one environment
variable (`CUTLIST_PROVIDER`), so a stronger model is a config change — and
that path is tested over real HTTP against a local OpenAI-compatible server
(`tests/test_model_swap.py`), including a model that volunteers timestamps it
was never asked for. They are discarded and the cut points do not move. I
have not run it against a paid key.

**The human stays at the end, not the middle.** The prototype
(`web/index.html`, no server, no build) opens on the corpus — fifty
episodes as a scroll-driven reel, each frame the episode's own pressure
curve — and cuts into a keyboard-driven review desk: approve, reject, nudge
an in-point by one beat, export the decisions. Every number on it is read
from the run, and because there is no video of this show there are no
stills on it either. The editor stops hunting and starts judging. *Assumption:* if promo selection is ~2 hours per show,
225 shows is ~450 editor-hours a month; I could not source a real figure
for that step, so treat the saving as directional.

## AI tools, and where they got it wrong

Built with **Claude** (Claude Code) for the code, three research subagents
for the microdrama, Kuku and UI-reference briefs, and my own reading of the
screenplays for the gold labels. It was wrong in a way worth reporting: the
first scoring function summed all signal axes for every beat, so a line
*screamed* in terror scored **0.22** — below a murmured question — because
physical-shock terms only fire on action beats and dialogue could never
reach them. It looked completely reasonable and was badly wrong, and only
printing the top-scoring lines and not recognising them caught it. Every
number above is from a run I can reproduce, which is the only reason I
trust any of it.

---
¹ RoC filings via Medianama/Entrackr, FY26. ² SocialPeta × AMO Pictures,
*Insight into Global Micro Drama App Marketing*, 2026. ³ Hollywood Reporter
India; Kuku job postings. ⁴ Microdrama writing/editing practice; see
`docs/RESEARCH.md`.
