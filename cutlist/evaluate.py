"""
Does it actually pick well? `python -m cutlist eval data/scripts`

Three questions, answered with numbers rather than screenshots.

**Is it better than doing something dumb?** Measured against a gold set of
six episodes I cut by hand *before* looking at what the tool chose for
them, and against three baselines - including the one that actually
threatens it, "just take the last 40 seconds", which is strong here
because microdramas are written to end on a cliffhanger.

**Which parts of the opinion are load-bearing?** Each scoring axis is
zeroed in turn and the damage measured. A weight that changes nothing is a
weight that should not be in the product.

**How much does the structure buy?** The headline claim is that a cut point
cannot be hallucinated. That is a property of the design, not of a model,
so it is checked by counting how small the legal target is: of every
timestamp a model could emit for an episode, how few are real beat
boundaries.

The gold set is six episodes, which is small, and I say so in the doc. It
is six episodes labelled honestly rather than fifty labelled by the same
rules the tool uses, which would prove nothing.
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass
from pathlib import Path

from .candidates import (MAX_LEN, MIN_LEN, Weights, candidates_for_episode,
                         _first_seen, suppress)
from .parse import Episode, parse_show, to_seconds, to_stamp

# --- the gold set -----------------------------------------------------------
# Six episodes, stratified across the 50, chosen *before* running the tool on
# them and labelled by reading the screenplay as an editor: the single best
# 20-60s promo window, snapped to beat boundaries. Episodes whose output I had
# already seen while building were excluded, so this is held out, not fitted.

GOLD: dict[int, tuple[str, str, str]] = {
    2:  ("00:00.00", "00:30.50", "'I cannot marry you' through to 'She is what I should have chosen'"),
    9:  ("01:28.00", "01:51.20", "the rumour of a living Duke, out on a whispered 'Impossible.'"),
    18: ("01:05.80", "01:30.00", "she runs back into the fire for the ledger; the beam comes down"),
    31: ("02:11.00", "02:35.20", "'Enough!' into Catherine burning her mother's book"),
    41: ("00:54.80", "01:33.50", "'You needed an entire chapel...' out on the cathedral exploding"),
    48: ("00:02.40", "00:26.50", "Catherine's 'ten days' speech, out on 'doors can be closed from the other side'"),
}


@dataclass
class Window:
    episode: int
    start: float
    end: float

    @property
    def duration(self) -> float:
        return self.end - self.start


def iou(a: Window, b: Window) -> float:
    """Temporal intersection-over-union: how much of the same clip is it."""
    if a.episode != b.episode:
        return 0.0
    inter = max(0.0, min(a.end, b.end) - max(a.start, b.start))
    union = a.duration + b.duration - inter
    return inter / union if union > 0 else 0.0


def overlap_of_gold(pick: Window, gold: Window) -> float:
    """How much of the hand-cut promo the tool's pick actually contains."""
    if pick.episode != gold.episode:
        return 0.0
    inter = max(0.0, min(pick.end, gold.end) - max(pick.start, gold.start))
    return inter / gold.duration if gold.duration > 0 else 0.0


# --- the systems under test -------------------------------------------------


def pick_cutlist(ep: Episode, seen: dict[str, int], weights: Weights) -> Window:
    best = suppress(candidates_for_episode(ep, weights, seen), limit=1)[0]
    s = best.segments[0]
    return Window(ep.number, s.start, s.end)


def pick_last40(ep: Episode) -> Window:
    """
    The lazy baseline, and a genuinely strong one: every episode of a
    microdrama is built to end on a cliffhanger, so the last 40 seconds is
    free cliffhanger. It is the bar a tool has to clear to be worth running.
    """
    end = ep.duration
    target = end - 40.0
    starts = sorted({b.start for b in ep.beats})
    below = [x for x in starts if x <= target] or [starts[0]]
    return Window(ep.number, below[-1], end)


def pick_densest(ep: Episode) -> Window:
    """Most words of dialogue per second, on beat boundaries. 'Where is the talking.'"""
    starts = sorted({b.start for b in ep.beats})
    ends = sorted({b.end for b in ep.beats})
    best, best_w = None, -1.0
    for lo in starts:
        for hi in ends:
            if not (MIN_LEN <= hi - lo <= MAX_LEN):
                continue
            words = sum(b.words for b in ep.beats
                        if b.kind == "DIALOGUE" and b.end > lo and b.start < hi)
            rate = words / (hi - lo)
            if rate > best_w:
                best, best_w = Window(ep.number, lo, hi), rate
    return best or Window(ep.number, 0.0, min(40.0, ep.duration))


def pick_random(ep: Episode, rng: random.Random) -> Window:
    starts = sorted({b.start for b in ep.beats})
    ends = sorted({b.end for b in ep.beats})
    for _ in range(400):
        lo = rng.choice(starts)
        hi = rng.choice(ends)
        if MIN_LEN <= hi - lo <= MAX_LEN:
            return Window(ep.number, lo, hi)
    return Window(ep.number, starts[0], min(starts[0] + 40, ep.duration))


# --- the hallucination surface ---------------------------------------------


