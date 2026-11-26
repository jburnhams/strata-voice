import os
from pathlib import Path

import pytest
import uvicorn
from fastapi.testclient import TestClient
from prompts import candidate, offer
from sqlalchemy.orm import Session
from strata_python.testing import FakeModels, assert_openapi_current, sine_wav
from takes import found_heard, found_voices, heard, recording, speech

from stratavoice import __version__, curriculum, writer
from stratavoice.server import app as server_app
from stratavoice.server.app import create_app

OPENAPI = Path(__file__).parents[2] / "web" / "openapi.json"
WAV = {"Content-Type": "audio/wav"}


def test_the_committed_schema_is_what_the_server_answers():
    # The web app's types are generated from this file (web/src/api.generated.ts); a route change without
    # `./strata-voice openapi` (then `npm run api-types` in web/) fails here, before the types drift from the server.
    assert_openapi_current(create_app, OPENAPI)


def test_landing_page_and_built_static_index(tmp_path, monkeypatch: pytest.MonkeyPatch, db_env: str):
    monkeypatch.setattr(server_app, "STATIC", str(tmp_path / "no_static"))
    with TestClient(create_app()) as c:
        assert "has not been built here yet" in c.get("/").text
        assert c.get("/api/health").json()["ok"] is True

    static = tmp_path / "static"
    (static / "assets").mkdir(parents=True)
    (static / "index.html").write_text("<h1>built react app</h1>", encoding="utf8")
    monkeypatch.setattr(server_app, "STATIC", str(static))
    with TestClient(create_app()) as c:
        assert c.get("/").text == '<base href="./"><h1>built react app</h1>'
        assert '<base href="../">' in c.get("/takes/2026").text
        assert c.get("/api/nope").json() == {"detail": "no such endpoint"}


def test_recording_needs_consent_then_keeps_the_wav(client: TestClient):
    studio = client.get("/api/studio").json()
    assert (studio["consented"], studio["max_take_seconds"]) == (False, 60)
    first = studio["queue"][0]
    assert first["key"] == curriculum.STARTER[0].key
    refused = client.post(f"/api/prompts/{first['id']}/takes", content=speech(1.0), headers=WAV)
    assert refused.status_code == 400
    assert refused.json()["detail"] == "Agree to be recorded first: nothing is kept until you do."

    assert client.put("/api/settings", json={"consented_on": "2026-11-23"}).status_code == 200
    data = speech(1.0)
    take = client.post(f"/api/prompts/{first['id']}/takes", params={"device": "USB mic"}, content=data, headers=WAV)
    assert take.status_code == 200
    body = take.json()
    assert (body["prompt_id"], body["seconds"], body["device"]) == (first["id"], 1.0, "USB mic")
    audio = client.get(f"/api/takes/{body['id']}/audio")
    assert (audio.status_code, audio.headers["content-type"], audio.content) == (200, "audio/wav", data)

    after = client.get("/api/studio").json()
    assert after["queue"][0]["key"] == curriculum.STARTER[1].key
    assert (after["progress"]["recorded"], after["progress"]["takes"]) == (1, 1)

    bad = client.post(f"/api/prompts/{first['id']}/takes", content=sine_wav(1.0, channels=2), headers=WAV)
    assert (bad.status_code, bad.json()["detail"]) == (400, "Send a mono recording; this one has 2 channels.")
    click = client.post(f"/api/prompts/{first['id']}/takes", content=sine_wav(0.1), headers=WAV)  # Record then Stop
    assert (click.status_code, click.json()["detail"]) == (
        400,
        "The recording is 0.1 seconds long; the shortest kept is 0.3.",
    )
    big = client.post(f"/api/prompts/{first['id']}/takes", content=b"x", headers={**WAV, "Content-Length": "99999999"})
    assert (big.status_code, big.json()["detail"]) == (400, "The take is 99 MB; the most accepted is 64 MB.")
    assert client.post("/api/prompts/999/takes", content=data, headers=WAV).status_code == 404


