"""
The model layer: taste, and nothing else.

Two rules shape this file.

**The model never emits a timestamp.** It is shown a window the parser
already chose, with the real script text inside it, and asked only to
judge it. Every number that reaches an editor was computed from the
screenplay by `parse.py`. This is not a prompt asking the model to behave -
a hallucinated cut point is structurally unable to exist, because there is
no field for the model to put one in.

**The model is swappable.** The brief says stronger models may be wired in
later, so the provider is one environment variable and every adapter
returns the same `Verdict`. The default adapter speaks the OpenAI
chat-completions shape, which covers OpenAI, Groq, Together, OpenRouter,
DeepSeek, Fireworks, vLLM and a local Ollama without changing a line.

And if there is no key at all, `OfflineJudge` runs instead and the pipeline
still completes end to end - the rules alone produce a full ranked cut
list. The model improves the ordering; it is not load-bearing.

Standard library only: no dependency to install before this runs.
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass, field

from .candidates import Candidate
from .parse import to_stamp

TIMEOUT = 60


@dataclass
class Verdict:
    """What the model is allowed to say. Note the absence of any timestamp."""

    hook: float          # 0-10, does it stop a thumb in 3 seconds
    cliff: float         # 0-10, does it break off before the answer
    standalone: float    # 0-10, can a stranger follow it
    why: str             # one line, for the editor
    caption: str         # a posting caption
    risk: str = ""       # what might be wrong with this pick
    model: str = "offline"
    raw: str = ""

    @property
    def mean(self) -> float:
        return (self.hook + self.cliff + self.standalone) / 30.0

    def to_dict(self) -> dict:
        return {
            "hook": self.hook, "cliff": self.cliff, "standalone": self.standalone,
            "why": self.why, "caption": self.caption, "risk": self.risk, "model": self.model,
        }


def render(cand: Candidate) -> str:
    """The clip as the model sees it: the real beats, in order, with times."""
    lines = []
    for seg in cand.segments:
        lines.append(f"[segment: episode {seg.episode}, {to_stamp(seg.start)} to {to_stamp(seg.end)}]")
        for b in cand.beats:
            if b.episode != seg.episode or b.end <= seg.start or b.start >= seg.end:
                continue
            at = to_stamp(b.start)
            if b.kind == "DIALOGUE":
                emo = f" ({', '.join(b.emotions)})" if b.emotions else ""
                lines.append(f'  {at} {b.speaker}{emo}: "{b.text}"')
            else:
                lines.append(f"  {at} [{b.kind.lower()}] {b.text}")
    return "\n".join(lines)


SYSTEM = """You are a promo editor for vertical microdrama - the 1-2 minute \
serialised shows on apps like ReelShort, DramaBox and Kuku TV. You have cut \
thousands of 20-60 second social promos for Instagram Reels, TikTok and YouTube \
Shorts, and you know that almost all of them are lost in the first three seconds.

You will be shown one candidate promo: the exact screenplay beats inside a clip \
that has already been cut. The cut points are fixed and are not yours to change. \
Judge only what is there.

Score three things, each 0-10, and be hard to please. A 7 should be rare.

HOOK - would a stranger mid-scroll stop within the first three seconds? A slap, \
a scream, an accusation, a reveal, a question that demands an answer. Beautiful \
scenery is a 1. Someone saying hello is a 2.

CLIFF - does it break off before the moment resolves, leaving a question the \
viewer needs the app to answer? A clip that finishes its own thought is a 2, \
however good it was.

STANDALONE - could someone who has never seen this show follow it? Count the \
names they must track and the events referred to that they have not seen. Two \
people in a clear confrontation is a 9. Five names and a reference to a will \
read in episode 12 is a 2.

Then write:
WHY - one sentence, under 20 words, that an editor would accept. Concrete. Name \
the actual moment, not the genre.
CAPTION - the line you would post with it, under 12 words, in the voice of the \
genre.
RISK - the strongest argument against posting this, under 15 words. If there is \
none, say "none".

