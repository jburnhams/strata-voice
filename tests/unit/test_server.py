from pathlib import Path

import pytest
import uvicorn
from fastapi.testclient import TestClient
from strata_python.testing import FakeModels, assert_openapi_current, sine_wav
from takes import heard, speech

from stratavoice import __version__, curriculum
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
