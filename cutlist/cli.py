"""
`python -m cutlist` - the whole pipeline, one command.

    python -m cutlist run data/scripts --out out --top 20

Runs with no API key and no pip install. Set CUTLIST_PROVIDER and a key to
add the model review pass; everything else is identical.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from .candidates import Weights, diversify, find_candidates
from .export import to_json, write_csv, write_cutsheet, write_edl, write_json
from .judge import get_judge, judge_all
from .parse import parse_show
from .verify import check, filter_clean

# Plain ASCII on purpose: the default Windows console is cp1252 and box
# characters crash it on import. A tool that dies on its own banner is not
# a tool anyone runs twice.
BANNER = """
  CUTLIST
  promo cut sheets, straight from the screenplay
  ----------------------------------------------"""


def run(args: argparse.Namespace) -> int:
    t0 = time.time()
    src = Path(args.scripts)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "edl").mkdir(exist_ok=True)

    print(BANNER)
    print(f"  reading    {src}")
    episodes = parse_show(src)
    beats = sum(len(e.beats) for e in episodes)
    runtime = sum(e.duration for e in episodes) / 60
    print(f"  parsed     {len(episodes)} episodes, {beats} beats, {runtime:.0f} min of screenplay")

    weights = Weights()
    cands = find_candidates(episodes, weights,
                            per_episode=args.per_episode, stitched=args.stitched)
    print(f"  generated  {len(cands)} candidate promos "
          f"({sum(1 for c in cands if c.kind == 'stitched')} stitched)")

    # Verify before the model sees anything: a broken window should never
    # cost an API call, and should never reach an editor.
    clean, bad = filter_clean(cands, episodes)
    if bad:
        print(f"  dropped    {len(cands) - len(clean)} promos failing grounding checks")
        for v in bad[:5]:
            print(f"               P{v.promo:03d} {v.rule}: {v.detail}")
    else:
        print(f"  verified   {len(clean)} promos, every cut point is a real beat boundary")

    judge = get_judge(args.provider)
    label = getattr(judge, "name", "offline")
    if label == "offline":
        print("  reviewing  rules only (no CUTLIST_API_KEY set - set one to add a model pass)")
    else:
        print(f"  reviewing  top {args.review} with {label}")

    def tick(i: int, n: int, v) -> None:
        sys.stdout.write(f"\r             {i}/{n} judged")
        sys.stdout.flush()

    reviewed = judge_all(clean, judge, limit=args.review, blend=args.blend,
                         on_event=None if label == "offline" else tick)
    if label != "offline":
        print()
    # Diversify after the re-rank, not before: the model's ordering would
    # otherwise undo it and the top of the list fills up with one episode.
    ranked = diversify([c for c, _ in reviewed])

    # Verify again: re-ranking must not have disturbed any geometry.
    assert not check(ranked, episodes), "post-review verification failed"

    top = ranked[: args.top]
    meta = {
        "show": args.show or src.parent.name or "show",
        "episodes": len(episodes),
        "beats": beats,
        "runtime_min": round(runtime, 1),
        "candidates": len(cands),
        "verified": len(clean),
        "model": label,
        "weights": weights.__dict__,
        "generated": time.strftime("%Y-%m-%d %H:%M:%S"),
        "seconds": round(time.time() - t0, 2),
    }

    payload = to_json(top, episodes, meta)
    write_json(out / "promos.json", payload)
    write_csv(out / "cutlist.csv", top)
    write_cutsheet(out / "cutsheet.md", top, meta["show"], meta)
    for rank, c in enumerate(top, 1):
        write_edl(out / "edl" / f"P{rank:03d}.edl", c, rank, meta["show"])
    write_json(out / "all-candidates.json", to_json(ranked, episodes, meta))
    # Written only when something failed - and removed when nothing did, or a
    # clean run silently inherits the last run's rejections and the output
    # claims promos were dropped that never existed.
    rejected = out / "rejected.json"
    if bad:
        rejected.write_text(json.dumps([v.__dict__ for v in bad], indent=2), encoding="utf-8")
    elif rejected.exists():
        rejected.unlink()

    # The web review desk reads one file. It is also written as a JS global,
    # because browsers block fetch() over file:// - and a reviewer should be
    # able to double-click index.html without starting a server first.
    #
    # This used to run on every invocation, which meant a second run on a
    # different show quietly repointed the prototype at it. The desk is now
    # only rewritten when asked, so running the sample does not disturb the
    # page built from the input pack.
    web = Path(__file__).resolve().parent.parent / args.web if args.web else None
    if web and web.is_dir():
        write_json(web / "promos.json", payload)
        (web / "promos.js").write_text(
            "window.CUTLIST_DATA = " + json.dumps(payload, ensure_ascii=False) + ";",
            encoding="utf-8")
    elif web:
        print(f"  note       {web} does not exist; the review desk was not updated")

    print(f"\n  wrote      {out}/promos.json        full structured output")
    print(f"             {out}/cutlist.csv        the sheet to schedule from")
    print(f"             {out}/cutsheet.md        human-readable")
    print(f"             {out}/edl/*.edl          {len(top)} EDLs for Premiere / Resolve")
    print(f"\n  done in {meta['seconds']}s  -  top promo scored "
          f"{getattr(top[0], 'final', top[0].score):.3f}\n")
    return 0


def evaluate_cmd(args: argparse.Namespace) -> int:
    from .evaluate import print_report, run_eval
    print(BANNER)
    report = run_eval(args.scripts, out=Path(args.out))
    print_report(report)
    print(f"  written to {args.out}/evaluation.json\n")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="cutlist", description="Find promos in microdrama screenplays.")
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="find, rank and export promos")
    r.add_argument("scripts", help="folder of .txt screenplays")
    r.add_argument("--out", default="out")
    r.add_argument("--show", default="")
    r.add_argument("--top", type=int, default=20, help="how many promos to export")
    r.add_argument("--review", type=int, default=25, help="how many to send to the model")
    r.add_argument("--per-episode", type=int, default=3)
    r.add_argument("--stitched", type=int, default=6)
    r.add_argument("--blend", type=float, default=0.5, help="model weight in the final rank")
    r.add_argument("--provider", default=None, help="offline | chat | anthropic | gemini")
    r.add_argument("--web", default="web", metavar="DIR",
                   help="also write the review desk's data here (default: web)")
    r.add_argument("--no-web", dest="web", action="store_const", const="",
                   help="leave the review desk pointing at whatever it already shows")
    r.set_defaults(fn=run)

    e = sub.add_parser("eval", help="measure picks against a hand-cut gold set and three baselines")
    e.add_argument("scripts", help="folder of .txt screenplays")
    e.add_argument("--out", default="out")
    e.set_defaults(fn=evaluate_cmd)

    args = p.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