Reply with JSON only: \
{"hook":n,"cliff":n,"standalone":n,"why":"...","caption":"...","risk":"..."}"""


# --- adapters ---------------------------------------------------------------


class JudgeError(RuntimeError):
    """
    A provider call that did not come back usable.

    Worth its own type rather than leaking urllib's: the review loop has to
    decide whether to drop one promo's review or give up, and that decision
    should not depend on remembering every exception class a transport can
    raise. Everything in here that means "no verdict this time" raises this.
    """


def _post(url: str, payload: dict, headers: dict) -> dict:
    body = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json", **headers})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as err:
        # An HTTPError is itself an open response. Closing it stops a provider
        # having a bad afternoon from leaking a socket per rejected promo, and
        # carries the provider's own message into the log instead of a bare
        # status code.
        with err:
            detail = err.read().decode("utf-8", "replace").strip()[:200]
        raise JudgeError(f"HTTP {err.code} from {url}: {detail}") from None


def _extract_json(text: str) -> dict:
    """Models wrap JSON in prose and fences however firmly you ask them not to."""
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    depth, start = 0, None
    for i, ch in enumerate(text):
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and start is not None:
                try:
                    return json.loads(text[start:i + 1])
                except json.JSONDecodeError:
                    start = None
    raise ValueError(f"no JSON object in model reply: {text[:160]!r}")


class OfflineJudge:
    """
    No API key, no network. Verdicts derived from the rule signals.

    This exists so the tool has no hard dependency on anyone's billing. It
    is also the control condition in the evaluation: it is how we measure
    what the model is actually adding.
    """

    name = "offline"

    def judge(self, cand: Candidate) -> Verdict:
        s = cand.scores
        hook_text = (cand.hook_beat.text[:60] + "...") if cand.hook_beat else "the opening beat"
        return Verdict(
            hook=round(s["hook"] * 10, 1),
            cliff=round(s["cliff"] * 10, 1),
            standalone=round(s["standalone"] * 10, 1),
            why=f"Opens on {hook_text.lower()} and cuts before it is answered.",
            caption="",
            risk="scored by rules only - no model review",
            model="offline",
        )


class ChatJudge:
    """
    Any OpenAI-compatible `/chat/completions` endpoint.

    Set three variables and it points anywhere:
        CUTLIST_BASE_URL   https://api.openai.com/v1
                           https://api.groq.com/openai/v1
                           http://localhost:11434/v1        (Ollama, free)
        CUTLIST_MODEL      gpt-4o-mini | llama-3.3-70b-versatile | qwen2.5
        CUTLIST_API_KEY
    """

    def __init__(self, base_url: str, model: str, api_key: str):
        self.base_url, self.model, self.api_key = base_url.rstrip("/"), model, api_key
        self.name = f"chat:{model}"

    def judge(self, cand: Candidate) -> Verdict:
        data = _post(
            f"{self.base_url}/chat/completions",
            {
                "model": self.model,
                "temperature": 0.2,
                "messages": [
                    {"role": "system", "content": SYSTEM},
                    {"role": "user", "content": render(cand)},
                ],
            },
            {"Authorization": f"Bearer {self.api_key}"},
        )
        text = data["choices"][0]["message"]["content"]
        return _to_verdict(text, self.name)


class AnthropicJudge:
    def __init__(self, model: str, api_key: str):
        self.model, self.api_key = model, api_key
        self.name = f"anthropic:{model}"

    def judge(self, cand: Candidate) -> Verdict:
        data = _post(
            "https://api.anthropic.com/v1/messages",
            {
                "model": self.model, "max_tokens": 700, "temperature": 0.2,
                "system": SYSTEM,
                "messages": [{"role": "user", "content": render(cand)}],
            },
            {"x-api-key": self.api_key, "anthropic-version": "2023-06-01"},
        )
        return _to_verdict(data["content"][0]["text"], self.name)


class GeminiJudge:
    def __init__(self, model: str, api_key: str):
        self.model, self.api_key = model, api_key
        self.name = f"gemini:{model}"

    def judge(self, cand: Candidate) -> Verdict:
        url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
               f"{self.model}:generateContent?key={self.api_key}")
        data = _post(
            url,
            {
                "systemInstruction": {"parts": [{"text": SYSTEM}]},
                "contents": [{"parts": [{"text": render(cand)}]}],
                "generationConfig": {"temperature": 0.2},
            },
            {},
        )
        return _to_verdict(data["candidates"][0]["content"]["parts"][0]["text"], self.name)


def _to_verdict(text: str, model: str) -> Verdict:
    obj = _extract_json(text)

    def num(key: str) -> float:
        try:
            return max(0.0, min(10.0, float(obj.get(key, 0))))
        except (TypeError, ValueError):
            return 0.0

    return Verdict(
        hook=num("hook"), cliff=num("cliff"), standalone=num("standalone"),
        why=str(obj.get("why", "")).strip(),
        caption=str(obj.get("caption", "")).strip(),
        risk=str(obj.get("risk", "")).strip(),
        model=model, raw=text,
    )


def get_judge(provider: str | None = None):
    """
    Pick an adapter from the environment. Falls back to offline, loudly.

        CUTLIST_PROVIDER = offline | chat | anthropic | gemini
    """
    provider = (provider or os.environ.get("CUTLIST_PROVIDER") or "").strip().lower()
    key = os.environ.get("CUTLIST_API_KEY", "").strip()
    model = os.environ.get("CUTLIST_MODEL", "").strip()

    if provider in ("", "offline") or not key:
        return OfflineJudge()
    if provider == "anthropic":
        return AnthropicJudge(model or "claude-sonnet-5", key)
    if provider == "gemini":
        return GeminiJudge(model or "gemini-2.0-flash", key)
    base = os.environ.get("CUTLIST_BASE_URL", "https://api.openai.com/v1")
    return ChatJudge(base, model or "gpt-4o-mini", key)


def judge_all(cands: list[Candidate], judge=None, limit: int = 25,
              blend: float = 0.5, on_event=None) -> list[tuple[Candidate, Verdict]]:
    """
    Review the top `limit` candidates and re-rank.

    Only the shortlist is sent. Scoring all 156 windows with a model would
    cost 6x more and change nothing: the rules are reliable at throwing away
    the obviously weak, and unreliable only near the top, which is exactly
    where the model is spent.

    A failed call is not fatal - that candidate keeps its rule score and the
    failure is recorded on it, so a flaky key degrades the ranking instead of
    emptying it.
    """
    judge = judge or get_judge()
    offline = isinstance(judge, OfflineJudge)
    out: list[tuple[Candidate, Verdict]] = []

    for i, cand in enumerate(cands):
        if i >= limit:
            out.append((cand, OfflineJudge().judge(cand)))
            continue
        try:
            verdict = judge.judge(cand)
        except (JudgeError, urllib.error.URLError, KeyError, ValueError, TimeoutError) as exc:
            verdict = OfflineJudge().judge(cand)
            verdict.risk = f"model review failed ({exc}); rule score only"[:160]
        if on_event:
            on_event(i + 1, min(limit, len(cands)), verdict)
        out.append((cand, verdict))

    for cand, verdict in out:
        cand.model = verdict.to_dict()
        cand.final = round(cand.score if offline else (1 - blend) * cand.score + blend * verdict.mean, 4)

    out.sort(key=lambda cv: -cv[0].final)
    return out
