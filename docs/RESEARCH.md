# Research notes

The evidence behind the design choices in `SOLUTION.md`. Claims are graded:
**[S]** sourced · **[C]** company claim, unaudited · **[I]** my inference.

A caution worth stating first: the *craft* layer of this field is mostly
vendor and affiliate blogs with a commercial stake. The genuinely
well-sourced material is in three places — platform ad documentation,
ad-intelligence datasets, and company filings. I have tried not to let
folklore into the scorer dressed as measurement.

---

## 1. Why promo selection is the high-leverage step

**Kuku FY26 financials** [S — RoC filings via Medianama / Entrackr]

| | FY25 | FY26 |
|---|---|---|
| Revenue from operations | ₹241.6 Cr | **₹1,484.2 Cr** |
| Marketing & advertising | ₹284.8 Cr | **₹1,105.1 Cr** |
| Total expenditure | ₹411 Cr | ₹1,421.8 Cr |
| Net result | −₹152.6 Cr | **+₹182.7 Cr** |

Derived [I, arithmetic]: marketing is **74.5% of revenue**, **77.7% of total
expenditure**, ≈ **₹3.03 crore per day**. Employee costs (₹74.1 Cr) are
**6.7%** of marketing spend — one point of marketing efficiency is worth
more than a large slice of total headcount.

**Production volume** [C/S — Hollywood Reporter India]: 10–20 shows/month at
launch → **200–250 shows/month now**, target **1,000/month**; **50+ episodes
per series**, each up to 2 minutes, each ending on a cliffhanger. Derived
[I]: ~11,250 episodes/month now, ~50,000 at target.

**Kuku runs human promo writers and promo editors, per language** [S — Kuku
job postings]. A "Video Editor – Hindi" posting is explicitly for
*"trailers, short clips, and ad creatives"* for microdrama and asks for
2–5 years in *"microdramas, OTT promos, or performance marketing
creatives."* A separate "AI – Video Editor (Microdrama)" posting asks the
editor to *"build hooks, emotional peaks, twists, and cliffhangers"*.
Equivalent postings exist per language, and there is a separate "Promo
Writer – Hindi" role for scripts *"designed to grab attention within
seconds."*

**Kuku already does this with AI, and says so** [C]: the AI stack is
described as spanning *"pitch to production to promotion"*, including
thumbnails and marketing creatives; CEO Lal Chand Bisu puts the split at
**70–80% GenAI, ~20% manual**, with *"humans still in the loop."*

---

## 2. Creative volume — why one promo is never enough

[S — SocialPeta × AMO Pictures, *Insight into Global Micro Drama App
Marketing*, 2026; ad-intelligence dataset, Jan–Dec 2025]

- **5,770 deduplicated ad creatives per month, per advertiser** (2025
  average), **up 144.9% YoY** — ≈190/day.
- **700+ monthly active microdrama advertisers**, up 63.6% YoY.
- Per-show creative counts: *"Too Young to Want Her Professor"* **98,000**
  creatives (12.5B impressions); *"Evil Bride vs. The CEO's Secret Mom"*
  **44,000**.
- **KukuTV ranks #13 globally** among going-global microdrama advertisers
  (Android, 2025) — operating at global creative scale already.
- **68% of US ad spend** by leading short-drama apps goes to social
  (Facebook ~25%, TikTok ~19%, Snapchat ~16%, Instagram ~8%).

**The finding that shaped this tool**, on the single biggest spender:

> "The drama's popular ad creatives **aren't long videos about its overall
> plot, but are under-1-minute clips of exciting moments**."

And their first viral formula, which maps one-to-one onto the scoring axes:
**Intense Conflicts (3-sec Lure) + Highlight Clips + Cliffhanger Ending.**
The report also names, as an industry trend, *"AI-generated covers and
clips of brilliant moments."*

---

## 3. Promo craft

