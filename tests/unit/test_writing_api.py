"""The written voice's HTTP API and commands, over the stand-in for strata-takeout's views."""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from writing import Source, at

from stratavoice import cli
from stratavoice.writing import corpus

LONG = "this is a reply long enough to count as something that says a little about how a person writes"


def run_jobs(client: TestClient) -> None:
    """Run the queued build where the test can see it (the server's worker is off in the `client` fixture)."""
    queue = client.app.state.queue()  # type: ignore[attr-defined]
    engine = queue.engine
    while queue.step({corpus.KIND: corpus.handler(lambda: engine)}) is not None:
        pass


def test_build_browse_and_check_over_http(client: TestClient, writing_source: Source) -> None:
    writing_source.mine("ok", at(0), conversation="a")
    writing_source.mine(LONG, at(0, days=1), conversation="b")
    assert client.get("/api/writing").json()["rows"] == 0
    task = client.post("/api/writing/build").json()
    assert task["kind"] == "writing"
    assert client.post("/api/writing/build").json()["id"] == task["id"]  # one build at a time
    run_jobs(client)
    summary = client.get("/api/writing").json()
    assert summary["rows"] == 2
    assert summary["job"]["state"] == "done"
    assert summary["job"]["result"]["rows"] == 2
    page = client.get("/api/writing/page", params={"limit": 1}).json()
    assert [w["text"] for w in page["items"]] == [LONG]
    assert client.get("/api/writing/page", params={"after": page["next"]}).json()["items"][0]["text"] == "ok"
    assert client.get("/api/writing/page", params={"trivial": "false"}).json()["items"][0]["text"] == LONG
    (row,) = client.get("/api/writing/check", params={"medium": "chat-direct"}).json()
    marked = client.post(f"/api/writing/{row['id']}/check", json={"verdict": "clean"}).json()
    assert marked["checked_as"] == "clean"
    assert client.get("/api/writing/check", params={"medium": "chat-direct"}).json() == []
    assert client.delete(f"/api/writing/{row['id']}/check").json()["checked_as"] is None
    bad = client.post(f"/api/writing/{row['id']}/check", json={"verdict": "great"})
    assert bad.status_code == 400
    assert "not a verdict" in bad.json()["detail"]
    assert client.post("/api/writing/999/check", json={"verdict": "clean"}).status_code == 404


def test_a_build_without_the_views_fails_with_the_reason(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STRATAVOICE_WRITING_URL", "")
    client.post("/api/writing/build")
    run_jobs(client)
    job = client.get("/api/writing").json()["job"]
    assert job["state"] in ("failed", "queued")
    assert "unified.my_writing could not be read" in (job["error"] or "")


def test_the_writing_commands(
    capsys: pytest.CaptureFixture[str], db_env: str, writing_source: Source, tmp_path: Path
) -> None:
    assert cli.main(["writing", "corpus"]) == 0
    assert "nothing built yet" in capsys.readouterr().out
    writing_source.mine("ok", at(0), conversation="a")
    writing_source.mine(LONG, at(0, days=1), conversation="b")
    writing_source.mine("a mail\n-- \nme", at(0, days=2), platform="email", kind="email", conversation="t")
    assert cli.main(["writing", "build"]) == 0
    out = capsys.readouterr().out
    assert "read 3 rows; 3 kept" in out
    assert "sealed from 2019-01-03" in out
    assert cli.main(["writing", "corpus"]) == 0
    out = capsys.readouterr().out
    assert "chat-direct" in out
    assert "2 rows (1 trivial)" in out
    assert cli.main(["writing", "corpus", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["rows"] == 3
    assert cli.main(["writing", "export"]) == 0
    assert [json.loads(line)["text"] for line in capsys.readouterr().out.splitlines()] == [LONG]
    target = tmp_path / "writing.jsonl"
    assert cli.main(["writing", "export", "--trivial", "-o", str(target)]) == 0
    assert "wrote 3 record(s)" in capsys.readouterr().out
    assert len(target.read_text(encoding="utf8").splitlines()) == 3


def test_writing_settings_are_checked(monkeypatch: pytest.MonkeyPatch) -> None:
    from stratavoice import settings

    assert settings.writing_tables() == ("unified.my_writing", "unified.messages_all", "unified.emails_all")
    assert settings.writing_url() == ""
    assert str(settings.assistant_since()) == "2022-11-30"
    # A name that is not a plain identifier never reaches SQL: the override is ignored for the default.
    monkeypatch.setenv("STRATAVOICE_WRITING_SOURCE", "x; drop table writing")
    assert settings.writing_tables()[0] == "unified.my_writing"
    with pytest.raises(ValueError, match="not a table name"):
        settings.table_name("x; drop table writing")
    assert settings.table_name(" my_writing ") == "my_writing"
    monkeypatch.setenv("STRATAVOICE_ASSISTANT_SINCE", "")
    assert settings.assistant_since() is None


def test_the_corpus_command_names_the_flags(
    capsys: pytest.CaptureFixture[str], db_env: str, writing_source: Source
) -> None:
    writing_source.mine(LONG, at(0), conversation="a")
    writing_source.mine(LONG, at(0, days=1), conversation="b")
    assert cli.main(["writing", "build"]) == 0
    capsys.readouterr()
    assert cli.main(["writing", "corpus"]) == 0
    assert "flags: duplicate 1" in capsys.readouterr().out
