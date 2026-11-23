"""Command line. From strata-python: `doctor` (versions and imports), `set` (a setting), `serve` (the web server) and
`openapi` (the schema file the web app's types are generated from). The app's own: `prompts` lists the queue with
how far each prompt has got, `takes` lists the kept takes, and `manifest` writes the dataset manifest (JSONL)."""

import argparse
import json
import sys
from collections.abc import Sequence
from typing import TYPE_CHECKING

from strata_python import cli as shared

from stratavoice import __version__, db, settings, studio

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
        print(f"  #{t.id:<5} {t.seconds:6.1f} s  {t.created:%Y-%m-%d %H:%M}  {t.prompt_text[:60]}")
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


def main(argv: Sequence[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="strata-voice")
    sub = p.add_subparsers(dest="cmd", required=True)
    shared.add_doctor(
        sub, "strata-voice", __version__, ("fastapi", "uvicorn", "pydantic", "sqlalchemy", "strata_python")
    )
    pr = sub.add_parser("prompts", help="list the prompts in queue order, with how far each has got")
    pr.add_argument("--json", action="store_true")
    pr.set_defaults(fn=cmd_prompts)
    t = sub.add_parser("takes", help="list the newest takes")
    t.add_argument("--limit", type=int, default=50)
    t.add_argument("--json", action="store_true")
    t.set_defaults(fn=cmd_takes)
    m = sub.add_parser("manifest", help="write the dataset manifest: one JSON record per prompt's take in use")
    m.add_argument("-o", "--out", help="file to write (default: standard output)")
    m.set_defaults(fn=cmd_manifest)
    shared.add_set(sub, settings.SETTINGS)
    shared.add_serve(sub, run_server, default_port=8370)
    shared.add_openapi(sub, create_app)
    a = p.parse_args(argv)
    return a.fn(a)
