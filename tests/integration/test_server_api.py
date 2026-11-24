"""The real server: the app under uvicorn on a loopback port (the plugin's `live_app`), answering real HTTP requests,
over the settings file and the SQLite fallback database in the test's home folder, which the CLI shares."""

import json
import urllib.error
import urllib.request
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager
from typing import Any

import pytest
from fastapi import FastAPI
from strata_python.testing import CliResult, FakeModels, sine_wav
from takes import heard, speech

Cli = Callable[..., CliResult]  # the `cli` fixture (tests/integration/conftest.py)


@pytest.fixture
def server(live_app: Callable[[FastAPI], AbstractContextManager[str]]) -> Iterator[str]:
    from stratavoice.server.app import create_app

    with live_app(create_app()) as base:
        yield base


def call(base: str, method: str, path: str, body: object = None, wav: bytes | None = None) -> tuple[int, Any]:
    data, kind = (
        (wav, "audio/wav")
        if wav is not None
        else (None if body is None else json.dumps(body).encode(), "application/json")
    )
    req = urllib.request.Request(base + path, data=data, method=method, headers={"Content-Type": kind})  # noqa: S310 - loopback
    try:
        with urllib.request.urlopen(req, timeout=10) as r:  # noqa: S310 - loopback
            raw = r.read()
            return r.status, json.loads(raw) if r.headers.get_content_type() == "application/json" else raw
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def test_a_take_posted_over_http_is_kept_judged_played_back_and_seen_by_the_cli(
    server: str, cli: Cli, models: FakeModels
):
    status, health = call(server, "GET", "/api/health")
    assert (status, health["ok"], health["version"]) == (200, True, "0.1.0")
    first = call(server, "GET", "/api/studio")[1]["queue"][0]
    assert call(server, "POST", f"/api/prompts/{first['id']}/takes", wav=sine_wav(1.0))[0] == 400  # no consent yet
    assert call(server, "PUT", "/api/settings", {"consented_on": "2026-11-23"})[0] == 200

    models.down = False
    models.results["transcribe"] = heard("I spent last weekend walking by the sea", start=0.4, end=1.6)
    data = speech(2.0, rate=44_100, width=3)
    status, take = call(server, "POST", f"/api/prompts/{first['id']}/takes?device=Desk%20mic", wav=data)
    assert (status, take["seconds"], take["sample_width"], take["device"]) == (200, 2.0, 3, "Desk mic")
    assert (take["verdict"], take["speech_start"], take["speech_end"]) == ("good", 0.25, 1.85)  # judged and cropped
    assert call(server, "GET", f"/api/takes/{take['id']}/audio") == (200, data)
    assert "1 take(s)" in cli("prompts").stdout
    record = json.loads(cli("manifest").stdout)
    assert (record["audio"]["seconds"], record["text"]) == (2.0, "I spent last weekend walking by the sea")
    assert "good" in cli("takes").stdout
    assert call(server, "GET", "/api/studio")[1]["queue"][0]["id"] != first["id"]
    assert call(server, "DELETE", f"/api/takes/{take['id']}")[0] == 200
    assert "no takes yet" in cli("takes").stdout


def test_errors_answer_with_the_sentence(server: str):
    call(server, "PUT", "/api/settings", {"consented_on": "2026-11-23"})
    first = call(server, "GET", "/api/studio")[1]["queue"][0]["id"]
    status, body = call(server, "POST", f"/api/prompts/{first}/takes", wav=b"not a wav at all")
    assert status == 400
    assert body["detail"].startswith("The recording is not a WAV file that can be read")
    assert call(server, "DELETE", "/api/takes/99")[0] == 404
    assert call(server, "PUT", "/api/settings", {"consented_on": "soon"})[0] == 400


def test_a_reload_on_any_screen_gets_the_app(server: str):
    with urllib.request.urlopen(server + "/settings?tab=appearance", timeout=10) as r:  # noqa: S310 - loopback
        assert r.status == 200
        assert '<base href="./">' in r.read().decode()
