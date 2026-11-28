"""Fixtures both suites share. Most come from the strata-python pytest plugin, configured in pyproject.toml: a fresh
home and settings folder for every test (`isolated_env`), no outbound network, `http_server` and `live_app` for real
HTTP, the `fake_*` last-resort doubles, the `integration` marker under tests/integration, and, because the app
declares its database (`[tool.strata-db]`), `db_session`, `db_engine`, `db_url` and `db_env` on a freshly migrated
SQLite copy (or a throwaway Postgres with `--pg`)."""

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from strata_python.testing import FakeModels
from writing import Source, source


@pytest.fixture
def models(fake_models: FakeModels) -> FakeModels:
    """strata-models, stood in for over real HTTP (the plugin's `fake_models`), down until a test gives it answers:
    a take is then judged on its levels alone and comes back `unchecked`, as when the service is not running. Set
    `models.down = False` and `models.results["transcribe"] = takes.heard("...")` to have its words heard."""
    fake_models.down = True
    return fake_models


@pytest.fixture
def client(db_env: str, models: FakeModels) -> Iterator[TestClient]:
    """The HTTP API on a fresh migrated test database, with strata-models down (`models`). Used as a context manager so
    the server's lifespan runs, as under uvicorn: the engine is disposed when the test ends (a SQLite file left open
    cannot be removed on Windows). The ingest worker is off: a test runs an upload's job itself
    (`c.app.state.queue().step(...)`, see tests/unit/test_ingest.py), so it sees each stage."""
    from stratavoice.server.app import create_app

    with TestClient(create_app(worker=False)) as c:
        yield c


@pytest.fixture
def writing_source(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Source]:
    """strata-takeout's views of what the person wrote, stood in for by real tables in a SQLite file
    (tests/utils/writing.py), with the writing settings pointed at them. Empty until a test adds rows."""
    src = source(str(tmp_path / "takeout.db"))
    src.use(monkeypatch)
    try:
        yield src
    finally:
        src.engine.dispose()
