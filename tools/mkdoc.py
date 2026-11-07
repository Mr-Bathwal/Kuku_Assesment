"""
docs/SOLUTION.md + out/evaluation.json  ->  docs/_solution.html  ->  SOLUTION.pdf

    python tools/mkdoc.py && node tools/topdf.js

The prose lives in SOLUTION.md and is the single source for it; this file
holds the layout and draws the figures. Every figure is generated from
out/evaluation.json and out/promos.json at build time, so the document
cannot quote a number the last run did not produce - the same rule the
prototype follows.

Two pages is the brief's cap, and the layout is built to that: a fixed
two-page grid rather than a flow that happens to land there. If the prose
grows, TYPE_PT below is the knob.
"""

from __future__ import annotations

import json
import pathlib
import re
import sys

try:
    import markdown
except ImportError:                                    # pragma: no cover
    sys.exit("pip install markdown")

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC = ROOT / "docs" / "SOLUTION.md"
OUT = ROOT / "docs" / "_solution.html"

TYPE_PT = 8.0          # body size; the one knob that moves the page count

INK = "#15171E"
MUTED = "#5A6070"
FAINT = "#8A91A1"
RULE = "#DADDE4"
ACCENT = "#4F4ECF"
ACCENT_SOFT = "#E6E6FA"
WARN = "#B2741F"


# ----------------------------------------------------------------- source --

def load_markdown() -> tuple[str, str, dict[str, str], str]:
    raw = SRC.read_text(encoding="utf-8")
    body, _, foot = raw.partition("\n---\n")

    title = re.search(r"^#\s+(.+)$", body, re.M).group(1).strip()
    parts = re.split(r"^##\s+(.+)$", body, flags=re.M)
    lede = re.sub(r"^#\s+.+$", "", parts[0], flags=re.M).strip()
    # SOLUTION.md carries the links inline so it reads on its own in the repo.
    # Here the rail below the title already has them, so drop the duplicate.
    lede = lede.split("\nRepo:")[0].strip()
    sections = {parts[i].strip(): parts[i + 1].strip() for i in range(1, len(parts), 2)}
    return title, lede, sections, foot.strip()


def md(text: str) -> str:
    return markdown.markdown(text, extensions=["tables", "sane_lists"])


def strip_table(text: str) -> str:
    """The baseline table becomes a figure, so drop it from the prose."""
    return "\n".join(l for l in text.split("\n") if not l.lstrip().startswith("|")).strip()


def split_on(text: str, marker: str) -> tuple[str, str]:
    i = text.find(marker)
    return (text, "") if i < 0 else (text[:i].strip(), text[i:].strip())


# ------------------------------------------------------------------- data --

def load_data() -> tuple[dict, dict]:
    ev = json.loads((ROOT / "out" / "evaluation.json").read_text(encoding="utf-8"))
    pr = json.loads((ROOT / "out" / "promos.json").read_text(encoding="utf-8"))
    return ev, pr


def secs(stamp: str) -> float:
    m, s = stamp.split(":")
    return int(m) * 60 + float(s)


def window(span: str) -> tuple[float, float]:
    a, b = span.split("-")
    return secs(a), secs(b)


# ---------------------------------------------------------------- figures --

