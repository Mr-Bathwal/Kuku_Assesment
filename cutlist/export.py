"""
Output in the shapes the work actually arrives in.

Four of them, because "the output" is different depending on who is holding
it: an editor wants something to drop into Premiere, a marketing lead wants
a spreadsheet to plan a week of posts, the review UI wants JSON, and a
human reading the submission wants prose.

The EDL is the one worth explaining. CMX3600 is the interchange format
every NLE has imported since 1980 - Premiere, Resolve, Avid, Final Cut. An
editor opens it and the in- and out-points are already on their timeline,
named, in order. It is the difference between a tool that gives you a list
of numbers to retype and a tool that gives you a sequence.
"""

from __future__ import annotations

import csv
import json
import math
from pathlib import Path

from .candidates import Candidate
from .parse import ACTION, CAMERA, DIALOGUE, SFX, Episode, to_stamp
from .signals import signal_episode

FPS = 30            # EDL timecode base; microdrama masters are 30p


def _tc(seconds: float) -> str:
    """Seconds -> HH:MM:SS:FF, non-drop."""
    total = int(round(seconds * FPS))
    f = total % FPS
    s = (total // FPS) % 60
    m = (total // (FPS * 60)) % 60
    h = total // (FPS * 3600)
    return f"{h:02d}:{m:02d}:{s:02d}:{f:02d}"


PROFILE_STEP = 1.0     # one sample per second of screen time
_ENVELOPE_CACHE: dict[int, list[int]] = {}


def _envelope(episode: Episode) -> list[int]:
    """
    An episode's pressure curve: the highest stop-power of any beat live in
    each second, 0-100.

    This exists so the review UI can draw an episode the way an editor reads
    one - as a shape with peaks and flats - rather than as a row of text. It
    is the same number the ranker uses, downsampled, so what the UI draws and
    what the scorer decided cannot drift apart.
    """
    # to_json runs twice per invocation (the top list and all candidates) over
    # the same episode objects; the curve is identical both times.
    hit = _ENVELOPE_CACHE.get(id(episode))
    if hit is not None:
        return hit

    n = max(1, int(math.ceil(episode.duration / PROFILE_STEP)))
    env = [0.0] * n
    for sig in signal_episode(episode):
        lo = max(0, int(sig.beat.start // PROFILE_STEP))
        hi = min(n - 1, int(max(sig.beat.start, sig.beat.end - 1e-6) // PROFILE_STEP))
        for i in range(lo, hi + 1):
            if sig.stop_power > env[i]:
                env[i] = sig.stop_power
    curve = [int(round(v * 100)) for v in env]
    _ENVELOPE_CACHE[id(episode)] = curve
    return curve


def _legal_lattice(episode: Episode) -> list[int]:
    """
    Every in-point this episode actually permits, in tenths of a second.

    The UI draws this against `int(duration / 0.1)` expressible timestamps to
    show the size of the target a free-text model is asked to hit. Shipping the
    lattice itself rather than a summary percentage means the picture on screen
    is the constraint, not an illustration of it.
    """
    return sorted({int(round(b.start * 10)) for b in episode.beats})


def _mix(episode: Episode) -> dict:
    """Beat counts per kind - what an episode is mostly made of."""
    counts = {DIALOGUE: 0, ACTION: 0, CAMERA: 0, SFX: 0}
    for b in episode.beats:
        if b.kind in counts:
            counts[b.kind] += 1
    return counts


def to_json(cands: list[Candidate], episodes: list[Episode], meta: dict) -> dict:
    by_no = {e.number: e for e in episodes}
    out = []
    for rank, c in enumerate(cands, 1):
        model = getattr(c, "model", None)
        out.append({
            "rank": rank,
            "id": f"P{rank:03d}",
            "kind": c.kind,
            "duration": round(c.duration, 2),
            "segments": [s.to_dict() for s in c.segments],
            "episodes": c.episodes,
            "score_rules": c.score,
            "score_final": getattr(c, "final", c.score),
            "scores": c.scores,
            "model": model,
            "hook": {
                "at": to_stamp(c.hook_beat.start), "episode": c.hook_beat.episode,
                "kind": c.hook_beat.kind, "speaker": c.hook_beat.speaker,
                "emotions": c.hook_beat.emotions, "text": c.hook_beat.text,
            } if c.hook_beat else None,
            "cliff": {
                "at": to_stamp(c.cliff_beat.end), "episode": c.cliff_beat.episode,
                "kind": c.cliff_beat.kind, "speaker": c.cliff_beat.speaker,
                "text": c.cliff_beat.text,
            } if c.cliff_beat else None,
            "characters": c.characters,
            "reasons": c.reasons,
            "beats": [b.to_dict() for b in c.beats],
        })
    # The hallucination-surface numbers ship inside the payload so the write-up
    # and the UI quote the same figure from the same run, instead of one of them
    # quoting a number somebody typed.
    from .evaluate import legal_fraction
    meta = dict(
        meta,
        grounding=legal_fraction(episodes),
        corpus={
            "emotion_tags": len({t for e in episodes for b in e.beats for t in b.emotions}),
            "speakers": len({b.speaker for e in episodes for b in e.beats if b.speaker}),
            "scenes": sum(len(e.scenes) for e in episodes),
        },
    )

    return {
        "meta": meta,
        "episodes": [
            {
                "number": e.number, "duration": round(e.duration, 2),
                "duration_tc": to_stamp(e.duration), "logline": e.logline,
                "scenes": len(e.scenes), "beats": len(e.beats),
                "characters": sorted(x for x in e.characters if x),
                "mix": _mix(e),
                "starts": _legal_lattice(e),
                "expressible": int(e.duration / 0.1),
                "profile": _envelope(e),
                "profile_step": PROFILE_STEP,
            }
            for e in sorted(by_no.values(), key=lambda e: e.number)
        ],
        "promos": out,
    }


def write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def write_csv(path: Path, cands: list[Candidate]) -> None:
    """The sheet a marketing lead schedules a week of posts from."""
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow([
            "rank", "promo_id", "type", "episodes", "segments", "duration_s",
            "score", "hook_score", "cliff_score", "standalone_score",
            "hook_line", "cliff_line", "characters", "why", "risk",
        ])
        for rank, c in enumerate(cands, 1):
            segs = " + ".join(
                f"EP{s.episode} {to_stamp(s.start)}-{to_stamp(s.end)}" for s in c.segments
            )
            model = getattr(c, "model", {}) or {}
            w.writerow([
                rank, f"P{rank:03d}", c.kind,
                "/".join(str(e) for e in c.episodes), segs, f"{c.duration:.1f}",
                f"{getattr(c, 'final', c.score):.3f}",
                c.scores["hook"], c.scores["cliff"], c.scores["standalone"],
                (c.hook_beat.text if c.hook_beat else ""),
                (c.cliff_beat.text if c.cliff_beat else ""),
                ", ".join(c.characters),
                model.get("why", ""), model.get("risk", ""),
            ])


def write_edl(path: Path, cand: Candidate, rank: int, show: str) -> None:
    """
    One CMX3600 edit decision list per promo: importable into any NLE.

    Record time runs continuously from zero, so a stitched promo arrives as
    two clips already butted together on the timeline in the right order.
    """
    lines = [f"TITLE: {show} PROMO P{rank:03d}", "FCM: NON-DROP FRAME", ""]
    record = 0.0
    for i, seg in enumerate(cand.segments, 1):
        reel = f"EP{seg.episode:03d}"
        lines.append(
            f"{i:03d}  {reel:<8} V     C        "
            f"{_tc(seg.start)} {_tc(seg.end)} {_tc(record)} {_tc(record + seg.duration)}"
        )
        lines.append(f"* FROM CLIP NAME: {show} EPISODE {seg.episode}")
        record += seg.duration
    if cand.hook_beat:
        lines.append(f"* HOOK: {cand.hook_beat.text[:70]}")
    if cand.cliff_beat:
        lines.append(f"* OUT ON: {cand.cliff_beat.text[:70]}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_cutsheet(path: Path, cands: list[Candidate], show: str, meta: dict) -> None:
    """The human-readable version: what an editor reads before opening the NLE."""
    L = [
        f"# {show} - promo cut sheet", "",
        f"{len(cands)} promos from {meta.get('episodes', '?')} episodes "
        f"({meta.get('runtime_min', '?')} min of screenplay). "
        f"Scored by rules, reviewed by `{meta.get('model', 'offline')}`.", "",
        "Every timestamp below is a beat boundary taken from the screenplay. "
        "Nothing here was written by a language model except the *why* and the caption.",
        "",
    ]
    for rank, c in enumerate(cands, 1):
        model = getattr(c, "model", {}) or {}
        segs = " + ".join(
            f"**EP{s.episode}** `{to_stamp(s.start)} - {to_stamp(s.end)}`" for s in c.segments
        )
        L += [
            f"## P{rank:03d} - {c.duration:.0f}s - score {getattr(c, 'final', c.score):.3f}",
            "", f"{segs}  ({c.kind})", "",
            f"- **Hook** ({to_stamp(c.hook_beat.start)}): {c.hook_beat.text}" if c.hook_beat else "- **Hook**: -",
            f"- **Out on** ({to_stamp(c.cliff_beat.end)}): {c.cliff_beat.text}" if c.cliff_beat else "- **Out on**: -",
            f"- **Cast in clip**: {', '.join(c.characters) or 'none speaking'}",
            f"- **Why**: {model.get('why') or c.reasons[0] if c.reasons else ''}",
        ]
        if model.get("caption"):
            L.append(f"- **Caption**: {model['caption']}")
        if model.get("risk") and model["risk"].lower() != "none":
            L.append(f"- **Risk**: {model['risk']}")
        L += [
            "- **Scores**: " + "  ".join(f"{k} {v:.2f}" for k, v in c.scores.items()),
            "",
        ]
    path.write_text("\n".join(L), encoding="utf-8")
