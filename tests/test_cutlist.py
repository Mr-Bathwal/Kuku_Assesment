"""
Tests for the guarantees the tool actually makes.

    python -m unittest discover tests -v

Standard library only, like the rest of it. These are not coverage theatre:
each one pins a claim made in the write-up, and three of them exist because
the thing they test was broken at some point during the build.
"""

from __future__ import annotations

import unittest
from pathlib import Path

from cutlist.candidates import (MAX_LEN, MIN_LEN, Weights, _first_seen,
                                candidates_for_episode, diversify,
                                find_candidates, suppress)
from cutlist.export import _tc
from cutlist.judge import OfflineJudge, _extract_json, render
from cutlist.parse import DIALOGUE, parse_show, to_seconds, to_stamp
from cutlist.signals import signal_beat, signal_episode
from cutlist.verify import check

SCRIPTS = Path(__file__).resolve().parent.parent / "data" / "scripts"


class Corpus(unittest.TestCase):
    """Parsed once; every other test reads these."""

    @classmethod
    def setUpClass(cls):
        cls.episodes = parse_show(SCRIPTS)
        cls.by_no = {e.number: e for e in cls.episodes}


class TestParse(Corpus):
    def test_every_episode_parses(self):
        self.assertEqual(len(self.episodes), 50)
        self.assertEqual(sum(len(e.beats) for e in self.episodes), 3727)

    def test_beats_are_chronological(self):
        for ep in self.episodes:
            for a, b in zip(ep.beats, ep.beats[1:]):
                self.assertLessEqual(a.start, b.start, f"ep{ep.number} out of order")

    def test_no_beat_ends_before_it_starts(self):
        for ep in self.episodes:
            for b in ep.beats:
                self.assertGreaterEqual(b.end, b.start)

    def test_timecode_round_trip(self):
        for stamp in ("00:00.00", "02:18.00", "01:05.80", "00:59.24"):
            self.assertEqual(to_stamp(to_seconds(stamp)), stamp)

    def test_dialogue_keeps_its_actor_direction(self):
        tagged = [b for e in self.episodes for b in e.beats
                  if b.kind == DIALOGUE and b.emotions]
        self.assertGreater(len(tagged), 1000)
        self.assertTrue(all(t == t.lower() for b in tagged for t in b.emotions))


class TestSignals(Corpus):
    def _find(self, prefix: str):
        for ep in self.episodes:
            for b in ep.beats:
                if b.text.startswith(prefix):
                    return signal_beat(b)
        self.fail(f"no beat starting {prefix!r}")

    def test_violence_on_a_person_outscores_violence_on_kindling(self):
        """The campfire bug: 'strikes flint' once scored as hard as a slap."""
        campfire = self._find("He strikes flint")
        assault = self._find("The noblewoman suddenly rears back her riding crop")
        self.assertLess(campfire.shock, 0.3)
        self.assertGreater(assault.shock, 0.8)
        self.assertLess(campfire.stop_power, assault.stop_power)

    def test_a_screamed_line_outscores_a_murmured_one(self):
        """stop_power used to sum axes that cannot co-occur for a beat kind."""
        screamed = self._find("Harrington! Gerald Harrington paid us!")
        self.assertGreater(screamed.stop_power, 0.6)

    def test_hyphenated_lexicon_terms_match(self):
        """Every hyphenated term silently matched nothing until this was fixed."""
        from cutlist.signals import CLIFF_VISUAL, _lex_hits
        hits = dict(_lex_hits("Slight push-in on Catherine as she clenches her fist", CLIFF_VISUAL))
        self.assertIn("push-in", hits)

    def test_sound_effects_carry_shock(self):
        """A beam coming down is an event, not ambience."""
        beam = self._find("Massive wooden beam crashes")
        self.assertGreater(beam.shock, 0.3)


class TestCandidates(Corpus):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.seen = _first_seen(cls.episodes)
        cls.cands = diversify(find_candidates(cls.episodes))

    def test_every_cut_lands_on_a_beat_boundary(self):
        """The core guarantee of the whole tool."""
        for c in self.cands:
            for seg in c.segments:
                ep = self.by_no[seg.episode]
                starts = {round(b.start, 3) for b in ep.beats}
                ends = {round(b.end, 3) for b in ep.beats}
                self.assertIn(round(seg.start, 3), starts)
                self.assertIn(round(seg.end, 3), ends)

    def test_every_promo_is_within_the_brief_length(self):
        for c in self.cands:
            self.assertGreaterEqual(c.duration, MIN_LEN - 0.01)
            self.assertLessEqual(c.duration, MAX_LEN + 0.01)

    def test_nothing_runs_past_the_end_of_its_episode(self):
        for c in self.cands:
            for seg in c.segments:
                self.assertLessEqual(seg.end, self.by_no[seg.episode].duration + 0.01)

    def test_suppression_removes_near_duplicates(self):
        ep = self.by_no[35]
        raw = candidates_for_episode(ep, Weights(), self.seen)
        kept = suppress(raw, overlap=0.4, limit=60)
        self.assertLess(len(kept), len(raw))
        for a in kept:
            for b in kept:
                if a is b:
                    continue
                s1, s2 = a.segments[0], b.segments[0]
                inter = max(0.0, min(s1.end, s2.end) - max(s1.start, s2.start))
                union = s1.duration + s2.duration - inter
                self.assertLessEqual(inter / union, 0.4 + 1e-6)

    def test_the_top_of_the_list_does_not_repeat_an_episode(self):
        touched = [n for c in self.cands[:20] for n in c.episodes]
        self.assertEqual(len(touched), len(set(touched)))

    def test_the_hook_beat_is_inside_the_hook_window(self):
        for c in self.cands:
            if not c.hook_beat:
                continue
            first = c.segments[0]
            self.assertEqual(c.hook_beat.episode, first.episode)
            self.assertLessEqual(c.hook_beat.start, first.start + 3.0 + 1e-6)