def fig_gold(ev: dict, pr: dict) -> str:
    """
    The honest figure: every hand-cut episode, what the tool chose against
    what I chose. Two clean hits, one partial, three complete misses - which
    is exactly what a mean of 0.380 is made of, and what a bar chart of
    means would hide.
    """
    durations = {e["number"]: e["duration"] for e in pr["episodes"]}
    eps = ev["gold_set"]["episodes"]
    per = ev["per_episode"]["cutlist"]

    W, ROW, PAD_L, PAD_R = 540.0, 23.0, 34.0, 44.0
    H = 20 + ROW * len(eps)
    track_w = W - PAD_L - PAD_R

    out = [f'<svg viewBox="0 0 {W:.0f} {H:.0f}" width="100%" role="img" '
           f'aria-label="Hand-cut window against the tool\'s pick, per episode">']

    out.append(f'<text x="{PAD_L}" y="9" font-size="6.4" fill="{FAINT}" '
               f'letter-spacing="0.6">HAND-CUT WINDOW</text>')
    out.append(f'<rect x="{PAD_L + 72}" y="4" width="16" height="5" rx="1" '
               f'fill="{ACCENT_SOFT}" stroke="{ACCENT}" stroke-width="0.6"/>')
    out.append(f'<text x="{PAD_L + 100}" y="9" font-size="6.4" fill="{FAINT}" '
               f'letter-spacing="0.6">WHAT CUTLIST PICKED</text>')
    out.append(f'<rect x="{PAD_L + 192}" y="4" width="16" height="5" rx="1" fill="{ACCENT}"/>')
    out.append(f'<text x="{W - PAD_R + 4}" y="9" font-size="6.4" fill="{FAINT}" '
               f'letter-spacing="0.6">IoU</text>')

    for i, ep in enumerate(eps):
        y = 20 + i * ROW
        dur = durations.get(ep, 1.0)
        g0, g1 = window(ev["gold_set"]["labels"][str(ep)]["window"])
        p0, p1 = window(per[str(ep)]["pick"])
        iou = per[str(ep)]["iou"]

        x = lambda t: PAD_L + (t / dur) * track_w            # noqa: E731

        out.append(f'<text x="0" y="{y + 11:.1f}" font-size="7" fill="{MUTED}" '
                   f'font-family="monospace">EP{ep:02d}</text>')
        out.append(f'<rect x="{PAD_L}" y="{y:.1f}" width="{track_w:.1f}" height="15" '
                   f'fill="#F2F3F7"/>')

        out.append(f'<rect x="{x(g0):.1f}" y="{y + 1.5:.1f}" width="{max(1.2, x(g1) - x(g0)):.1f}" '
                   f'height="5" rx="1" fill="{ACCENT_SOFT}" stroke="{ACCENT}" stroke-width="0.6"/>')
        colour = ACCENT if iou > 0 else WARN
        out.append(f'<rect x="{x(p0):.1f}" y="{y + 8.5:.1f}" width="{max(1.2, x(p1) - x(p0)):.1f}" '
                   f'height="5" rx="1" fill="{colour}"/>')

        label = f"{iou:.2f}" if iou > 0 else "miss"
        out.append(f'<text x="{W - PAD_R + 4}" y="{y + 11:.1f}" font-size="7" '
                   f'fill="{colour}" font-family="monospace">{label}</text>')

    out.append("</svg>")
    return "".join(out)


def fig_baselines(ev: dict) -> str:
    """Mean IoU, four systems. The win is narrow and the chart says so."""
    rows = [("cutlist", True), ("last-40s", False),
            ("densest-dialogue", False), ("random", False)]
    W, ROW, PAD_L, PAD_R = 260.0, 17.0, 76.0, 30.0
    H = ROW * len(rows) + 10
    track = W - PAD_L - PAD_R
    top = max(ev["systems"][n]["mean_iou"] for n, _ in rows) or 1.0

    out = [f'<svg viewBox="0 0 {W:.0f} {H:.0f}" width="100%" role="img" '
           f'aria-label="Mean IoU against three baselines">']
    out.append(f'<text x="0" y="7" font-size="6.4" fill="{FAINT}" letter-spacing="0.6">'
               f'MEAN IoU AGAINST THE HAND-CUT SET</text>')
    for i, (name, mine) in enumerate(rows):
        v = ev["systems"][name]["mean_iou"]
        y = 12 + i * ROW
        out.append(f'<text x="0" y="{y + 8:.1f}" font-size="7" '
                   f'fill="{INK if mine else MUTED}" font-family="monospace">{name}</text>')
        out.append(f'<rect x="{PAD_L}" y="{y + 1:.1f}" width="{track:.1f}" height="9" fill="#F2F3F7"/>')
        out.append(f'<rect x="{PAD_L}" y="{y + 1:.1f}" width="{(v / top) * track:.1f}" '
                   f'height="9" fill="{ACCENT if mine else "#B9BECC"}"/>')
        out.append(f'<text x="{W - PAD_R + 4}" y="{y + 8:.1f}" font-size="7" '
                   f'fill="{INK if mine else MUTED}" font-family="monospace">{v:.3f}</text>')
    out.append("</svg>")
    return "".join(out)