def test_skip_list_page_remove_and_the_manifest(client: TestClient):
    client.put("/api/settings", json={"consented_on": "2026-11-23"})
    prompts = client.get("/api/prompts").json()
    assert len(prompts) == len(curriculum.STARTER)
    assert client.post(f"/api/prompts/{prompts[0]['id']}/skip").json()["skipped"] is True
    assert client.get("/api/studio").json()["queue"][0]["id"] == prompts[1]["id"]
    assert client.delete(f"/api/prompts/{prompts[0]['id']}/skip").json()["skipped"] is False
    assert client.post("/api/prompts/999/skip").status_code == 404

    ids = [
        client.post(f"/api/prompts/{p['id']}/takes", content=speech(0.5), headers=WAV).json()["id"] for p in prompts[:3]
    ]
    queue = client.get("/api/queue", params={"limit": 2}).json()
    assert [p["id"] for p in queue["items"]] == [p["id"] for p in prompts[3:5]]
    assert client.get("/api/queue", params={"after": queue["next"]}).json()["items"][0]["id"] == prompts[5]["id"]
    bad = client.get("/api/queue", params={"after": "x"})
    assert (bad.status_code, bad.json()["detail"]) == (
        400,
        "“x” is not a place in the queue: give the `next` of the page before.",
    )
    page = client.get("/api/takes/page", params={"limit": 2}).json()
    assert ([t["id"] for t in page["items"]], page["next"]) == (ids[:0:-1], str(ids[1]))
    assert client.get("/api/takes/page", params={"limit": 0}).status_code == 422

    lines = client.get("/api/manifest.jsonl")
    assert lines.headers["content-type"].startswith("application/x-ndjson")
    assert lines.text.count("\n") == 3

    assert client.delete(f"/api/takes/{ids[1]}").json()["id"] == ids[1]
    gone = client.delete(f"/api/takes/{ids[1]}")
    assert (gone.status_code, gone.json()["detail"]) == (404, f"There is no take {ids[1]}.")
    assert client.get(f"/api/takes/{ids[1]}/audio").status_code == 404

    s = client.get("/api/system").json()
    assert s["version"] == __version__
    assert (s["takes"], s["seconds"]) == (2, 1.0)
    assert s["recordings_bytes"] == 2 * len(speech(0.5))
    assert [f["name"] for f in s["folders"]] == ["home", "recordings"]


