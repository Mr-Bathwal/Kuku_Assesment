"""
Beat-level signals: the part that is rules, not model.

The split this whole tool rests on: *taste* is a language-model job, but
*arithmetic* is not. Where a clip starts and stops, how much dialogue is in
it, how many people a stranger has to keep track of, whether the last line
is a question - all of that is countable, and counting it is free, instant,
reproducible and impossible to hallucinate. The model is spent only on the
handful of judgements counting cannot make.

Every lexicon below was built by reading this corpus, not guessed: the
emotion vocabulary is the 620 distinct actor directions the screenplays
actually use, and the action verbs are the ones that actually appear. Each
signal records *which beat fired it*, so a score can always be opened up and
argued with - by me, or by the editor who disagrees with it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .parse import ACTION, CAMERA, DIALOGUE, SFX, Beat, Episode

# --- lexicons ---------------------------------------------------------------
# Weights are 0-1 "how hard does this stop a thumb". Tuned by hand against
# the first ten episodes, then left alone so later episodes stay a fair test.

SHOCK_ACTION = {
    # physical violence - the strongest scroll-stoppers in the genre
    "slap": 1.00, "strikes": 0.95, "strike": 0.95, "struck": 0.90, "stab": 1.00,
    "stabs": 1.00, "stabbed": 0.95, "blood": 0.90, "bleeding": 0.85, "wound": 0.60,
    "punch": 0.95, "grabs": 0.70, "grab": 0.70, "shoves": 0.80, "shove": 0.80,
    "throws": 0.70, "hurls": 0.80, "slams": 0.80, "slam": 0.80, "chokes": 0.95,
    "drags": 0.70, "kicks": 0.80, "whip": 0.90, "sword": 0.70, "dagger": 0.85,
    "blade": 0.75, "gun": 0.90, "collapses": 0.85, "collapse": 0.85, "faints": 0.80,
    "falls": 0.50, "crashes": 0.70, "shatters": 0.70, "burns": 0.60, "fire": 0.50,
    # social violence - humiliation and exposure, the genre's other engine
    "kneels": 0.65, "kneel": 0.65, "tears": 0.45, "rips": 0.70, "spits": 0.85,
    "screams": 0.90, "scream": 0.90, "shouts": 0.60, "weeps": 0.45, "sobs": 0.50,
    "trembling": 0.20, "flinches": 0.45, "recoils": 0.55, "gasps": 0.50,
    "storms": 0.55, "seizes": 0.70, "snatches": 0.65, "pins": 0.60,
}

# Lexicons collide with ordinary English, and on this corpus the collisions
# were not hypothetical: "He strikes flint and steel together over dry
# kindling" scored as hard as a slap and put a man lighting a campfire at
# the top of the promo list. A verb is only violence when it lands on a
# person. These are the objects it lands on instead.
BENIGN_OBJECT = re.compile(
    r"\b(flint|kindling|tinder|match|candle|lantern|hearth|fireplace|"
    r"bell|gong|clock|chime|anvil|nail|dough|drum|chord|string|lute|"
    r"tent|post|stake|oar|loom)\b"
)

# ...but a courtroom gavel or a fist on a table is theatre, and plays.
LOUD_PROP = re.compile(r"\b(gavel|table|door|wall|desk|glass|goblet|mirror|window)\b")

# Words that, inside a spoken line, mean something is being disclosed or
# detonated. A promo lives on these.
REVEAL = {
    "truth": 0.80, "lied": 0.85, "lying": 0.80, "liar": 0.90, "secret": 0.85,
    "betrayed": 0.90, "betrayal": 0.85, "traitor": 0.90, "murdered": 0.95,
    "murder": 0.90, "killed": 0.90, "kill": 0.75, "poison": 0.85, "poisoned": 0.90,
    "alive": 0.80, "dead": 0.70, "died": 0.65, "pregnant": 0.95, "child": 0.45,
    "father": 0.40, "mother": 0.40, "husband": 0.45, "wife": 0.45, "bastard": 0.80,
    "heir": 0.70, "inheritance": 0.65, "will": 0.20, "proof": 0.75, "evidence": 0.75,
    "confess": 0.85, "confession": 0.85, "admit": 0.65, "knew": 0.60, "know": 0.30,
    "never": 0.35, "divorce": 0.80, "annul": 0.80, "marry": 0.55, "marriage": 0.50,
    "disgrace": 0.70, "ruin": 0.70, "ruined": 0.75, "shame": 0.65,
    "scandal": 0.80, "witness": 0.70, "trial": 0.70, "guilty": 0.80, "innocent": 0.75,
}

THREAT = {
    "regret": 0.85, "warned": 0.70, "warning": 0.65, "pay": 0.60, "revenge": 0.90,
    "destroy": 0.85, "finished": 0.70, "over": 0.30, "leave": 0.35, "get out": 0.70,
    "how dare": 0.85, "never forgive": 0.85, "or else": 0.80, "last time": 0.70,
    "swear": 0.65, "promise you": 0.60, "mine": 0.45, "belongs to me": 0.80,
}

# The visual grammar of "we cut here".
#
# This lexicon exists because of a measured failure, not a hunch. The first
# version of the cliffhanger scorer only read dialogue and sound, and when
# it was finally run against six promos cut by hand it scored 0.00 on every
# single out-point - because in a screenplay the last thing before a cut is
# almost always a camera direction. "Push-in close-up on her stricken face"
# *is* the cliffhanger; the shot holding on a reaction is how the form says
# "you do not get the answer".
CLIFF_VISUAL = {
    "cut to black": 1.00, "fade to black": 0.95, "smash cut": 0.85,
    "push-in": 0.75, "push in": 0.75, "extreme close-up": 0.80,
    "macro close-up": 0.80, "tight close-up": 0.75, "close-up": 0.55,
    "slowly": 0.35, "freeze": 0.80, "holds": 0.45, "lingers": 0.60,
    "widening": 0.65, "wide eyes": 0.70, "widen": 0.65, "trembling": 0.50,
    "stricken": 0.75, "stares": 0.60, "staring": 0.55, "turning toward": 0.55,
    "turns toward": 0.55, "silhouette": 0.50, "shadow": 0.40,
    "unreadable": 0.70, "darkens": 0.60, "hardening": 0.65, "dawning": 0.70,
}

# Sound cues the screenplays use when a scene is being left unresolved.
CLIFF_SFX = {
    "cliffhanger": 1.00, "unresolved": 0.95, "ominous": 0.70, "sting": 0.75,
    "swell": 0.55, "abrupt": 0.70, "silence": 0.55, "drone": 0.50, "tense": 0.50,
    "thunderous": 0.60, "cut to black": 1.00, "crash": 0.70, "crashes": 0.70,
    "shatter": 0.65, "shattering": 0.65, "explosion": 0.85, "detonation": 0.90,
    "scream": 0.70, "gunshot": 0.90, "slam": 0.60,
}

# Warmth and closure. At an out-point these are poison: the viewer has no
# reason to open the app.
RESOLUTION = {
    "smiles": 0.70, "smile": 0.65, "embrace": 0.85, "embraces": 0.85, "kiss": 0.50,
    "laughs": 0.60, "laughing": 0.60, "thank you": 0.70, "safe": 0.60, "forgive": 0.55,
    "relieved": 0.70, "peaceful": 0.70, "gently": 0.40, "reassuring": 0.65,
    "warmly": 0.70, "tenderly": 0.60, "content": 0.60, "at last": 0.50, "finally": 0.40,
    "it is over": 0.80, "settled": 0.60, "agreed": 0.45,
}

# Actor directions, graded. These come straight from the parenthetical tags.
HOT_EMOTION = {
    "screaming": 1.00, "shouting": 0.85, "furious": 0.90, "venomous": 0.90,
    "cruel": 0.85, "threatening": 0.90, "enraged": 0.95, "seething": 0.85,
    "cold": 0.70, "icy": 0.75, "steely": 0.65, "defiant": 0.80, "fierce": 0.80,
    "desperate": 0.80, "pleading": 0.70, "heartbroken": 0.75, "anguished": 0.80,
    "weeping": 0.70, "tearful": 0.65, "trembling": 0.60, "horrified": 0.90,
    "shocked": 0.85, "incredulous": 0.75, "stunned": 0.80, "accusatory": 0.85,
    "mocking": 0.75, "scornful": 0.75, "smug": 0.65, "contemptuous": 0.75,
    "commanding": 0.60, "authoritative": 0.55, "grave": 0.55, "ominous": 0.70,
    "urgent": 0.70, "breathless": 0.60, "resolute": 0.55, "sinister": 0.85,
    "dismissive": 0.55, "bitter": 0.65, "sharp": 0.55, "demanding": 0.60,
    # the cold end of the scale: calm, soft, warm - fine drama, weak hook
    "gentle": 0.10, "soft": 0.10, "warm": 0.10, "tender": 0.10, "calm": 0.15,
    "sincere": 0.20, "quiet": 0.20, "reassuring": 0.10, "amused": 0.30,
}

# Phrases that point at something the viewer has not seen. Each one is a
# small debt the clip owes a stranger.
CONTEXT_DEBT = [
    r"\bafter what\b", r"\bremember when\b", r"\bthat night\b", r"\blast time\b",
    r"\bas i told you\b", r"\byou promised\b", r"\bsince the\b", r"\bback then\b",
    r"\bthe letter\b", r"\bthe will\b", r"\byour brother\b", r"\bmy brother\b",
    r"\bthe war\b", r"\bthe battle\b", r"\bagain\b", r"\bstill\b",
]

_WORD = re.compile(r"[a-z']+")


def _lex_hits(text: str, lex: dict[str, float]) -> list[tuple[str, float]]:
    """
    Every lexicon term present, with its weight.

    Multi-word *and hyphenated* terms are matched as substrings. The hyphen
    case is not a detail: the word tokeniser splits on punctuation, so
    "push-in" was being looked up as a single token that the tokeniser could
    never produce, and every hyphenated entry in the visual lexicon -
    "close-up", "extreme close-up", "push-in", nearly all of them - was dead
    weight that silently matched nothing.
    """
    low = text.lower()
    words = set(_WORD.findall(low))
    hits = []
    for term, weight in lex.items():
        compound = " " in term or "-" in term
        if (compound and term in low) or (not compound and term in words):
            hits.append((term, weight))
    return hits


def _top(hits: list[tuple[str, float]]) -> float:
    """One strong hit should count more than four weak ones, but not four times."""
    if not hits:
        return 0.0
    ranked = sorted((w for _, w in hits), reverse=True)
    return min(1.0, ranked[0] + sum(ranked[1:]) * 0.18)


# --- per-beat features ------------------------------------------------------


@dataclass
class BeatSignal:
    """What one beat contributes, and why. `why` is shown to the editor."""

    beat: Beat
    shock: float = 0.0        # physical or social violence on screen
    reveal: float = 0.0       # something is disclosed
    threat: float = 0.0       # menace in the line
    heat: float = 0.0         # emotional temperature of the delivery
    question: float = 0.0     # the line ends unanswered
    cliff_sfx: float = 0.0    # sound cue marking an unresolved beat
    cliff_visual: float = 0.0 # the shot itself says "we cut here"
    resolution: float = 0.0   # warmth / closure (a penalty at an out-point)
    debt: float = 0.0         # references to things a stranger has not seen
    why: list[str] = field(default_factory=list)

    @property
    def stop_power(self) -> float:
        """
        How hard this single beat would stop a thumb, 0-1.

        Scored per kind, which matters more than it sounds. A first version
        summed all the axes for every beat, so a line could never score
        highly because `shock` only fires on physical action - and the
        corpus's most violent line, screamed, came out at 0.22, below a
        murmured question. A beat is only ever one kind of thing; it should
        be judged on the axes that kind can actually express.
        """
        if self.beat.kind == DIALOGUE:
            punch = 0.0
            if "!" in self.beat.text:
                punch += 0.12
            if self.beat.words <= 6 and self.heat >= 0.6:
                punch += 0.10          # short and hot: the genre's native register
            return min(
                1.0,
                0.46 * self.heat
                + 0.42 * self.reveal
                + 0.34 * self.threat
                + 0.16 * self.question
                + punch,
            )
        if self.beat.kind in (ACTION, CAMERA):
            return min(1.0, self.shock * 1.15)
        return min(1.0, self.cliff_sfx * 0.6)


def signal_beat(beat: Beat) -> BeatSignal:
    sig = BeatSignal(beat=beat)
    text = beat.text

    if beat.kind in (ACTION, CAMERA):
        hits = _lex_hits(text, SHOCK_ACTION)
        sig.shock = _top(hits) * (1.0 if beat.kind == ACTION else 0.55)
        low_t = text.lower()
        if hits and BENIGN_OBJECT.search(low_t):
            sig.shock *= 0.15                      # a campfire, not a fight
            sig.why.append("violent verb on a harmless object - discounted")
        elif hits and LOUD_PROP.search(low_t):
            sig.shock *= 0.75                      # hits furniture: still theatre
        if hits:
            sig.why.append(f"{beat.kind.lower()}: {', '.join(t for t, _ in sorted(hits, key=lambda h: -h[1])[:3])}")
        res = _lex_hits(text, RESOLUTION)
        sig.resolution = _top(res)
        sig.cliff_visual = _top(_lex_hits(text, CLIFF_VISUAL))
        if sig.cliff_visual >= 0.7:
            sig.why.append("the shot holds on an unresolved reaction")

    elif beat.kind == DIALOGUE:
        rev = _lex_hits(text, REVEAL)
        thr = _lex_hits(text, THREAT)
        sig.reveal, sig.threat = _top(rev), _top(thr)
        sig.heat = max((HOT_EMOTION.get(e, 0.3) for e in beat.emotions), default=0.3)
        if text.strip().endswith("?"):
            sig.question = 1.0
        sig.resolution = _top(_lex_hits(text, RESOLUTION))
        if rev:
            sig.why.append(f"reveal: {', '.join(t for t, _ in sorted(rev, key=lambda h: -h[1])[:2])}")
        if thr:
            sig.why.append(f"threat: {', '.join(t for t, _ in sorted(thr, key=lambda h: -h[1])[:2])}")
        hot = [e for e in beat.emotions if HOT_EMOTION.get(e, 0) >= 0.7]
        if hot:
            sig.why.append(f"delivery: {', '.join(hot[:2])}")

    elif beat.kind == SFX:
        sig.cliff_sfx = _top(_lex_hits(text, CLIFF_SFX))
        # A beam coming down is an event, not ambience. Sound was the only
        # beat kind never scored for shock, so episode 18's falling roof -
        # unmistakably the cut point - registered as nothing at all.
        sig.shock = _top(_lex_hits(text, SHOCK_ACTION)) * 0.8
        if sig.cliff_sfx >= 0.7:
            sig.why.append("sound cue marks an unresolved beat")

    low = text.lower()
    sig.debt = min(1.0, sum(0.34 for p in CONTEXT_DEBT if re.search(p, low)))
    return sig


def signal_episode(episode: Episode) -> list[BeatSignal]:
    return [signal_beat(b) for b in episode.beats]