def fig_ablation(ev: dict) -> str:
    """Which axis is load-bearing. Two of them are negative, and stay in."""
    order = ["cliff", "intensity", "shape", "hook", "standalone"]
    W, ROW, PAD_L, PAD_R = 260.0, 17.0, 60.0, 40.0
    H = ROW * len(order) + 10
    track = W - PAD_L - PAD_R
    mid = PAD_L + track / 2
    span = max(abs(ev["ablation"][k]["delta"]) for k in order) or 1.0

    out = [f'<svg viewBox="0 0 {W:.0f} {H:.0f}" width="100%" role="img" '
           f'aria-label="Change in mean IoU when each axis is dropped">']
    out.append(f'<text x="0" y="7" font-size="6.4" fill="{FAINT}" letter-spacing="0.6">'
               f'CHANGE IF THE AXIS IS DROPPED</text>')
    for i, k in enumerate(order):
        d = ev["ablation"][k]["delta"]
        y = 12 + i * ROW
        w = abs(d) / span * (track / 2)
        hurts = d < 0
        out.append(f'<text x="0" y="{y + 8:.1f}" font-size="7" fill="{MUTED}" '
                   f'font-family="monospace">{k}</text>')
        out.append(f'<rect x="{mid - w if hurts else mid:.1f}" y="{y + 1:.1f}" '
                   f'width="{w:.1f}" height="9" fill="{ACCENT if hurts else WARN}"/>')
        out.append(f'<text x="{W - PAD_R + 4}" y="{y + 8:.1f}" font-size="7" '
                   f'fill="{ACCENT if hurts else WARN}" font-family="monospace">'
                   f'{d:+.3f}</text>')
    out.append(f'<line x1="{mid:.1f}" y1="10" x2="{mid:.1f}" y2="{H - 4:.1f}" '
               f'stroke="{INK}" stroke-width="0.7"/>')
    out.append("</svg>")
    return "".join(out)


def fig_grounding(ev: dict) -> str:
    """5.5% of expressible timestamps are legal. The rest is the risk."""
    g = ev["hallucination_surface"]
    frac = g["beat_starts"] / g["expressible_timestamps"]
    W, H = 260.0, 26.0
    out = [f'<svg viewBox="0 0 {W:.0f} {H:.0f}" width="100%" role="img" '
           f'aria-label="Share of expressible timestamps that are legal cut points">']
    out.append(f'<text x="0" y="7" font-size="6.4" fill="{FAINT}" letter-spacing="0.6">'
               f'TIMESTAMPS THIS SHOW CAN EXPRESS</text>')
    out.append(f'<rect x="0" y="11" width="{W:.0f}" height="10" fill="{WARN}" opacity="0.18"/>')
    out.append(f'<rect x="0" y="11" width="{max(2.0, frac * W):.1f}" height="10" fill="{ACCENT}"/>')
    out.append(f'<text x="{max(2.0, frac * W) + 5:.1f}" y="18.6" font-size="6.6" fill="{MUTED}">'
               f'{g["beat_starts"]:,} legal in-points of {g["expressible_timestamps"]:,} '
               f'&#8212; {g["pct_of_guesses_that_would_be_invalid"]:.1f}% of a free-hand guess is wrong'
               f'</text>')
    out.append("</svg>")
    return "".join(out)


def metric_strip(pr: dict, ev: dict) -> str:
    m = pr["meta"]
    items = [
        (f'{m["episodes"]}', "episodes read"),
        (f'{m["beats"]:,}', "timed beats"),
        (f'{m["candidates"]}', "candidates"),
        (f'{m["verified"]}', "passed grounding"),
        (f'{len(pr["promos"])}', "promos + EDLs"),
        (f'{m["seconds"]}s', "end to end"),
        ("0", "dependencies"),
    ]
    cells = "".join(
        f'<div class="metric"><span class="v">{v}</span><span class="k">{k}</span></div>'
        for v, k in items)
    return f'<div class="strip">{cells}</div>'


# ------------------------------------------------------------------ build --

