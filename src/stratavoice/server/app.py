"""The application server: `./strata-voice serve` starts the FastAPI backend and serves the built React app.

    ./strata-voice serve [--host 127.0.0.1] [--port 8370]

From strata-python: GET /api/health, GET and PUT /api/settings (consent is the `consented_on` setting), GET
/api/system, /api/docs, /api/openapi.json, the error answers ({detail, payload}) and the web app's pages. This app's own:

    GET  /api/studio                      may it record, the next prompt, progress (a Studio)
    GET  /api/prompts                     every prompt in queue order with its count of takes
    POST /api/prompts/{id}/takes?device=  keep a take and judge it: the body is the WAV itself (audio/wav)
    POST /api/prompts/{id}/skip           take a prompt out of the queue
    DELETE /api/prompts/{id}/skip         put it back
    GET  /api/takes/page?after=&limit=    one page of takes, newest first (a Page)
    GET  /api/takes/{id}/audio            a take's WAV
    POST /api/takes/{id}/score            judge a take again (after strata-models was not running)
    POST /api/takes/{id}/accept           keep a take judged `retry` anyway; DELETE takes that back
    DELETE /api/takes/{id}                remove a take and its file
    GET  /api/manifest.jsonl              the dataset manifest (spec §5 records), one take per prompt
    GET  /api/coverage                    what the recordings cover: phonemes, pairs, stress, length, sentence, style
    POST /api/prompts/write               have the writer add a batch of prompts ({count}), then rank the queue

Every other path serves the web app (`server/static/index.html` when built with `cd web && npm run build`, else the
plain stand-in `landing.html`), so a reload or a shared link to /takes opens that screen.

The microphone needs a secure page: browsers give `getUserMedia` only to https:// or http://localhost. Behind a
reverse proxy on plain http the studio cannot record; see docs/deploying.md."""

import os
from collections.abc import Sequence
from typing import Annotated

from fastapi import FastAPI, Query, Request
from fastapi.responses import FileResponse, PlainTextResponse
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool
from strata_python import web
from strata_python.contracts import ApiModel, Page
from strata_python.db.web import DbSession, add_database

from stratavoice import __version__, coverage, db, settings, studio, system, writer

HERE = os.path.dirname(os.path.abspath(__file__))
STATIC = os.path.join(HERE, "static")
LANDING = os.path.join(HERE, "landing.html")
COMMIT = web.source_commit(__file__)  # None when installed from a wheel
MAX_UPLOAD = 64_000_000  # 300 s (the most `max_take_seconds` allows) of 24-bit 48 kHz mono is 43 MB

# A take is posted as the WAV itself, not JSON or a multipart form: no base64 inflation and no form parser. The
# schema says so here, since FastAPI cannot infer a body it does not parse.
WAV_BODY = {
    "requestBody": {"required": True, "content": {"audio/wav": {"schema": {"type": "string", "format": "binary"}}}}
}


class WriteIn(ApiModel):
    """How many prompts to ask the writer for (1 to writer.MAX_COUNT)."""

    count: int = writer.DEFAULT_COUNT


def create_app() -> FastAPI:
    app = web.base_app("strata-voice", __version__, settings.SETTINGS, commit=COMMIT)
    # A refused take is a ValueError (400) and a missing prompt or take a KeyError (404): no try/except in the routes.
    # The prompt writer ran but gave nothing usable: the models service's fault, a 502 (not running is a 503).
    web.add_error_handlers(app, {writer.WriterFailed: 502})
    # Opened and migrated on the first request that needs it.
    records = add_database(app, db.PROJECT, default=db.default_url)

    def numbers() -> dict[str, object]:
        with Session(records.engine()) as s:
            done = studio.progress(s)
        size = system.folder_bytes(settings.recordings_dir())
        return system.AppNumbers(takes=done.takes, seconds=done.seconds, recordings_bytes=size).model_dump()

    web.add_system(
        app,
        __version__,
        commit=COMMIT,
        folders={"home": settings.SETTINGS.home, "recordings": settings.recordings_dir},
        extra=numbers,
    )

    @app.get("/api/studio")
    def get_studio(s: DbSession) -> studio.Studio:
        return studio.studio(s)

    @app.get("/api/prompts")
    def get_prompts(s: DbSession) -> list[studio.PromptOut]:
        return studio.prompts(s)

    @app.post("/api/prompts/{prompt_id}/takes", openapi_extra=WAV_BODY)
    async def post_take(prompt_id: int, request: Request, s: DbSession, device: str | None = None) -> studio.TakeOut:
        size = int(request.headers.get("content-length") or 0)
        if size > MAX_UPLOAD:
            raise ValueError(f"The take is {size // 1_000_000} MB; the most accepted is {MAX_UPLOAD // 1_000_000} MB.")
        kept = studio.add_take(s, prompt_id, await request.body(), device)
        # Judged before answering, so the studio can ask again at once. In a worker thread: the transcription waits
        # on strata-models for up to scoring.ASR_WAIT_SECONDS, and the event loop serves every other request.
        return await run_in_threadpool(studio.score_take, s, kept.id)

    @app.post("/api/prompts/{prompt_id}/skip")
    def post_skip(prompt_id: int, s: DbSession) -> studio.PromptOut:
        return studio.skip(s, prompt_id)

    @app.delete("/api/prompts/{prompt_id}/skip")
    def delete_skip(prompt_id: int, s: DbSession) -> studio.PromptOut:
        return studio.skip(s, prompt_id, skipped=False)

    @app.get("/api/takes/page")
    def get_takes_page(
        s: DbSession, after: int | None = None, limit: Annotated[int, Query(ge=1, le=200)] = 20
    ) -> Page[studio.TakeOut]:
        return studio.takes_page(s, after, limit)

    @app.get("/api/takes/{take_id}/audio", response_class=FileResponse)
    def get_take_audio(take_id: int, s: DbSession) -> FileResponse:
        return FileResponse(studio.take_file(s, take_id), media_type="audio/wav")

    @app.post("/api/takes/{take_id}/score")
    def post_score(take_id: int, s: DbSession) -> studio.TakeOut:
        return studio.score_take(s, take_id)

    @app.post("/api/takes/{take_id}/accept")
    def post_accept(take_id: int, s: DbSession) -> studio.TakeOut:
        return studio.accept_take(s, take_id)

    @app.delete("/api/takes/{take_id}/accept")
    def delete_accept(take_id: int, s: DbSession) -> studio.TakeOut:
        return studio.accept_take(s, take_id, accepted=False)

    @app.delete("/api/takes/{take_id}")
    def delete_take(take_id: int, s: DbSession) -> studio.TakeOut:
        return studio.remove_take(s, take_id)

    @app.get("/api/coverage")
    def get_coverage(s: DbSession) -> coverage.Coverage:
        studio.seed(s)
        return coverage.coverage(s)

    @app.post("/api/prompts/write")
    def post_write(body: WriteIn, s: DbSession) -> writer.Written:
        studio.seed(s)
        return writer.write(s, body.count)

    @app.get("/api/manifest.jsonl", response_class=PlainTextResponse)
    def get_manifest(s: DbSession) -> PlainTextResponse:
        body = "".join(studio.manifest_line(r) for r in studio.manifest(s))
        return PlainTextResponse(body, media_type="application/x-ndjson")

    web.add_web(app, STATIC, LANDING)  # last: its catch-all serves the web app at every other path
    return app


def main(argv: Sequence[str] | None = None) -> None:
    web.serve(create_app(), argv, default_port=8370, banner=f"settings and records: {settings.SETTINGS.home()}")
