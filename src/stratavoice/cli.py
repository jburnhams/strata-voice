"""Command line. From strata-python: `doctor` (versions and imports), `set` (a setting), `serve` (the web server) and
`openapi` (the schema file the web app's types are generated from). The app's own: `prompts` lists the queue with
how far each prompt has got, `takes` lists the kept takes with their verdicts, `score` judges the takes not judged yet
(after strata-models was not running), `manifest` writes the dataset manifest (JSONL), `coverage` says what the
recordings cover and lack, `write` has the prompt writer add a batch of prompts, and `rank` orders the queue again."""

import argparse
import json
import sys
from collections.abc import Sequence
from typing import TYPE_CHECKING

from strata_python import cli as shared

from stratavoice import __version__, coverage, db, phonemes, settings, studio, writer

if TYPE_CHECKING:
    from fastapi import FastAPI


def run_server(host: str, port: int) -> None:
    from stratavoice.server import app as server_app  # here, so the other commands do not import FastAPI's routes

    server_app.main(["--host", host, "--port", str(port)])


def create_app() -> "FastAPI":
    from stratavoice.server.app import create_app as create  # only when `openapi` runs

    return create()


def cmd_prompts(args: argparse.Namespace) -> int:
    with db.session() as s:
        items = studio.prompts(s)
    if args.json:
        print(json.dumps([p.model_dump(mode="json") for p in items], indent=1))
        return 0
    for p in items:
        state = "skipped" if p.skipped else f"{p.takes} take(s)" if p.takes else "waiting"
        print(f"  #{p.id:<4} {p.kind:12} {state:11} {p.text[:70]}")
    return 0


def cmd_takes(args: argparse.Namespace) -> int:
    with db.session() as s:
        items = studio.takes_page(s, limit=args.limit).items
    if args.json:
        print(json.dumps([t.model_dump(mode="json") for t in items], indent=1))
    elif not items:
        print("  (no takes yet: record some in the studio, ./strata-voice serve)")
    for t in [] if args.json else items:
        verdict = t.verdict or "not scored"
        print(f"  #{t.id:<5} {t.seconds:6.1f} s  {t.created:%Y-%m-%d %H:%M}  {verdict:10}  {t.prompt_text[:60]}")
    return 0


def cmd_score(args: argparse.Namespace) -> int:
    with db.session() as s:
        ids = [t.id for t in studio.takes_page(s, limit=1_000_000).items] if args.all else studio.unscored(s)
        if not ids:
            print("  (every take is judged; --all judges them again)")
        for take_id in ids:
            t = studio.score_take(s, take_id)
            why = " ".join(p.sentence for p in t.problems)
            print(f"  #{t.id:<5} {t.verdict:10} {why or t.prompt_text[:60]}")
    return 0


def cmd_manifest(args: argparse.Namespace) -> int:
    with db.session() as s:
        lines = [studio.manifest_line(r) for r in studio.manifest(s)]
    if args.out:
        with open(args.out, "w", encoding="utf8", newline="\n") as f:
            f.writelines(lines)
        print(f"wrote {len(lines)} record(s) to {args.out}; audio paths are relative to {settings.recordings_dir()}")
    else:
        sys.stdout.writelines(lines)
    return 0


def check_espeak() -> "tuple[shared.Status, str]":
    """Optional: without espeak-ng the studio still records, but phonemes are not counted or ranked by."""
    found = phonemes.program()
    if found is None:
        return "missing", "install espeak-ng (it phonemises prompts for coverage), or set `espeak` to its path"
    return "ok", found


def cmd_coverage(args: argparse.Namespace) -> int:
    with db.session() as s:
        studio.seed(s)
        cov = coverage.coverage(s)
    if args.json:
        print(json.dumps(cov.model_dump(mode="json"), indent=1))
        return 0
    print(f"  {cov.prompts} prompt(s) recorded, {cov.waiting} generated prompt(s) waiting")
    if not cov.phonemised:
        print("  espeak-ng was not found, so phonemes are not counted: install it, or set `espeak` to its path")
    for g in cov.groups:
        of = f" of {g.inventory}" if g.inventory is not None else ""
        least = ", ".join(f"{u.value} {u.count}" for u in g.units[:8])
        print(f"  {g.title:16} {g.covered}{of} said; least: {least}")
    return 0


def cmd_write(args: argparse.Namespace) -> int:
    with db.session() as s:
        studio.seed(s)
        done = writer.write(s, args.count)
    cost = f", ${done.cost_usd:.3f}" if done.cost_usd is not None else ""
    print(
        f"  {done.writer} offered {done.offered}, kept {done.added}{cost}; {done.waiting} generated prompt(s) waiting"
    )
    return 0


def cmd_rank(args: argparse.Namespace) -> int:
    with db.session() as s:
        studio.seed(s)
        n = coverage.rank(s)
        top = [p for p in studio.upcoming(s, args.show) if p.source == coverage.GENERATED]
    print(f"  ranked {n} generated prompt(s)")
    for p in top:
        print(f"  {p.score or 0:7.3f}  {p.kind:11} {p.text[:70]}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="strata-voice")
    sub = p.add_subparsers(dest="cmd", required=True)
    shared.add_doctor(
        sub,
        "strata-voice",
        __version__,
        ("fastapi", "uvicorn", "pydantic", "sqlalchemy", "strata_python"),
        checks=[shared.Check("espeak-ng", check_espeak, optional=True)],
    )
    pr = sub.add_parser("prompts", help="list the prompts in queue order, with how far each has got")
    pr.add_argument("--json", action="store_true")
    pr.set_defaults(fn=cmd_prompts)
    t = sub.add_parser("takes", help="list the newest takes")
    t.add_argument("--limit", type=int, default=50)
    t.add_argument("--json", action="store_true")
    t.set_defaults(fn=cmd_takes)
    sc = sub.add_parser("score", help="judge the takes not judged yet (levels here, words through strata-models)")
    sc.add_argument("--all", action="store_true", help="judge every take again, as after changing a threshold")
    sc.set_defaults(fn=cmd_score)
    m = sub.add_parser("manifest", help="write the dataset manifest: one JSON record per prompt's take in use")
    m.add_argument("-o", "--out", help="file to write (default: standard output)")
    m.set_defaults(fn=cmd_manifest)
    cv = sub.add_parser("coverage", help="what the recordings cover and lack: phonemes, pairs, stress, styles...")
    cv.add_argument("--json", action="store_true")
    cv.set_defaults(fn=cmd_coverage)
    w = sub.add_parser("write", help="have the prompt writer (strata-models' `write` role) add prompts, then rank")
    w.add_argument("--count", type=int, default=writer.DEFAULT_COUNT)
    w.set_defaults(fn=cmd_write)
    rk = sub.add_parser("rank", help="order the generated prompts still to record by what they would add")
    rk.add_argument("--show", type=int, default=10, help="how many of the next prompts to print")
    rk.set_defaults(fn=cmd_rank)
    shared.add_set(sub, settings.SETTINGS)
    shared.add_serve(sub, run_server, default_port=8370)
    shared.add_openapi(sub, create_app)
    a = p.parse_args(argv)
    return a.fn(a)