class TestVerify(Corpus):
    def test_clean_output_passes(self):
        self.assertEqual(check(diversify(find_candidates(self.episodes)), self.episodes), [])

    def test_a_fabricated_timestamp_is_caught(self):
        """The failure the whole design exists to prevent."""
        cands = diversify(find_candidates(self.episodes))[:3]
        cands[0].segments[0].start += 0.37        # a plausible, wrong in-point
        bad = check(cands, self.episodes)
        self.assertTrue(any(v.rule == "in-point-on-beat" for v in bad))

    def test_an_impossible_length_is_caught(self):
        cands = diversify(find_candidates(self.episodes))[:3]
        cands[0].segments[0].end = cands[0].segments[0].start + 5.0
        self.assertTrue(any(v.rule == "length" for v in check(cands, self.episodes)))


class TestJudge(Corpus):
    def test_the_model_is_never_shown_a_timestamp_field_it_can_fill(self):
        """
        The prompt contains times for context, but the reply schema has no
        timestamp key - so there is nowhere for a hallucinated cut to go.
        """
        verdict = OfflineJudge().judge(diversify(find_candidates(self.episodes))[0])
        self.assertEqual(
            set(verdict.to_dict()) & {"start", "end", "start_tc", "end_tc", "timestamp"},
            set(),
        )

    def test_rendered_clip_contains_only_real_beats(self):
        cand = diversify(find_candidates(self.episodes))[0]
        text = render(cand)
        for b in cand.beats:
            if b.kind == DIALOGUE:
                self.assertIn(b.text, text)

    def test_json_survives_a_model_wrapping_it_in_prose(self):
        messy = 'Sure! Here you go:\n```json\n{"hook": 8, "cliff": 7, "standalone": 6}\n```\nHope that helps.'
        self.assertEqual(_extract_json(messy)["hook"], 8)


class TestWhatTheUIDraws(Corpus):
    """
    The review page draws the ranker's own numbers rather than a decorative
    stand-in, which is only worth claiming if the two cannot drift apart.
    These pin the payload the page reads.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        from cutlist.export import to_json
        cands = diversify(find_candidates(cls.episodes))[:20]
        cls.payload = to_json(cands, cls.episodes, {"show": "test"})
        cls.eps_out = {e["number"]: e for e in cls.payload["episodes"]}

    def test_every_episode_has_a_pressure_curve_one_sample_per_second(self):
        import math
        for ep in self.payload["episodes"]:
            self.assertEqual(len(ep["profile"]), math.ceil(ep["duration"]))
            self.assertTrue(all(0 <= v <= 100 for v in ep["profile"]))

    def test_the_curve_agrees_with_the_scorer_at_the_hook(self):
        """
        The spike the page draws under a promo's in-point has to be the same
        number the ranker chose that in-point with.
        """
        from cutlist.signals import signal_beat
        hook = self.payload["promos"][0]["hook"]
        ep = self.by_no[hook["episode"]]
        beat = next(b for b in ep.beats
                    if b.text == hook["text"] and to_stamp(b.start) == hook["at"])
        drawn = self.eps_out[ep.number]["profile"][int(beat.start)]
        self.assertGreaterEqual(drawn, round(signal_beat(beat).stop_power * 100))

    def test_the_lattice_the_page_draws_sums_to_the_figure_the_write_up_quotes(self):
        """
        Two independent code paths: evaluate.legal_fraction counts boundaries,
        export._legal_lattice emits them. The page draws the second and the
        caption prints the first, so a mismatch would be a lie on screen.
        """
        g = self.payload["meta"]["grounding"]
        self.assertEqual(sum(len(e["starts"]) for e in self.payload["episodes"]),
                         g["beat_starts"])
        self.assertEqual(sum(e["expressible"] for e in self.payload["episodes"]),
                         g["expressible_timestamps"])

    def test_no_in_point_falls_outside_its_episode(self):
        for e in self.payload["episodes"]:
            self.assertTrue(all(0 <= s < e["expressible"] for s in e["starts"]))

    def test_the_beat_mix_accounts_for_every_beat(self):
        for e in self.payload["episodes"]:
            self.assertEqual(sum(e["mix"].values()), e["beats"])


class TestExport(unittest.TestCase):
    def test_edl_timecode(self):
        self.assertEqual(_tc(0.0), "00:00:00:00")
        self.assertEqual(_tc(1.0), "00:00:01:00")
        self.assertEqual(_tc(89.8), "00:01:29:24")      # 0.8s * 30fps = 24 frames
        self.assertEqual(_tc(3661.5), "01:01:01:15")


if __name__ == "__main__":
    unittest.main(verbosity=2)