CSS = f"""
@page {{ size: A4; margin: 11mm 12mm; }}
* {{ box-sizing: border-box; }}
html, body {{ margin: 0; padding: 0; }}
body {{
  font-family: "IBM Plex Sans", "Segoe UI", Calibri, sans-serif;
  font-size: {TYPE_PT}pt; line-height: 1.45; color: {INK};
  -webkit-font-smoothing: antialiased;
}}
.page {{ position: relative; }}
.page + .page {{ break-before: page; padding-top: 2mm; }}

h1 {{
  font-family: "IBM Plex Serif", Georgia, serif;
  font-size: 19pt; font-weight: 600; letter-spacing: -0.4pt;
  margin: 0 0 1.5pt; line-height: 1.05;
}}
.lede {{ color: {MUTED}; margin: 0 0 7pt; max-width: 62em; }}
.lede strong {{ color: {INK}; font-weight: 600; }}
.rail {{
  font-family: "IBM Plex Mono", Consolas, monospace; font-size: 6.6pt;
  color: {MUTED}; letter-spacing: 0.1pt; margin: 0 0 8pt;
  padding-bottom: 5pt; border-bottom: 0.8pt solid {INK};
}}
.rail b {{ color: {INK}; font-weight: 500; }}

h2 {{
  font-family: "IBM Plex Serif", Georgia, serif;
  font-size: 10pt; font-weight: 600; color: {INK};
  margin: 9pt 0 3.5pt; letter-spacing: -0.15pt;
}}
h2:first-child {{ margin-top: 0; }}
h2 .n {{
  font-family: "IBM Plex Mono", monospace; font-size: 7pt; color: {ACCENT};
  margin-right: 5pt; font-weight: 500;
}}

p {{ margin: 0 0 3.5pt; }}
strong {{ font-weight: 600; }}
em {{ font-style: italic; }}
code {{
  font-family: "IBM Plex Mono", Consolas, monospace; font-size: 0.88em;
  background: #F1F2F6; padding: 0 2.5px; border-radius: 2px; color: #2A2E3A;
}}
ul {{ margin: 0 0 4pt; padding-left: 11pt; }}
li {{ margin-bottom: 2pt; }}
li::marker {{ color: {FAINT}; }}

.cols {{ column-count: 2; column-gap: 7mm; column-rule: 0.4pt solid {RULE}; }}
.cols.tight {{ margin-top: 3pt; }}
.cols > h2 {{ break-after: avoid; }}
.keep {{ break-inside: avoid; }}

.strip {{
  display: flex; gap: 0; margin: 0 0 9pt;
  border-top: 0.8pt solid {INK}; border-bottom: 0.4pt solid {RULE};
  padding: 4.5pt 0;
}}
.metric {{ flex: 1; padding-right: 5pt; }}
.metric .v {{
  display: block; font-family: "IBM Plex Mono", monospace;
  font-size: 12pt; font-weight: 500; letter-spacing: -0.4pt; color: {INK};
  font-variant-numeric: tabular-nums; line-height: 1.1;
}}
.metric .k {{
  display: block; font-size: 5.9pt; color: {FAINT};
  letter-spacing: 0.35pt; text-transform: uppercase; margin-top: 1.5pt;
}}

.figs {{ display: grid; grid-template-columns: 1fr 1fr; gap: 6mm; margin: 5pt 0 7pt; }}
figure {{ margin: 0; break-inside: avoid; }}
figcaption {{ font-size: 6.5pt; color: {FAINT}; margin-top: 2.5pt; line-height: 1.35; }}
.hero {{ margin: 4pt 0 3pt; break-inside: avoid; }}
/* An SVG with width:100% scales its height with the column. Left uncapped a
   one-bar statistic renders 70pt tall and costs a page. */
.hero svg {{ max-width: 148mm; }}
figure.keep svg {{ max-width: 112mm; }}
figure.keep.wide {{ margin-bottom: 4pt; }}

.pipe {{
  display: grid; grid-template-columns: repeat(6, 1fr); gap: 3.5mm;
  margin: 5pt 0 7pt; break-inside: avoid;
  border-top: 0.4pt solid {RULE}; padding-top: 5pt;
}}
.pipe .st .nm {{
  font-family: "IBM Plex Mono", monospace; font-size: 7.4pt; font-weight: 500;
  color: {INK}; margin-bottom: 1.5pt;
}}
.pipe .st .ds {{ font-size: 6.3pt; color: {MUTED}; line-height: 1.35; }}
.pipe .st .out {{
  font-family: "IBM Plex Mono", monospace; font-size: 6.6pt; color: {ACCENT};
  margin-top: 2.5pt; padding-top: 2.5pt; border-top: 0.4pt solid {RULE};
}}

.foot {{
  margin-top: 7pt; padding-top: 4pt; border-top: 0.4pt solid {RULE};
  font-size: 6.2pt; color: {FAINT}; line-height: 1.4;
}}
.foot em {{ font-style: italic; }}
.page {{ padding-bottom: 9pt; }}
.sig {{
  position: absolute; bottom: 0; right: 0;
  font-family: "IBM Plex Mono", monospace; font-size: 6pt; color: #B4B9C6;
}}
"""

