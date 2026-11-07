"""
Finding the cut points.

An editor's actual problem is not "which scene is good" - they already know
that after one watch. It is "which forty seconds can stand alone, and
exactly where do I cut". Those are different problems, and only the second
one is arithmetic.

So: every candidate promo is a window whose in- and out-points are real beat
boundaries from the screenplay. The tool cannot propose a cut in the middle
of a line of dialogue, because such a window is never generated. That one
constraint removes the single most common failure of asking a language model
for timestamps.

Each window is scored on five axes, kept separate so a bad pick can be
diagnosed rather than just distrusted:

    hook        does something stop the thumb inside the first 3 seconds
    cliff       does it break off before the moment resolves
    intensity   is anything happening, per second
    standalone  can a stranger follow it with no prior episode
    shape       is it the right length, with no dead air

Then non-maximum suppression, so the output is ten distinct promos rather
than ten slightly different crops of the same argument.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .parse import ACTION, CAMERA, DIALOGUE, Beat, Episode, to_stamp
from .signals import BeatSignal, signal_episode

MIN_LEN, MAX_LEN = 20.0, 60.0
HOOK_WINDOW = 3.0      # the brief's own definition of a hook
CLIFF_WINDOW = 5.0     # how much of the tail counts as the out-point
IDEAL_LEN = 28.0      # the six hand-cut promos average 27.5s; the old 34 biased long


@dataclass
class Weights:
    """Visible, arguable, one place to tune. These are the whole opinion."""

    hook: float = 0.32
    cliff: float = 0.26
    intensity: float = 0.16
    standalone: float = 0.18
    shape: float = 0.08


@dataclass
class Segment:
    episode: int
    start: float
    end: float

    @property
    def duration(self) -> float:
        return self.end - self.start

    def to_dict(self) -> dict:
        return {
            "episode": self.episode,
            "start": round(self.start, 2),
            "end": round(self.end, 2),
            "start_tc": to_stamp(self.start),
            "end_tc": to_stamp(self.end),
            "duration": round(self.duration, 2),
        }


@dataclass
class Candidate:
    segments: list[Segment]
    scores: dict[str, float]
    score: float
    hook_beat: Beat | None
    cliff_beat: Beat | None
    beats: list[Beat] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)
    characters: list[str] = field(default_factory=list)
    kind: str = "continuous"      # continuous | stitched

    @property
    def duration(self) -> float:
        return sum(s.duration for s in self.segments)

    @property
    def episodes(self) -> list[int]:
        return sorted({s.episode for s in self.segments})


# --- scoring ----------------------------------------------------------------


def _overlapping(sigs: list[BeatSignal], lo: float, hi: float) -> list[BeatSignal]:
    return [s for s in sigs if s.beat.end > lo and s.beat.start < hi]


def _snap_start(sigs: list[BeatSignal], t: float) -> float:
    """Nearest real beat start at or before `t`. Cuts land where beats begin."""
    starts = sorted({s.beat.start for s in sigs})
    below = [x for x in starts if x <= t + 1e-6]
    return below[-1] if below else starts[0]


def _snap_end(sigs: list[BeatSignal], t: float, cap: float) -> float:
    """Nearest real beat end at or after `t`, never past the episode."""
    ends = sorted({s.beat.end for s in sigs if s.beat.end <= cap + 1e-6})
    above = [x for x in ends if x >= t - 1e-6]
    return above[0] if above else (ends[-1] if ends else cap)


def score_hook(sigs: list[BeatSignal], start: float) -> tuple[float, Beat | None, str]:
    """
    The first three seconds decide whether the clip is watched at all.

    What counts: something with stop-power landing early. A clip that opens
    on an establishing camera move is penalised however good the scene is -
    on a feed, nobody waits four seconds for the cathedral doors.
    """
    inside = _overlapping(sigs, start, start + HOOK_WINDOW)
    if not inside:
        return 0.0, None, "nothing in the first 3s"

    best, best_sig = 0.0, None
    for s in inside:
        lateness = max(0.0, s.beat.start - start) / HOOK_WINDOW
        value = s.stop_power * (1.0 - 0.45 * lateness)
        if s.beat.kind == DIALOGUE and s.beat.start - start <= 1.2:
            value *= 1.15          # someone is already talking when it opens
        if value > best:
            best, best_sig = value, s

    opening = min(inside, key=lambda s: s.beat.start)
    if opening.beat.kind == CAMERA and opening.stop_power < 0.25:
        best *= 0.55               # opens on scenery
    talk = [s for s in inside if s.beat.kind == DIALOGUE]
    if not talk:
        best *= 0.70               # silent open

    why = best_sig.why[0] if best_sig and best_sig.why else "opens on movement"
    return min(1.0, best), (best_sig.beat if best_sig else None), why


def score_cliff(sigs: list[BeatSignal], end: float, ep_duration: float) -> tuple[float, Beat | None, str]:
    """
    The out-point has to hurt. It must land before the answer arrives.
    """
    tail = _overlapping(sigs, end - CLIFF_WINDOW, end)
    if not tail:
        return 0.0, None, "nothing at the out-point"

    last = max(tail, key=lambda s: s.beat.end)
    value = 0.0
    why = []

    # The last *spoken* line in the tail, which is usually not the last beat:
    # a camera direction almost always sits after it. Reading only the final
    # beat was the bug that scored every hand-cut out-point at zero.
    spoken = [s for s in tail if s.beat.kind == DIALOGUE]
    if spoken:
        line = max(spoken, key=lambda s: s.beat.end)
        if line.question:
            value = max(value, 0.85)
            why.append("ends on an unanswered question")
        value = max(value, 0.80 * line.reveal, 0.78 * line.threat)
        if line.reveal >= 0.6:
            why.append("ends on a disclosure")
        if line.threat >= 0.6:
            why.append("ends on a threat")
        if "!" in line.beat.text and line.heat >= 0.8:
            value = max(value, 0.72)
            why.append("ends on a shout")

    # The shot that holds the cut.
    visual = max((s.cliff_visual for s in tail), default=0.0)
    if visual:
        value = max(value, 0.62 * visual + 0.22)
        if visual >= 0.7 and not why:
            why.append("holds on a reaction instead of an answer")

    # Violence frozen mid-act is its own kind of unresolved.
    shock = max((s.shock for s in tail if s.beat.kind in (ACTION, CAMERA)), default=0.0)
    if shock >= 0.6:
        value = max(value, 0.58 * shock + 0.20)
        why.append("cuts on the act itself")

    sfx = max((s.cliff_sfx for s in tail), default=0.0)
    if sfx:
        value = max(value, 0.70 * sfx + 0.25)
        why.append("sound cue holds it unresolved")

    # An episode of a microdrama is built to end on a cliffhanger; landing on
    # that boundary inherits the writers' own work.
    if ep_duration - end <= 1.5:
        value = max(value, 0.72)
        why.append("lands on the episode's own cliffhanger")

    # Warmth at the out-point is the opposite of what is wanted.
    warmth = max((s.resolution for s in tail), default=0.0)
    value *= 1.0 - 0.55 * warmth
    if warmth >= 0.6:
        why.append("but it resolves - weak out-point")

    if not why:
        why.append("cuts mid-scene")
    return min(1.0, value), last.beat, "; ".join(why[:2])


def score_intensity(sigs: list[BeatSignal], duration: float) -> float:
    """Words and incident per second. A promo cannot afford a quiet stretch."""
    if duration <= 0:
        return 0.0
    dialogue = [s for s in sigs if s.beat.kind == DIALOGUE]
    words = sum(s.beat.words for s in dialogue)
    wps = words / duration                       # ~2.8 w/s is brisk speech
    speakers = [s.beat.speaker for s in dialogue]
    turns = sum(1 for a, b in zip(speakers, speakers[1:]) if a != b)
    heat = sum(s.stop_power for s in sigs) / max(1.0, duration / 6.0)
    return min(
        1.0,
        0.40 * min(1.0, wps / 2.6)
        + 0.28 * min(1.0, turns / max(1.0, duration / 7.0))
        + 0.32 * min(1.0, heat),
    )


def score_standalone(sigs: list[BeatSignal], first_seen: dict[str, int], episode_no: int) -> tuple[float, list[str]]:
    """
    Can a stranger follow it?

    This is the axis most tools skip, and the reason good scenes make bad
    promos. Three things make a clip hard to drop into cold: too many names
    to track, lines that point at events off-screen, and characters who only
    mean something after thirty episodes of history.
    """
    speakers = [s.beat.speaker for s in sigs if s.beat.kind == DIALOGUE and s.beat.speaker]
    cast = list(dict.fromkeys(speakers))

    n = len(cast)
    if n == 0:
        crowding = 0.35                  # nobody speaks: hard to follow
    elif n <= 1:
        crowding = 0.72                  # a monologue plays, but flatter
    elif n <= 3:
        crowding = 1.00                  # a confrontation: ideal
    else:
        crowding = max(0.25, 1.0 - 0.18 * (n - 3))

    debt = min(1.0, sum(s.debt for s in sigs) / 3.0)

    # A character first met in episode 38 carries 37 episodes of baggage.
    baggage = 0.0
    for c in cast:
        intro = first_seen.get(c, 1)
        if intro > 1:
            baggage += min(0.30, 0.012 * (episode_no - intro))
    baggage = min(0.5, baggage)

    return max(0.0, min(1.0, crowding * (1.0 - 0.45 * debt) - baggage)), cast


def score_shape(duration: float, sigs: list[BeatSignal]) -> float:
    """Right length, and no hole in the middle."""
    length = 1.0 - min(1.0, abs(duration - IDEAL_LEN) / 26.0) * 0.6

    dialogue = sorted((s.beat for s in sigs if s.beat.kind == DIALOGUE), key=lambda b: b.start)
    gap = 0.0
    if len(dialogue) >= 2:
        gap = max(b.start - a.end for a, b in zip(dialogue, dialogue[1:]))
    elif dialogue:
        gap = duration - dialogue[0].duration
    dead = 1.0 - min(1.0, max(0.0, gap - 3.0) / 9.0) * 0.8
    return max(0.0, length * dead)


# --- generation -------------------------------------------------------------


def _first_seen(episodes: list[Episode]) -> dict[str, int]:
    seen: dict[str, int] = {}
    for ep in sorted(episodes, key=lambda e: e.number):
        for b in ep.beats:
            if b.speaker and b.speaker not in seen:
                seen[b.speaker] = ep.number
    return seen


def _build(ep: Episode, sigs: list[BeatSignal], lo: float, hi: float,
           weights: Weights, first_seen: dict[str, int]) -> Candidate:
    inside = _overlapping(sigs, lo, hi)
    duration = hi - lo

    hook, hook_beat, hook_why = score_hook(sigs, lo)
    cliff, cliff_beat, cliff_why = score_cliff(sigs, hi, ep.duration)
    intensity = score_intensity(inside, duration)
    standalone, cast = score_standalone(inside, first_seen, ep.number)
    shape = score_shape(duration, inside)

    scores = {
        "hook": round(hook, 3), "cliff": round(cliff, 3),
        "intensity": round(intensity, 3), "standalone": round(standalone, 3),
        "shape": round(shape, 3),
    }
    total = (
        weights.hook * hook + weights.cliff * cliff + weights.intensity * intensity
        + weights.standalone * standalone + weights.shape * shape
    )

    return Candidate(
        segments=[Segment(ep.number, lo, hi)],
        scores=scores,
        score=round(total, 4),
        hook_beat=hook_beat,
        cliff_beat=cliff_beat,
        beats=[s.beat for s in inside],
        reasons=[f"hook: {hook_why}", f"out: {cliff_why}"],
        characters=cast,
    )


def candidates_for_episode(ep: Episode, weights: Weights, first_seen: dict[str, int]) -> list[Candidate]:
    """
    Every legal window, scored.

    In-points are restricted to beats that could plausibly open a promo
    (a line, an action, a hard sound) - never a camera move, which on a feed
    reads as nothing happening. Out-points may be any beat end.
    """
    sigs = signal_episode(ep)
    starts = sorted({s.beat.start for s in sigs if s.beat.kind != CAMERA or s.stop_power > 0.35})
    ends = sorted({s.beat.end for s in sigs})

    out: list[Candidate] = []
    for lo in starts:
        for hi in ends:
            if MIN_LEN <= hi - lo <= MAX_LEN:
                out.append(_build(ep, sigs, lo, hi, weights, first_seen))
    return out


def suppress(cands: list[Candidate], overlap: float = 0.4, limit: int = 60) -> list[Candidate]:
    """
    Keep the best, drop anything that is mostly the same clip again.

    Without this the top fifty results are fifty crops of one argument, and
    an editor scrolls past all of them.
    """
    kept: list[Candidate] = []
    for cand in sorted(cands, key=lambda c: -c.score):
        a0, a1 = cand.segments[0].start, cand.segments[0].end
        ep = cand.segments[0].episode
        clash = False
        for k in kept:
            if k.segments[0].episode != ep:
                continue
            b0, b1 = k.segments[0].start, k.segments[0].end
            inter = max(0.0, min(a1, b1) - max(a0, b0))
            union = (a1 - a0) + (b1 - b0) - inter
            if union > 0 and inter / union > overlap:
                clash = True
                break
        if not clash:
            kept.append(cand)
        if len(kept) >= limit:
            break
    return kept


def stitched_candidates(episodes: list[Episode], per_show: int, weights: Weights,
                        first_seen: dict[str, int]) -> list[Candidate]:
    """
    Two-part promos: the hardest hook in the show, cut to someone else's
    cliffhanger.

    The brief allows a promo to join moments, and the genre does this
    constantly - a slap from episode 9 straight into a question from episode
    30. It only works when both halves are short and the pair is not
    confusing, so this is deliberately conservative: one hook beat, one
    cliff beat, nothing in between.
    """
    hooks: list[tuple[float, Episode, BeatSignal]] = []
    cliffs: list[tuple[float, Episode, BeatSignal]] = []
    cache: dict[int, list[BeatSignal]] = {ep.number: signal_episode(ep) for ep in episodes}

    for ep in episodes:
        sigs = cache[ep.number]
        for s in sigs:
            if s.beat.duration < 1.0 or s.beat.duration > 14.0:
                continue
            if s.stop_power >= 0.62 and s.beat.kind in (DIALOGUE, ACTION):
                hooks.append((s.stop_power, ep, s))
            tail_cliff, _, _ = score_cliff(sigs, s.beat.end, ep.duration)
            if tail_cliff >= 0.7:
                cliffs.append((tail_cliff, ep, s))

    hooks.sort(key=lambda x: -x[0])
    cliffs.sort(key=lambda x: -x[0])

    out: list[Candidate] = []
    # Each hook and each cliffhanger may be spent once. Without this the
    # strongest single out-point in the show - episode 1's finale - gets
    # welded onto every hook in the catalogue, and the list reads as one
    # idea six times.
    spent_hooks: set[tuple[int, float]] = set()
    spent_cliffs: set[tuple[int, float]] = set()
    for hv, hep, hs in hooks[:60]:
        if (hep.number, hs.beat.start) in spent_hooks:
            continue
        for cv, cep, cs in cliffs[:60]:
            if hep.number == cep.number:
                continue
            if (cep.number, cs.beat.end) in spent_cliffs:
                continue
            # Pad each half to a watchable length - then snap to real beat
            # boundaries. The first version added a flat nine seconds and
            # every stitched promo was rejected by verify.py for cutting
            # mid-beat: the padding has to land where the writer put a seam.
            h_lo = hs.beat.start
            h_hi = _snap_end(cache[hep.number], hs.beat.end + 9.0, hep.duration)
            c_lo = _snap_start(cache[cep.number], cs.beat.start - 11.0)
            c_hi = cs.beat.end
            total = (h_hi - h_lo) + (c_hi - c_lo)
            if not (MIN_LEN <= total <= MAX_LEN):
                continue

            h_sigs = _overlapping(cache[hep.number], h_lo, h_hi)
            c_sigs = _overlapping(cache[cep.number], c_lo, c_hi)
            both = h_sigs + c_sigs
            standalone, cast = score_standalone(both, first_seen, max(hep.number, cep.number))
            standalone *= 0.82          # a cut between shows costs the viewer something
            intensity = score_intensity(both, total)
            shape = score_shape(total, both)
            scores = {
                "hook": round(hv, 3), "cliff": round(cv, 3),
                "intensity": round(intensity, 3), "standalone": round(standalone, 3),
                "shape": round(shape, 3),
            }
            score = (
                weights.hook * hv + weights.cliff * cv + weights.intensity * intensity
                + weights.standalone * standalone + weights.shape * shape
            )
            out.append(
                Candidate(
                    segments=[Segment(hep.number, h_lo, h_hi), Segment(cep.number, c_lo, c_hi)],
                    scores=scores,
                    score=round(score, 4),
                    hook_beat=hs.beat,
                    cliff_beat=cs.beat,
                    beats=[s.beat for s in both],
                    reasons=[
                        f"hook: {hs.why[0] if hs.why else 'hard open'} (ep {hep.number})",
                        f"out: unresolved beat from ep {cep.number}",
                    ],
                    characters=cast,
                    kind="stitched",
                )
            )
            spent_hooks.add((hep.number, hs.beat.start))
            spent_cliffs.add((cep.number, cs.beat.end))
            break

    out.sort(key=lambda c: -c.score)
    return out[:per_show]


def diversify(cands: list[Candidate], per_episode: int = 1) -> list[Candidate]:
    """
    Re-order so the head of the list is not one episode four times.

    A ranked list is a posting schedule, not a leaderboard: an editor
    publishing the top five wants five different moments from the show.
    Nothing is dropped - repeats are pushed below the first pass.
    """
    head: list[Candidate] = []
    tail: list[Candidate] = []
    used: dict[int, int] = {}
    # Sort on the final score when a model pass has set one, or this runs
    # before the re-rank and its ordering is silently thrown away.
    for c in sorted(cands, key=lambda c: -getattr(c, "final", c.score)):
        # Every episode the promo touches counts, not just the first. A
        # stitched promo that borrows its out-point from an episode already
        # in the list shows the editor the same moment twice.
        keys = c.episodes
        if all(used.get(k, 0) < per_episode for k in keys):
            for k in keys:
                used[k] = used.get(k, 0) + 1
            head.append(c)
        else:
            tail.append(c)
    return head + tail


def find_candidates(episodes: list[Episode], weights: Weights | None = None,
                    per_episode: int = 3, stitched: int = 6) -> list[Candidate]:
    """Every episode's best few, plus a handful of stitched pairs."""
    weights = weights or Weights()
    seen = _first_seen(episodes)
    out: list[Candidate] = []
    for ep in episodes:
        best = suppress(candidates_for_episode(ep, weights, seen), limit=per_episode)
        out.extend(best)
    out.extend(stitched_candidates(episodes, stitched, weights, seen))
    out.sort(key=lambda c: -c.score)
    return out
