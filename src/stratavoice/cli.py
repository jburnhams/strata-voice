"""Command line. From strata-python: `doctor` (versions and imports), `set` (a setting), `serve` (the web server) and
`openapi` (the schema file the web app's types are generated from). The app's own: `prompts` lists the queue with
how far each prompt has got, `takes` lists the kept takes with their verdicts, `score` judges the takes not judged yet
(after strata-models was not running), `manifest` writes the dataset manifest (JSONL), `coverage` says what the
recordings cover and lack, `write` has the prompt writer add a batch of prompts, `rank` orders the queue again, `pilot` reads a session's
takes against the scoring thresholds (step 4, tuning them), and `ingest` brings in found recordings (the Upload screen's
work, for files too big to send through a browser). For the written voice, `writing build` rebuilds the cleaned, split
corpus of what the person wrote from strata-takeout's views, `writing corpus` says what it holds, and `writing export`
writes it as JSON lines."""

import argparse
import datetime
import json
import os
import shutil
import sys
import uuid
from collections.abc import Sequence
from typing import TYPE_CHECKING

from strata_python import cli as shared

from stratavoice import __version__, coverage, db, ingest, models, phonemes, pilot, settings, studio, writer

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


def cmd_ingest(args: argparse.Namespace) -> int:
    """Bring in each file (a copy: the file stays where it is), then run its ingest job here, now."""
    from sqlalchemy.orm import Session
    from strata_python.contracts import FINISHED
    from strata_python.tasks.queue import Queue

    failed = 0
    engine = db.PROJECT.open(default=db.default_url())
    queue = Queue(engine, models.JOBS)
    with Session(engine) as s:
        for path in args.files:
            incoming = os.path.join(settings.recordings_dir(), ingest.FOUND, "incoming")
            os.makedirs(incoming, exist_ok=True)
            part = os.path.join(incoming, f"{uuid.uuid4().hex}.part")
            shutil.copyfile(path, part)
            try:
                up = ingest.add_upload(s, queue, os.path.basename(path), part)
            except ValueError as e:
                print(f"  {e}", file=sys.stderr)
                failed += 1
                continue
            print(f"  #{up.id} {up.name}: {up.seconds or 0:.0f} s, ingesting")
            # Run jobs until this upload's own is finished: an older one queued first runs first (the queue is in
            # order), and nothing left to claim means a server's worker holds it or it waits to be tried again.
            done = queue.get(int(up.job.id)) if up.job else None
            while done is not None and done.state not in FINISHED:
                if queue.step({ingest.KIND: ingest.handler(lambda: engine)}) is None:
                    break
                done = queue.get(done.id)
            out = ingest.get_upload(s, queue, up.id)
            if done is None or done.state != "done":
                why = "no job" if done is None else done.error or f"{done.state}; the server's worker will finish it"
                print(f"  #{up.id} not finished: {why}", file=sys.stderr)
                failed += 1
                continue
            print(
                f"  #{up.id} {out.sentences} sentences: {out.kept} kept ({out.kept_seconds:.0f} s), "
                f"{out.other_voice} someone else's, {out.retry} to check"
            )
    engine.dispose()
    return 1 if failed else 0


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


def cmd_pilot(args: argparse.Namespace) -> int:
    since = datetime.date.fromisoformat(args.since) if args.since else None
    with db.session() as s:
        report = pilot.report(s, since)
    if args.json:
        print(json.dumps(report.model_dump(mode="json"), indent=1))
        return 0
    for line in pilot.describe(report):
        print(f"  {line}")
    return 0


def cmd_writing_build(args: argparse.Namespace) -> int:
    from stratavoice.writing import corpus

    engine = db.PROJECT.open(default=db.default_url())
    try:
        done = corpus.run_build(engine)
    finally:
        engine.dispose()
    splits = ", ".join(f"{c.value} {c.rows}" for c in done.splits)
    print(
        f"  read {done.read} rows; {done.rows} kept ({done.joined} chat lines joined into others), {done.trivial} "
        f"trivial, {done.duplicates} copies, {done.leaks} with a quote left in, {done.signatures} signature(s) learnt"
    )
    print(f"  split: {splits}; sealed from {done.cutoff:%Y-%m-%d}")
    return 0


def cmd_writing_corpus(args: argparse.Namespace) -> int:
    from stratavoice.writing import corpus

    with db.session() as s:
        got = corpus.summary(s)
    if args.json:
        print(json.dumps(got.model_dump(mode="json"), indent=1))
        return 0
    if not got.rows:
        print("  (nothing built yet: strata-voice writing build)")
        return 0
    for m in got.mediums:
        print(
            f"  {m.medium:15} {m.rows:7} rows ({m.trivial} trivial), {m.words:9} words, {m.first:%Y} to {m.last:%Y}; "
            f"checked {m.checked} of {m.sample}, {m.clean} clean"
        )
    print("  split: " + ", ".join(f"{c.value} {c.rows}" for c in got.splits))
    if got.flags:
        print("  flags: " + ", ".join(f"{c.value} {c.rows}" for c in got.flags))
    return 0


def cmd_writing_export(args: argparse.Namespace) -> int:
    from stratavoice.writing import corpus

    with db.session() as s:
        lines = list(corpus.export(s, include_trivial=args.trivial))
    if args.out:
        with open(args.out, "w", encoding="utf8", newline="\n") as f:
            f.writelines(lines)
        print(f"wrote {len(lines)} record(s) to {args.out}")
    else:
        sys.stdout.writelines(lines)
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
    pl = sub.add_parser("pilot", help="the newest session's takes against each scoring threshold, to tune them")
    pl.add_argument(
        "--since", metavar="YYYY-MM-DD", help="every take from this day (UTC) on, not just the newest session"
    )
    pl.add_argument("--json", action="store_true")
    pl.set_defaults(fn=cmd_pilot)
    ig = sub.add_parser("ingest", help="bring in found recordings (any format): level, transcribe, cut, judge, keep")
    ig.add_argument("files", nargs="+", metavar="FILE")
    ig.set_defaults(fn=cmd_ingest)
    wr = sub.add_parser("writing", help="the written voice: what you wrote, cleaned and split (writing build first)")
    wsub = wr.add_subparsers(dest="writing", required=True)
    wb = wsub.add_parser("build", help="rebuild it from strata-takeout's views (the split stays as first frozen)")
    wb.set_defaults(fn=cmd_writing_build)
    wc = wsub.add_parser("corpus", help="what it holds: rows by medium, the split, the cleaning check")
    wc.add_argument("--json", action="store_true")
    wc.set_defaults(fn=cmd_writing_corpus)
    we = wsub.add_parser("export", help="write it as JSON lines, copies left out")
    we.add_argument("-o", "--out", help="file to write (default: standard output)")
    we.add_argument("--trivial", action="store_true", help="include the trivial rows too")
    we.set_defaults(fn=cmd_writing_export)
    shared.add_set(sub, settings.SETTINGS)
    shared.add_serve(sub, run_server, default_port=8370)
    shared.add_openapi(sub, create_app)
    a = p.parse_args(argv)
    return a.fn(a)