def test_settings_roundtrip_and_server_main(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    got = client.get("/api/settings").json()
    assert (got["consented_on"], got["max_take_seconds"]) == ("", 60)
    assert got["recordings_dir"].endswith("recordings")
    assert client.put("/api/settings", json={"max_take_seconds": 1}).status_code == 400
    assert client.put("/api/settings", json={"max_take_seconds": 90}).json()["max_take_seconds"] == 90

    runs: list[tuple[str, int, str]] = []
    monkeypatch.setattr(uvicorn, "run", lambda app, host, port, log_level: runs.append((host, port, log_level)))
    server_app.main(["--host", "127.0.0.1", "--port", "8370"])
    assert runs == [("127.0.0.1", 8370, "warning")]


def test_a_take_is_judged_as_it_is_kept_and_can_be_judged_again(client: TestClient, models: FakeModels):
    client.put("/api/settings", json={"consented_on": "2026-11-24"})
    prompt = next(p for p in client.get("/api/prompts").json() if p["kind"] == "phonetic")
    kept = client.post(f"/api/prompts/{prompt['id']}/takes", content=speech(), headers=WAV).json()
    assert (kept["verdict"], kept["problems"]) == ("unchecked", [])  # strata-models is down: kept, not refused

    models.down = False
    models.results["transcribe"] = heard("Something else entirely")
    again = client.post(f"/api/takes/{kept['id']}/score").json()
    assert again["verdict"] == "retry"
    assert [p["code"] for p in again["problems"]] == ["words"]
    assert prompt["id"] in [p["id"] for p in client.get("/api/studio").json()["queue"]]

    assert client.post(f"/api/takes/{kept['id']}/accept").json()["accepted"] is True
    assert prompt["id"] not in [p["id"] for p in client.get("/api/studio").json()["queue"]]
    assert client.delete(f"/api/takes/{kept['id']}/accept").json()["accepted"] is False
    assert client.post("/api/takes/999/score").status_code == 404


def test_coverage_and_writing_prompts(client: TestClient, models: FakeModels):
    cov = client.get("/api/coverage").json()
    assert (cov["prompts"], cov["waiting"], cov["phonemised"]) == (0, 0, True)
    assert [g["key"] for g in cov["groups"]] == ["phoneme", "pair", "stress", "length", "sentence", "style"]

    r = client.post("/api/prompts/write", json={"count": 2})
    assert r.status_code == 503
    assert r.json()["detail"].startswith("strata-models is not running, so no prompts can be written")
    assert client.post("/api/prompts/write", json={"count": 0}).status_code == 400

    models.down = False
    models.results["write"] = {"text": "nothing useful", "json": None}
    r = client.post("/api/prompts/write", json={"count": 2})
    assert (r.status_code, r.json()["detail"]) == (502, "The prompt writer's answer had no list of prompts. Try again.")

    models.results["write"] = offer(candidate("Is it raining yet?", "prosodic", "worried", "a worried question"))
    done = client.post("/api/prompts/write", json={}).json()  # the default batch size
    assert (done["added"], done["waiting"]) == (1, 1)
    assert models.jobs[-1]["params"]["prompt"].startswith(f"Write {writer.DEFAULT_COUNT} new prompts")
    queue = client.get("/api/prompts").json()
    last = queue[-1]
    assert (last["source"], last["style"], last["cue"]) == ("generated", "worried", "a worried question")
    assert last["score"] > 0
    assert client.get("/api/coverage").json()["waiting"] == 1


def test_a_recording_is_brought_in_ingested_and_removed(client: TestClient, models: FakeModels, tmp_path: Path):
    from stratavoice import ingest

    data = Path(recording(str(tmp_path / "talk.flac"))).read_bytes()
    body = {"Content-Type": "application/octet-stream"}
    refused = client.post("/api/uploads", params={"name": "talk.flac"}, content=data, headers=body)
    assert refused.status_code == 400
    assert "Agree to be recorded" in refused.json()["detail"]
    client.put("/api/settings", json={"consented_on": "2026-11-23"})
    big = client.post(
        "/api/uploads", params={"name": "x.wav"}, content=b"x", headers={**body, "Content-Length": "9" * 11}
    )
    assert big.status_code == 400
    assert "the most accepted" in big.json()["detail"]
    kept = client.post("/api/uploads", params={"name": "talk.flac"}, content=data, headers=body)
    assert kept.status_code == 200, kept.text
    up = kept.json()
    assert (up["name"], up["job"]["state"], up["sentences"]) == ("talk.flac", "queued", 0)
    assert client.post("/api/uploads", params={"name": "again.flac"}, content=data, headers=body).status_code == 400

    queue = client.app.state.queue()  # pyright: ignore[reportAttributeAccessIssue]
    models.down = False
    models.results["transcribe"] = found_heard(lambda: Session(queue.engine))
    models.results["speaker-embedding"] = found_voices
    assert queue.step({ingest.KIND: ingest.handler(lambda: queue.engine)}).state == "done"
    got = client.get(f"/api/uploads/{up['id']}").json()
    assert (got["sentences"], got["kept"], got["other_voice"], got["job"]["state"]) == (3, 2, 1, "done")
    assert got["job"]["progress"]["text"] == "2 of 3 sentences kept"
    assert client.get("/api/uploads/page").json()["items"][0]["id"] == up["id"]
    sentences = client.get("/api/takes/page", params={"upload": up["id"]}).json()["items"]
    assert [t["verdict"] for t in sentences] == ["good", "retry", "good"]
    assert client.get(f"/api/takes/{sentences[0]['id']}/audio").status_code == 200
    assert client.get(f"/api/jobs/{up['job']['id']}").json()["kind"] == "ingest"
    assert client.delete(f"/api/uploads/{up['id']}").json()["sentences"] == 3
    assert client.get(f"/api/uploads/{up['id']}").status_code == 404
    assert client.get("/api/takes/page", params={"upload": up["id"]}).json()["items"] == []


def test_the_server_runs_ingest_jobs_on_its_own_worker(db_env: str, models: FakeModels, tmp_path: Path):
    """Under uvicorn the lifespan starts the worker, so an upload is ingested without anyone running it."""
    import time

    from stratavoice import settings

    settings.SETTINGS.save({"consented_on": "2026-11-23"})
    data = Path(recording(str(tmp_path / "talk.flac"))).read_bytes()
    with TestClient(create_app()) as c:
        queue = c.app.state.queue()  # pyright: ignore[reportAttributeAccessIssue]
        models.down = False
        models.results["transcribe"] = found_heard(lambda: Session(queue.engine))
        models.results["speaker-embedding"] = found_voices
        up = c.post(
            "/api/uploads", params={"name": "t.flac"}, content=data, headers={"Content-Type": "audio/flac"}
        ).json()
        deadline = time.monotonic() + 60
        while c.get(f"/api/uploads/{up['id']}").json()["job"]["state"] != "done" and time.monotonic() < deadline:
            time.sleep(0.2)
        assert c.get(f"/api/uploads/{up['id']}").json()["kept"] == 2


def test_an_upload_over_the_limit_is_refused_as_it_streams_in(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    from stratavoice import ingest, settings

    client.put("/api/settings", json={"consented_on": "2026-11-23"})
    monkeypatch.setattr(ingest, "MAX_UPLOAD_BYTES", 1000)

    def chunks():  # no Content-Length: sent in pieces, so only counting what arrives can refuse it
        yield b"x" * 600
        yield b"x" * 600

    r = client.post("/api/uploads", params={"name": "long.wav"}, content=chunks())
    assert r.status_code == 400
    assert "over 0 MB" in r.json()["detail"]
    assert os.listdir(os.path.join(settings.recordings_dir(), "found", "incoming")) == []  # nothing half kept
