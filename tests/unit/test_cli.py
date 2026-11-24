import importlib
import json
from pathlib import Path

import pytest
from strata_python.testing import FakeModels, sine_wav
from takes import heard, speech

from stratavoice import cli, curriculum, db, settings, studio
from stratavoice.server import app as server_app


def test_doctor_success_and_missing_module(capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch):
    assert cli.main(["doctor"]) == 0
    assert "sqlalchemy" in capsys.readouterr().out

    real_import = importlib.import_module

    def fake_import(name: str):
        if name == "uvicorn":
            raise ImportError("no uvicorn")
        return real_import(name)

    monkeypatch.setattr(importlib, "import_module", fake_import)
    assert cli.main(["doctor"]) == 1
    assert "MISSING  uvicorn" in capsys.readouterr().out


def test_score_judges_the_takes_not_judged_yet(capsys: pytest.CaptureFixture[str], db_env: str, models: FakeModels):
    assert cli.main(["score"]) == 0
    assert "every take is judged" in capsys.readouterr().out
    settings.SETTINGS.save({"consented_on": "2026-11-24"})
    with db.session() as s:
        prompt = next(p for p in studio.prompts(s) if p.kind == "phonetic")
        studio.add_take(s, prompt.id, speech())
        studio.add_take(s, prompt.id, sine_wav(1.0))  # no quiet at all: reads as a noisy room

    assert cli.main(["score"]) == 0
    out = capsys.readouterr().out
    assert "unchecked" in out
    assert "The room is noisy" in out
    models.down = False
    models.results["transcribe"] = heard(prompt.text)
    assert cli.main(["score"]) == 0  # both: neither was heard while strata-models was down
    out = capsys.readouterr().out
    assert (out.count("#"), "good" in out) == (2, True)
    assert cli.main(["score"]) == 0
    assert "every take is judged" in capsys.readouterr().out  # both heard now
    assert cli.main(["score", "--all"]) == 0
    assert capsys.readouterr().out.count("#") == 2
    assert cli.main(["takes"]) == 0
    assert "retry" in capsys.readouterr().out


def test_prompts_takes_and_manifest_commands(capsys: pytest.CaptureFixture[str], db_env: str, tmp_path: Path):
    assert cli.main(["takes"]) == 0
    assert "no takes yet" in capsys.readouterr().out
    assert cli.main(["prompts"]) == 0
    out = capsys.readouterr().out
    assert out.count("waiting") == len(curriculum.STARTER)

    settings.SETTINGS.save({"consented_on": "2026-11-23"})
    with db.session() as s:
        first = studio.prompts(s)[0]
        studio.add_take(s, first.id, sine_wav(1.5))
        studio.skip(s, studio.prompts(s)[1].id)

    assert cli.main(["prompts"]) == 0
    out = capsys.readouterr().out
    assert "1 take(s)" in out
    assert "skipped" in out
    assert cli.main(["prompts", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)[0]["takes"] == 1
    assert cli.main(["takes"]) == 0
    assert "   1.5 s" in capsys.readouterr().out
    assert cli.main(["takes", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)[0]["prompt_id"] == first.id

    assert cli.main(["manifest"]) == 0
    (record,) = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert record["prompt"]["key"] == first.key
    out_file = tmp_path / "manifest.jsonl"
    assert cli.main(["manifest", "-o", str(out_file)]) == 0
    assert "wrote 1 record(s)" in capsys.readouterr().out
    assert json.loads(out_file.read_text(encoding="utf8"))["id"] == record["id"]


def test_set_serve_and_openapi_commands(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    assert cli.main(["set", "consented_on", "2026-11-23"]) == 0
    assert "consented_on = 2026-11-23" in capsys.readouterr().out
    with pytest.raises(SystemExit, match="unknown setting"):
        cli.main(["set", "bad_key", "val"])

    called: list[list[str]] = []
    monkeypatch.setattr(server_app, "main", lambda argv: called.append(argv))
    assert cli.main(["serve", "--host", "0.0.0.0", "--port", "9000"]) == 0
    assert called == [["--host", "0.0.0.0", "--port", "9000"]]

    out = tmp_path / "openapi.json"
    assert cli.main(["openapi", "-o", str(out)]) == 0
    assert '"/api/prompts/{prompt_id}/takes"' in out.read_text(encoding="utf8")