**One continuous stretch, not a montage** [S, moderate confidence]. The
editing playbooks describe trimming a single scene and never discuss
stitching. The structural reason: microdrama episodes are *written* as one
location, one beat — changing location inside 90 seconds is listed as a
top writing mistake. So the source material is already single-scene, and a
promo is a trim rather than an assembly. This is the opposite of
conventional trailer grammar.

*Consequence for the tool:* continuous windows are the primary output;
stitched promos are generated but demoted and flagged as the weaker,
less-evidenced form. Note the tension — SocialPeta's Formula 1 describes
"3–7 mid-sequence high-impact clips", which *is* an assembly. The sources
disagree and I have not resolved it.

**The first three seconds** [S — platform documentation and ad research].
The hook must break the scroll before the viewer is lost; practitioner
accounts converge on physical shock, an accusation, a reveal, or a question
that demands an answer. Beautiful establishing shots are the documented
failure mode. This is the brief's own definition too, so it is weighted
highest (0.32).

**Cliffhanger** — cut *before* resolution, on an open question, with the
app as the only way to find out. In this corpus the writers mark it
explicitly: five SOUND FX blocks literally contain the word "cliffhanger",
and every episode is built to end on one.

**Genre trope vocabulary** [S, folklore-grade]: contract marriage, secret
heir, revenge, abandoned bride, mistaken identity, hidden pregnancy,
CEO/billionaire, rebirth. Useful as lexicon seed; not used as evidence.

**Prior art in automatic trailer/highlight selection** [S]: IBM's *Morgan*
trailer, highlight-detection literature, and commercial virality scorers
(Opus Clip scores 0–99 on Hook / Flow / Value / Trend). Known weakness
across all of them: they score a clip but do not expose *why*, so a
professional cannot argue with the result. CUTLIST shows the beat that
fired each signal for exactly this reason.

---

## 4. Competitive note

At least four public GitHub repositories named `kuku-promo-finder` exist
from other candidates for this assignment, one with a closely convergent
architecture (deterministic parser, model proposes IDs not timestamps,
validator, ~35/35/20 weights, Streamlit, offline fallback). The convergence
is itself evidence the shape is right. Where this submission differs:
series-aware **context debt** in the standalone score, a **held-out
hand-cut gold set with baselines and ablation** rather than an unvalidated
ranking, lexicon-collision damping, **EDL export**, zero dependencies, and
a review desk built for an editor rather than a demo.

---

## 5. What I could not source

- Any published CAC or CPI for Kuku or any Indian microdrama app.
- Kuku's own creative volume, or promos produced per week.
- **Hours a promo editor spends selecting moments per show** — the input the
  "editor-hours saved" claim needs. Stated as a labelled assumption in
  `SOLUTION.md` rather than asserted.
- Any data-backed teardown of Kuku/ReelShort/DramaBox promos specifically.

## Primary sources

- Medianama, Kuku FY26 revenue/IPO filings — https://www.medianama.com/2026/10/223-kuku-ipo-revenue-surges/
- TechCrunch, Kuku $85M Series C (scale, pricing, AI split) — https://techcrunch.com/2025/10/15/indias-kuku-snags-85m-as-mobile-content-wars-intensify/
- Hollywood Reporter India, India's microdrama boom (shows/month, cost/minute) — https://www.hollywoodreporterindia.com/features/insight/indias-microdrama-boom-how-data-desire-and-aritifical-intelligence-are-reshaping-entertainment
- SocialPeta × AMO Pictures, Global Micro Drama App Marketing 2026 — https://investgame.net/wp-content/uploads/2026/04/2026-04-07-socialpeta_x_amo_pictures_insight_into_global_micro_drama_app_marketing_wp.pdf
- Marketing Mind, Bisu on AI microdrama — https://marketingmind.in/from-reels-to-a-feed-of-movies-kukus-lal-chand-bisu-bets-big-on-ai-microdramas/
- afaqs!, how microdramas are advertised in India — https://www.afaqs.com/news/mktg/tiny-episodes-big-hooks-how-micro-dramas-are-advertised-in-india-10971497
- Opus Clip virality score documentation — https://help.opus.pro/docs/article/virality-score
