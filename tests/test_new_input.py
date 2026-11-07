"""
Does it work on a show it has never seen?

The brief says that if shortlisted, "you'll run your solution on a new input
during your interview". That is a claim about generalisation, and the only
honest way to make it is to keep a second show in the repo and run the whole
pipeline on it - different writers, different genre, different vocabulary,
nothing in the lexicons tuned for it.

`data/sample/` is three episodes of an original contemporary thriller I
wrote for this purpose. It is not Kuku's content, so unlike the input pack
it can live in a public repository, which also means anyone can clone this
and get a real run out of it without the confidential pack.

    python -m unittest tests.test_new_input -v
"""

from __future__ import annotations

import unittest
from pathlib import Path

from cutlist.candidates import MAX_LEN, MIN_LEN, diversify, find_candidates
from cutlist.export import to_json
from cutlist.judge import OfflineJudge, judge_all
from cutlist.parse import ACTION, CAMERA, DIALOGUE, SFX, parse_show
from cutlist.verify import check

SAMPLE = Path(__file__).resolve().parent.parent / "data" / "sample"


class ANewShow(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.episodes = parse_show(SAMPLE)
        cls.cands = diversify(find_candidates(cls.episodes))

    def test_it_parses_a_screenplay_it_was_not_written_against(self):
        self.assertEqual(len(self.episodes), 3)
        self.assertGreater(sum(len(e.beats) for e in self.episodes), 90)
        kinds = {b.kind for e in self.episodes for b in e.beats}
        self.assertEqual(kinds, {DIALOGUE, ACTION, CAMERA, SFX})

    def test_actor_directions_survive_on_a_different_writer(self):
        tagged = [b for e in self.episodes for b in e.beats
                  if b.kind == DIALOGUE and b.emotions]
        self.assertGreater(len(tagged), 20)

    def test_it_finds_promos_at_all(self):
        self.assertGreater(len(self.cands), 5)

    def test_the_guarantee_holds_on_unseen_input(self):
        """Every cut on a new show is still a real beat boundary."""
        self.assertEqual(check(self.cands, self.episodes), [])

    def test_lengths_are_still_inside_the_brief(self):
        for c in self.cands:
            self.assertGreaterEqual(c.duration, MIN_LEN - 0.01)
            self.assertLessEqual(c.duration, MAX_LEN + 0.01)

    def test_the_top_pick_opens_on_something_and_ends_unresolved(self):
        """
        Not a score threshold - a shape check. The best promo on this show
        should start on a beat the scorer actually flagged and end on one it
        read as unresolved, or the ranker is only sorting noise.
        """
        top = self.cands[0]
        self.assertIsNotNone(top.hook_beat)
        self.assertIsNotNone(top.cliff_beat)
        self.assertLessEqual(top.hook_beat.start, top.segments[0].start + 3.0 + 1e-6)
        self.assertGreater(top.scores["cliff"], 0.5)

    def test_a_full_run_exports_cleanly(self):
        reviewed = judge_all(self.cands, OfflineJudge(), limit=5)
        ranked = diversify([c for c, _ in reviewed])[:6]
        payload = to_json(ranked, self.episodes, {"show": "The Last Shift"})
        self.assertEqual(len(payload["promos"]), 6)
        for p in payload["promos"]:
            self.assertTrue(p["segments"])
            self.assertTrue(p["hook"]["text"])
            self.assertTrue(p["cliff"]["text"])
            self.assertTrue(p["reasons"])
        # and the page's data contract survives a different corpus
        for e in payload["episodes"]:
            self.assertEqual(sum(e["mix"].values()), e["beats"])
            self.assertTrue(e["profile"])
        g = payload["meta"]["grounding"]
        self.assertEqual(sum(len(e["starts"]) for e in payload["episodes"]),
                         g["beat_starts"])

    def test_no_lexicon_is_fitted_to_the_supplied_show(self):
        """
        The vocabulary the scorer actually matches on - not the prose around
        it - must contain nothing specific to one corpus. Introspecting the
        real objects rather than grepping the file matters: an illustrative
        comment mentioning a location is fine, a lexicon entry for it is the
        tool quietly learning one show by heart.

        This caught a real one. `"duke": 0.35` sat in the reveal lexicon,
        fitted to the period setting of the supplied pack and worth nothing
        on a contemporary thriller. Removing it changed the gold-set score by
        0.000, which is the tell that it was never earning its place.
        """
        import cutlist.signals as S

        vocabulary: set[str] = set()
        for name in dir(S):
            if not name.isupper():
                continue
            value = getattr(S, name)
            if isinstance(value, dict):
                vocabulary |= {str(k).lower() for k in value}
            elif isinstance(value, (list, tuple, set)):
                vocabulary |= {str(v).lower() for v in value if isinstance(v, str)}
            elif hasattr(value, "pattern"):
                vocabulary.add(value.pattern.lower())

        self.assertGreater(len(vocabulary), 150, "no lexicon was inspected")
        blob = " ".join(vocabulary)
        for name in ("juliana", "catherine", "gerald", "clarissa", "harrington",
                     "rupert", "alexander", "duke", "duchess", "cathedral",
                     "noblewoman", "priya", "rao", "mehra", "fernandes"):
            self.assertNotIn(name, blob, f"{name!r} is baked into a lexicon")


if __name__ == "__main__":
    unittest.main(verbosity=2)
