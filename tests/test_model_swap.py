"""
The swappable model layer, exercised against a real HTTP server.

The brief says a solution where the model is easy to swap will shine, and
that stronger models may be connected through APIs they provide. That claim
is only worth making if the network path has actually run, so this stands up
a tiny OpenAI-compatible endpoint on localhost and drives the whole pipeline
through it - real sockets, real JSON, real `urllib`.

What it proves, and what it does not: it proves the request shape, the
response parsing, the blend, the fallback on a failed call, and the fact
that a model cannot move a cut point. It does not prove any particular
vendor's endpoint is reachable, and it is not a substitute for one real key.

    python -m unittest tests.test_model_swap -v
"""

from __future__ import annotations

import json
import os
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from cutlist.candidates import diversify, find_candidates
from cutlist.judge import ChatJudge, Verdict, get_judge, judge_all, render
from cutlist.parse import parse_show
from cutlist.verify import check

SCRIPTS = Path(__file__).resolve().parent.parent / "data" / "scripts"

# What the fake model replies with. Deliberately hostile: it wraps its JSON in
# prose and a fence, and it tries to hand back timestamps it was never asked
# for - which is exactly the failure the architecture is supposed to make
# harmless.
REPLY = (
    "Sure! Here's my assessment:\n```json\n"
    + json.dumps({
        "hook": 9, "cliff": 8, "standalone": 7,
        "why": "Opens on a slap and cuts before the answer.",
        "caption": "She should never have opened that door.",
        "risk": "none",
        "start": "00:00.00", "end": "00:45.00", "start_tc": "99:99.99",
    })
    + "\n```\nHope that helps!"
)


class _Handler(BaseHTTPRequestHandler):
    seen: list[dict] = []
    fail_next = False

    def do_POST(self):                                    # noqa: N802
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        _Handler.seen.append({
            "path": self.path,
            "auth": self.headers.get("Authorization"),
            "body": body,
        })
        if _Handler.fail_next:
            _Handler.fail_next = False
            self.send_response(500)
            self.end_headers()
            self.wfile.write(b'{"error":"upstream is having a day"}')
            return
        payload = json.dumps({"choices": [{"message": {"content": REPLY}}]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *a):                            # keep the test output clean
        pass


class ModelSwap(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.server = HTTPServer(("127.0.0.1", 0), _Handler)
        cls.port = cls.server.server_port
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.port}/v1"
        cls.episodes = parse_show(SCRIPTS)
        cls.cands = diversify(find_candidates(cls.episodes))

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        _Handler.seen.clear()
        _Handler.fail_next = False

    # ---------------------------------------------------------------- wiring

    def test_three_environment_variables_point_it_at_a_different_model(self):
        env = {
            "CUTLIST_PROVIDER": "chat",
            "CUTLIST_BASE_URL": self.base,
            "CUTLIST_MODEL": "a-different-model",
            "CUTLIST_API_KEY": "test-key-not-a-real-one",
        }
        old = {k: os.environ.get(k) for k in env}
        os.environ.update(env)
        try:
            judge = get_judge()
            self.assertIsInstance(judge, ChatJudge)
            self.assertEqual(judge.name, "chat:a-different-model")
            verdict = judge.judge(self.cands[0])
        finally:
            for k, v in old.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v

        call = _Handler.seen[0]
        self.assertEqual(call["path"], "/v1/chat/completions")
        self.assertEqual(call["auth"], "Bearer test-key-not-a-real-one")
        self.assertEqual(call["body"]["model"], "a-different-model")
        self.assertEqual(verdict.hook, 9.0)
        self.assertEqual(verdict.cliff, 8.0)

    def test_it_parses_json_a_model_buried_in_prose_and_a_fence(self):
        v = ChatJudge(self.base, "m", "k").judge(self.cands[0])
        self.assertEqual(v.standalone, 7.0)
        self.assertIn("slap", v.why)

    # ------------------------------------------------- the grounding promise

    def test_the_prompt_carries_no_field_a_model_could_put_a_cut_point_in(self):
        ChatJudge(self.base, "m", "k").judge(self.cands[0])
        system = _Handler.seen[0]["body"]["messages"][0]["content"]
        for word in ("start", "end", "timestamp", "in-point", "out-point"):
            self.assertNotIn(
                '"' + word + '"', system,
                f"the reply schema offers a {word!r} key for a model to fill",
            )

    def test_timestamps_the_model_volunteers_are_discarded(self):
        """
        The fake model returns start/end/start_tc. None of them may survive
        into a Verdict, and the promo must keep the cut points the parser
        computed.
        """
        before = (self.cands[0].segments[0].start, self.cands[0].segments[0].end)
        v = ChatJudge(self.base, "m", "k").judge(self.cands[0])
        self.assertEqual(
            set(v.to_dict()) & {"start", "end", "start_tc", "end_tc", "timestamp"},
            set(),
        )
        self.assertEqual((self.cands[0].segments[0].start,
                          self.cands[0].segments[0].end), before)

    def test_a_full_reviewed_run_still_passes_every_grounding_check(self):
        reviewed = judge_all(self.cands, ChatJudge(self.base, "m", "k"),
                             limit=5, blend=0.5)
        ranked = diversify([c for c, _ in reviewed])
        self.assertEqual(check(ranked, self.episodes), [])
        self.assertEqual(len(_Handler.seen), 5)

    # ------------------------------------------------------------- behaviour

    def test_the_model_moves_the_ranking_but_only_the_ranking(self):
        top = self.cands[:5]
        rules = [c.score for c in top]
        reviewed = judge_all(top, ChatJudge(self.base, "m", "k"), limit=5, blend=0.5)
        for (cand, verdict), rule in zip(reviewed, rules):
            self.assertEqual(cand.score, rule, "the rule score must survive")
            self.assertNotEqual(getattr(cand, "final", None), None)
            self.assertIsInstance(verdict, Verdict)

    def test_one_failed_call_costs_that_promo_its_review_and_nothing_else(self):
        _Handler.fail_next = True
        reviewed = judge_all(self.cands, ChatJudge(self.base, "m", "k"),
                             limit=3, blend=0.5)
        self.assertEqual(len(reviewed), len(self.cands))
        self.assertEqual(check(diversify([c for c, _ in reviewed]), self.episodes), [])

    def test_no_api_key_means_offline_rather_than_a_crash(self):
        old = {k: os.environ.get(k) for k in ("CUTLIST_PROVIDER", "CUTLIST_API_KEY")}
        os.environ["CUTLIST_PROVIDER"] = "chat"
        os.environ.pop("CUTLIST_API_KEY", None)
        try:
            self.assertEqual(getattr(get_judge(), "name", "offline"), "offline")
        finally:
            for k, v in old.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v

    def test_the_clip_sent_to_the_model_is_only_real_screenplay(self):
        text = render(self.cands[0])
        for beat in self.cands[0].beats:
            if beat.kind == "DIALOGUE":
                self.assertIn(beat.text, text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
