# Unit tests

Shared commands, layout, hermetic setup and file-ownership rules are in [`tests/README.md`](../README.md); read that first. This file is owned by unit-test work.

Fast and isolated: synthetic data, a migrated SQLite copy per test for the records; no external services, no network. `pytest tests/unit --cov` is what CI gates on (`fail_under` in `pyproject.toml`).

## Where things are tested

| Module | Tests | Coverage | Status | Notes |
| --- | --- | --- | --- | --- |
| `settings.py` | `test_settings.py` | 100% | done | defaults (the recordings folder in the app home), environment overrides, save, validation and reset |
| `curriculum.py` | `test_curriculum.py` | 100% | done | the starter set: every kind present, an evaluation partition, keys stable and unique |
| `studio.py` | `test_studio.py` | 100% | done | seeding once in order, the queue past recorded and skipped prompts, a take written as a WAV master, consent and bad files refused, a failed write keeps nothing, paging and removing takes with their files, the manifest |
| `models.py`, `migrations/` | `test_database.py` | 100% | done | strata-python's standard tests: migrations up and down, schema matches the models |
| `system.py` | `test_system.py` | 100% | done | folder sizes (files that vanish mid-walk) |
| `cli.py`, `db.py` | `test_cli.py` | 100% | done | doctor, prompts, takes and manifest (text and JSON), set, serve delegation, openapi |
| `server/app.py` | `test_server.py` | 100% | done | the committed `openapi.json`, landing/static index with its relative `<base>`, consent then a WAV kept, refusals (channels, too short, too big), skip and unskip, paging, take audio, removal, the manifest, system, settings, `main` |
