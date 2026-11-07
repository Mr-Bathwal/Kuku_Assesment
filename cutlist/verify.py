"""
Grounding checks: nothing leaves this tool that is not in the screenplay.

The failure everyone expects from an AI tool here is a confident, plausible,
wrong timestamp - a cut at 01:12 in an episode where nothing happens at
01:12, which costs an editor the very minute the tool claimed to save. So
rather than trusting the pipeline, every promo is re-checked against the
parsed script before it is written out, and anything that fails is dropped
with a reason.

These checks run in milliseconds and have caught real bugs during the build,
not just hypothetical ones. They are the reason the numbers in the output
can be read as facts rather than suggestions.
"""

from __future__ import annotations

from dataclasses import dataclass

from .candidates import MAX_LEN, MIN_LEN, Candidate
from .parse import Episode, to_stamp

TOL = 0.001          # float comparison on timecodes parsed from text
HOOK_WINDOW = 3.0


@dataclass
class Violation:
    promo: int
    rule: str
    detail: str


def check(cands: list[Candidate], episodes: list[Episode]) -> list[Violation]:
    by_number = {e.number: e for e in episodes}
    bad: list[Violation] = []

    for i, cand in enumerate(cands, 1):
        if not cand.segments:
            bad.append(Violation(i, "empty", "promo has no segments"))
            continue

        for seg in cand.segments:
            ep = by_number.get(seg.episode)
            if ep is None:
                bad.append(Violation(i, "episode-exists", f"episode {seg.episode} is not in the input"))
                continue

            starts = {round(b.start, 3) for b in ep.beats}
            ends = {round(b.end, 3) for b in ep.beats}

            # The core guarantee: cuts land on beats the writer wrote.
            if round(seg.start, 3) not in starts:
                bad.append(Violation(i, "in-point-on-beat",
                                     f"ep{seg.episode} in at {to_stamp(seg.start)} is not a beat start"))
            if round(seg.end, 3) not in ends:
                bad.append(Violation(i, "out-point-on-beat",
                                     f"ep{seg.episode} out at {to_stamp(seg.end)} is not a beat end"))

            if seg.start < -TOL or seg.end > ep.duration + TOL:
                bad.append(Violation(i, "inside-episode",
                                     f"ep{seg.episode} {to_stamp(seg.start)}-{to_stamp(seg.end)} "
                                     f"falls outside the episode (runs {to_stamp(ep.duration)})"))
            if seg.duration <= 0:
                bad.append(Violation(i, "positive-length", f"ep{seg.episode} segment is not positive"))

        total = cand.duration
        if not (MIN_LEN - TOL <= total <= MAX_LEN + TOL):
            bad.append(Violation(i, "length", f"{total:.1f}s is outside the {MIN_LEN:.0f}-{MAX_LEN:.0f}s brief"))

        # Segments of one episode must not overlap or run backwards.
        per_ep: dict[int, list] = {}
        for seg in cand.segments:
            per_ep.setdefault(seg.episode, []).append(seg)
        for ep_no, segs in per_ep.items():
            segs = sorted(segs, key=lambda s: s.start)
            for a, b in zip(segs, segs[1:]):
                if b.start < a.end - TOL:
                    bad.append(Violation(i, "no-overlap", f"ep{ep_no} segments overlap"))

        # The hook must actually be inside the hook window, or the headline
        # claim of the whole tool is false.
        if cand.hook_beat:
            first = cand.segments[0]
            if cand.hook_beat.episode != first.episode or \
               cand.hook_beat.start > first.start + HOOK_WINDOW + TOL or \
               cand.hook_beat.end < first.start - TOL:
                bad.append(Violation(i, "hook-in-window",
                                     f"hook beat at {to_stamp(cand.hook_beat.start)} is not in the "
                                     f"first {HOOK_WINDOW:.0f}s after {to_stamp(first.start)}"))

        # Every beat cited must be a beat of the episode it claims.
        for b in cand.beats:
            ep = by_number.get(b.episode)
            if ep is None:
                continue
            if not any(abs(x.start - b.start) < TOL and x.text == b.text for x in ep.beats):
                bad.append(Violation(i, "quote-is-real",
                                     f"cited beat at ep{b.episode} {to_stamp(b.start)} is not in the script"))
                break

    return bad


def filter_clean(cands: list[Candidate], episodes: list[Episode]) -> tuple[list[Candidate], list[Violation]]:
    """Return only promos that pass every check, plus everything that failed."""
    bad = check(cands, episodes)
    broken = {v.promo for v in bad}
    clean = [c for i, c in enumerate(cands, 1) if i not in broken]
    return clean, bad