def legal_fraction(episodes: list[Episode], precision: float = 0.1) -> dict:
    """
    How small is the target a free-text model has to hit?

    Counts, per episode, how many distinct beat boundaries exist against how
    many timestamps are expressible at the precision these screenplays use.
    The complement is the share of timestamps that are syntactically
    plausible, confidently formatted, and wrong - which is the space a model
    asked for raw timestamps is sampling from.
    """
    legal_starts = legal_ends = expressible = 0
    for ep in episodes:
        legal_starts += len({round(b.start, 2) for b in ep.beats})
        legal_ends += len({round(b.end, 2) for b in ep.beats})
        expressible += int(ep.duration / precision)
    return {
        "beat_starts": legal_starts,
        "beat_ends": legal_ends,
        "expressible_timestamps": expressible,
        "legal_start_fraction": round(legal_starts / expressible, 5),
        "pct_of_guesses_that_would_be_invalid": round(100 * (1 - legal_starts / expressible), 2),
    }


# --- the harness ------------------------------------------------------------


def run_eval(scripts: str | Path, out: Path | None = None, seed: int = 7) -> dict:
    episodes = parse_show(scripts)
    by_no = {e.number: e for e in episodes}
    seen = _first_seen(episodes)
    weights = Weights()
    rng = random.Random(seed)

    gold = {n: Window(n, to_seconds(a), to_seconds(b)) for n, (a, b, _) in GOLD.items()}

    systems = {
        "cutlist": lambda ep: pick_cutlist(ep, seen, weights),
        "last-40s": pick_last40,
        "densest-dialogue": pick_densest,
        "random": lambda ep: pick_random(ep, rng),
    }

    results: dict[str, dict] = {}
    per_episode: dict[str, dict] = {}
    for name, fn in systems.items():
        ious, covers, hits = [], [], 0
        per_episode[name] = {}
        for n, g in gold.items():
            pick = fn(by_no[n])
            i, c = iou(pick, g), overlap_of_gold(pick, g)
            ious.append(i)
            covers.append(c)
            hits += 1 if i >= 0.5 else 0
            per_episode[name][n] = {
                "pick": f"{to_stamp(pick.start)}-{to_stamp(pick.end)}",
                "gold": f"{to_stamp(g.start)}-{to_stamp(g.end)}",
                "iou": round(i, 3), "gold_covered": round(c, 3),
            }
        results[name] = {
            "mean_iou": round(sum(ious) / len(ious), 3),
            "mean_gold_covered": round(sum(covers) / len(covers), 3),
            "hits_at_iou_50": f"{hits}/{len(gold)}",
        }

    # Ablation: zero each axis, re-pick, measure the damage.
    ablation = {}
    base = results["cutlist"]["mean_iou"]
    for axis in ("hook", "cliff", "intensity", "standalone", "shape"):
        w = Weights(**{**weights.__dict__, axis: 0.0})
        ious = [iou(pick_cutlist(by_no[n], seen, w), g) for n, g in gold.items()]
        mean = sum(ious) / len(ious)
        ablation[axis] = {"mean_iou_without": round(mean, 3), "delta": round(mean - base, 3)}

    # Stability: jitter every weight +/-20% and see if the top pick survives.
    stable = 0
    trials = 20
    for t in range(trials):
        r = random.Random(1000 + t)
        w = Weights(**{k: v * r.uniform(0.8, 1.2) for k, v in weights.__dict__.items()})
        same = sum(
            1 for n, g in gold.items()
            if iou(pick_cutlist(by_no[n], seen, w), pick_cutlist(by_no[n], seen, weights)) >= 0.8
        )
        stable += same / len(gold)

    report = {
        "gold_set": {
            "episodes": sorted(gold),
            "note": "labelled by hand from the screenplay before running the tool on these episodes",
            "labels": {str(n): {"window": f"{a}-{b}", "why": why} for n, (a, b, why) in GOLD.items()},
        },
        "systems": results,
        "per_episode": per_episode,
        "ablation": ablation,
        "weight_stability": {
            "trials": trials,
            "mean_share_of_picks_unchanged_under_+-20%_weights": round(stable / trials, 3),
        },
        "hallucination_surface": legal_fraction(episodes),
    }

    if out:
        out.mkdir(parents=True, exist_ok=True)
        (out / "evaluation.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def print_report(r: dict) -> None:
    print("\n  GOLD SET")
    print(f"    {len(r['gold_set']['episodes'])} episodes, hand-cut: "
          f"{', '.join('EP' + str(n) for n in r['gold_set']['episodes'])}")
    print(f"    {r['gold_set']['note']}")

    print("\n  AGAINST BASELINES          mean IoU   gold covered   hits@IoU>=0.5")
    for name, s in r["systems"].items():
        star = " <--" if name == "cutlist" else ""
        print(f"    {name:<22} {s['mean_iou']:>7.3f} {s['mean_gold_covered']:>13.3f} "
              f"{s['hits_at_iou_50']:>14}{star}")

    print("\n  ABLATION (drop one axis)   mean IoU   change")
    for axis, a in sorted(r["ablation"].items(), key=lambda kv: kv[1]["delta"]):
        print(f"    without {axis:<16} {a['mean_iou_without']:>7.3f}  {a['delta']:+.3f}")

    st = r["weight_stability"]
    print(f"\n  STABILITY  {st['mean_share_of_picks_unchanged_under_+-20%_weights']:.0%} of picks "
          f"unchanged when every weight is jittered +/-20% ({st['trials']} trials)")

    h = r["hallucination_surface"]
    print(f"\n  HALLUCINATION SURFACE")
    print(f"    {h['beat_starts']} real beat starts across {h['expressible_timestamps']} "
          f"expressible timestamps")
    print(f"    a free-text model guessing an in-point is wrong "
          f"{h['pct_of_guesses_that_would_be_invalid']:.2f}% of the time by construction;")
    print(f"    cutlist cannot emit one, because the model is never shown a timestamp field.\n")
