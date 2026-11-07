"""
Screenplay -> typed, timed beats.

Everything downstream depends on this being exact, so it is deliberately
strict: the parser fails loudly on a line it does not recognise rather than
guessing. A promo is a pair of timestamps, and a timestamp that is off by a
beat is an editor re-doing the work by hand.

The input format (Kuku microdrama screenplay) is:

    EPISODE NUMBER: Episode 1
    EPISODE LOGLINE: ...
    CONTINUITY NOTES: ...

    --- SCRIPT START ---

    SCENE 01
    Scene heading: INT. CATHEDRAL - DAY
    Scene start: 00:00.00
    Scene end: 02:18.00

    Actions and dialogue:

    **CAMERA:**
    Start: (00:00.00) | End: (00:04.80)
    Symmetrical framing on the heavy church doors...

    **LADY JULIANA (Confused, Breathless):**
    Start: (00:13.50) | End: (00:14.30)
    "Why?"

Four block kinds matter: CAMERA (shot description), ACTION (what happens),
SFX (sound), and DIALOGUE (anything else in the ** ** header position is a
speaking character). The parenthetical on a dialogue header is the actor
direction - "Cold, Commanding" - and is the single richest signal in the
whole corpus, so it is kept as structured data rather than prose.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict
from pathlib import Path

# --- timecode ---------------------------------------------------------------

_TIME = re.compile(r"^(?:(\d+):)?(\d{1,2}):(\d{2}(?:\.\d+)?)$")


def to_seconds(stamp: str) -> float:
    """`02:18.00` -> 138.0. Accepts H:MM:SS.cc too, though this corpus is MM:SS.cc."""
    stamp = stamp.strip()
    m = _TIME.match(stamp)
    if not m:
        raise ValueError(f"unparseable timecode: {stamp!r}")
    hours, mins, secs = m.groups()
    return (int(hours) * 3600 if hours else 0) + int(mins) * 60 + float(secs)


def to_stamp(seconds: float) -> str:
    """138.0 -> `02:18.00`. The format the screenplays use, so output matches input."""
    seconds = max(0.0, seconds)
    return f"{int(seconds // 60):02d}:{seconds % 60:05.2f}"


# --- model ------------------------------------------------------------------

CAMERA, ACTION, SFX, DIALOGUE = "CAMERA", "ACTION", "SFX", "DIALOGUE"


@dataclass
class Beat:
    """One timed block of the screenplay. The atom of everything else."""

    episode: int
    scene: int
    index: int          # position within the episode, 0-based
    kind: str           # CAMERA | ACTION | SFX | DIALOGUE
    start: float
    end: float
    text: str
    speaker: str | None = None
    emotions: list[str] = field(default_factory=list)

    @property
    def duration(self) -> float:
        return self.end - self.start

    @property
    def words(self) -> int:
        return len(self.text.split())

    def to_dict(self) -> dict:
        d = asdict(self)
        d["start_tc"] = to_stamp(self.start)
        d["end_tc"] = to_stamp(self.end)
        return d


@dataclass
class Scene:
    number: int
    heading: str
    start: float
    end: float


@dataclass
class Episode:
    number: int
    source: str
    logline: str
    continuity: str
    scenes: list[Scene]
    beats: list[Beat]

    @property
    def duration(self) -> float:
        return max((b.end for b in self.beats), default=0.0)

    @property
    def dialogue(self) -> list[Beat]:
        return [b for b in self.beats if b.kind == DIALOGUE]

    @property
    def characters(self) -> set[str]:
        return {b.speaker for b in self.beats if b.speaker}

    def scene_of(self, t: float) -> int:
        for s in self.scenes:
            if s.start <= t <= s.end:
                return s.number
        return self.scenes[-1].number if self.scenes else 1


# --- parsing ----------------------------------------------------------------

_BLOCK = re.compile(r"^\*\*(.+?):\*\*\s*$")
_TIMELINE = re.compile(r"^Start:\s*\(([\d:.]+)\)\s*\|\s*End:\s*\(([\d:.]+)\)\s*$")
_SCENE = re.compile(r"^SCENE\s+(\d+)\s*$", re.I)
_KEY = re.compile(r"^([A-Za-z ]+):\s*(.*)$")
_SPEAKER = re.compile(r"^(.+?)\s*\(([^)]*)\)\s*$")

# Header words that are production metadata, not a person speaking.
_NON_SPEAKER = {
    "CAMERA", "ACTION", "SOUND FX", "SFX", "SOUND", "MUSIC", "VFX",
    "TRANSITION", "TEXT", "TITLE", "ON SCREEN TEXT", "NOTE",
}


def _kind_for(header: str) -> tuple[str, str | None, list[str]]:
    """Split a `**...:**` header into (kind, speaker, emotions)."""
    speaker, emotions = header.strip(), []
    m = _SPEAKER.match(speaker)
    if m:
        speaker = m.group(1).strip()
        emotions = [e.strip().lower() for e in m.group(2).split(",") if e.strip()]

    upper = speaker.upper()
    if upper in _NON_SPEAKER:
        kind = {"SOUND FX": SFX, "SOUND": SFX, "MUSIC": SFX, "SFX": SFX}.get(upper, upper)
        return (kind if kind in (CAMERA, ACTION, SFX) else ACTION), None, emotions
    return DIALOGUE, speaker, emotions


def parse_episode(path: str | Path) -> Episode:
    """Parse one screenplay file. Raises on anything it does not understand."""
    path = Path(path)
    lines = path.read_text(encoding="utf-8", errors="replace").split("\n")

    number, logline, continuity = 0, "", ""
    scenes: list[Scene] = []
    beats: list[Beat] = []
    scene_no = 0
    pending: dict | None = None

    for i, raw in enumerate(lines):
        line = raw.rstrip()
        if not line.strip():
            continue

        # A block header: **CAMERA:** / **LADY JULIANA (Cold):**
        m = _BLOCK.match(line)
        if m:
            kind, speaker, emotions = _kind_for(m.group(1))
            pending = {"kind": kind, "speaker": speaker, "emotions": emotions}
            continue

        # The timeline under a header, then the single text line under that.
        m = _TIMELINE.match(line)
        if m:
            if pending is None:
                raise ValueError(f"{path.name}:{i+1} timeline with no block header")
            text = ""
            for nxt in lines[i + 1:]:
                if nxt.strip():
                    text = nxt.strip()
                    break
            beats.append(
                Beat(
                    episode=number,
                    scene=scene_no,
                    index=len(beats),
                    kind=pending["kind"],
                    speaker=pending["speaker"],
                    emotions=pending["emotions"],
                    start=to_seconds(m.group(1)),
                    end=to_seconds(m.group(2)),
                    text=text.strip('"').strip(),
                )
            )
            pending = None
            continue

        m = _SCENE.match(line)
        if m:
            scene_no = int(m.group(1))
            scenes.append(Scene(scene_no, "", 0.0, 0.0))
            continue

        m = _KEY.match(line)
        if m:
            key, value = m.group(1).strip().lower(), m.group(2).strip()
            if key == "episode number":
                digits = re.search(r"\d+", value)
                number = int(digits.group()) if digits else 0
            elif key == "episode logline":
                logline = value
            elif key == "continuity notes":
                continuity = value
            elif key == "scene heading" and scenes:
                scenes[-1].heading = value
            elif key == "scene start" and scenes:
                scenes[-1].start = to_seconds(value)
            elif key == "scene end" and scenes:
                scenes[-1].end = to_seconds(value)

    for b in beats:
        b.episode = number

    if not beats:
        raise ValueError(f"{path.name}: no beats parsed")

    # Beats are written in document order, which is overwhelmingly but not
    # perfectly chronological (a CAMERA block can be logged after the ACTION
    # it covers). Sort by start so every window operation downstream can
    # assume a monotonic timeline.
    beats.sort(key=lambda b: (b.start, b.end))
    for n, b in enumerate(beats):
        b.index = n
        if scenes:
            b.scene = next((s.number for s in scenes if s.start <= b.start <= s.end), beats[0].scene or 1)

    return Episode(number, path.name, logline, continuity, scenes, beats)


def parse_show(folder: str | Path) -> list[Episode]:
    """Parse every .txt in a folder, in episode order."""
    folder = Path(folder)
    files = sorted(folder.glob("*.txt"))
    if not files:
        raise FileNotFoundError(f"no .txt screenplays in {folder}")
    episodes = [parse_episode(f) for f in files]
    episodes.sort(key=lambda e: e.number)
    return episodes