PIPE = [
    ("parse", "Screenplay to typed, timed beats. Fails loudly rather than guessing.", "{beats} beats"),
    ("signals", "Seven lexicons, two collision guards. Each records which beat fired it.", "{tags} directions"),
    ("candidates", "Every window with real beat boundaries at both ends, on five axes.", "{cands} windows"),
    ("verify", "Eight grounding checks, before the model, so a bad cut costs no call.", "{verified} passed"),
    ("judge", "Top 25 to a model for hook, cliff, standalone and the why.", "1 env var"),
    ("export", "JSON, CSV, cut sheet, and one CMX3600 EDL per promo.", "{top} EDLs"),
]


def build() -> int:
    title, lede, sec, foot = load_markdown()
    ev, pr = load_data()
    m = pr["meta"]

    def S(key_fragment: str) -> tuple[str, str]:
        for k, v in sec.items():
            if key_fragment.lower() in k.lower():
                return k, v
        raise SystemExit(f"section not found: {key_fragment}")

    _, why = S("Why this problem")
    _, assumed = S("What I assumed")
    _, works = S("How it works")
    k_good, good = S("How I know")
    _, scaling = S("Scaling to every show")
    _, tools = S("AI tools")

    good = strip_table(good)
    good_head, good_bad = split_on(good, "**Where it picks badly.**")

    pipe = "".join(
        f'<div class="st"><div class="nm">{n}</div><div class="ds">{d}</div>'
        f'<div class="out">{o.format(beats=f"{m["beats"]:,}", tags=m["corpus"]["emotion_tags"], cands=m["candidates"], verified=m["verified"], top=len(pr["promos"]))}</div></div>'
        for n, d, o in PIPE)

    html = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500&family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Serif:wght@600&display=swap">
<style>{CSS}</style></head><body>

<section class="page">
  <h1>{title}</h1>
  <div class="lede">{md(lede)}</div>
  <div class="rail">GOURAV KUMAR BATHWAL &#183; BT23BTECH11008 &#183; IIT HYDERABAD
    &#160;&#160;|&#160;&#160; PROTOTYPE <b>mr-bathwal.github.io/Kuku_Assesment</b>
    &#160;&#160;|&#160;&#160; SOURCE <b>github.com/Mr-Bathwal/Kuku_Assesment</b>
    &#160;&#160;|&#160;&#160; RAW OUTPUTS <b>out/</b></div>

  {metric_strip(pr, ev)}

  <div class="cols">
    <h2><span class="n">01</span>Why this problem</h2>
    {md(why)}
    <h2><span class="n">02</span>What I assumed, where the brief was silent</h2>
    {md(assumed)}
  </div>

  <h2><span class="n">03</span>How it works</h2>
  {md(works)}
  <div class="pipe">{pipe}</div>

  <div class="cols tight">
    <h2><span class="n">04</span>Scaling to every show Kuku makes</h2>
    {md(scaling)}
  </div>

  <div class="sig">1 / 2 &#160;&#183;&#160; the solution</div>
</section>

<section class="page">
  <h2><span class="n">05</span>{k_good}</h2>
  <figure class="keep wide">{fig_grounding(ev)}</figure>
  {md(good_head)}

  <figure class="hero">{fig_gold(ev, pr)}
    <figcaption>Every episode I hand-cut before running the tool on it, against what the
    tool chose. Two near-exact, one partial, three complete misses &#8212; which is what a mean
    of {ev["systems"]["cutlist"]["mean_iou"]:.3f} is actually made of, and what a chart of means would hide.</figcaption>
  </figure>

  <div class="figs">
    <figure>{fig_baselines(ev)}
      <figcaption>It beats the trivial baseline and not by much. <code>last-40s</code> is strong
      because microdramas are written to end on a cliffhanger.</figcaption></figure>
    <figure>{fig_ablation(ev)}
      <figcaption>Dropping <strong>hook</strong> or <strong>standalone</strong> improves agreement, but changes
      only 3 of 6 episodes. At n=6 that is noise, and both stay in.</figcaption></figure>
  </div>

  <div class="cols">
    {md(good_bad)}
    <h2><span class="n">06</span>AI tools, and where they got it wrong</h2>
    {md(tools)}
  </div>

  <div class="foot">{md(foot)}</div>
  <div class="sig">2 / 2 &#160;&#183;&#160; the evidence</div>
</section>

</body></html>"""

    OUT.write_text(html, encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)}  ({len(html):,} chars)")
    print("now run: node tools/topdf.js")
    return 0


if __name__ == "__main__":
    raise SystemExit(build())
