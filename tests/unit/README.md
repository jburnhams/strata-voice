# Unit tests

Shared commands, layout, hermetic setup and file-ownership rules are in [`tests/README.md`](../README.md); read that first. This file is owned by unit-test work.

Fast and isolated: synthetic data, a migrated SQLite copy per test for the records; no external services, no network. `pytest tests/unit --cov` is what CI gates on (`fail_under` in `pyproject.toml`).

## Where things are tested

| Module | Tests | Coverage | Status | Notes |
| --- | --- | --- | --- | --- |
| `settings.py` | `test_settings.py` | 100% | done | defaults (the recordings folder in the app home), environment overrides, save, validation and reset; the writing views' names checked as identifiers and the assistant date |
| `curriculum.py` | `test_curriculum.py` | 100% | done | the starter set: every kind present, an evaluation partition, keys stable and unique |
| `studio.py` | `test_studio.py` | 100% | done | seeding once in order, the queue past recorded and skipped prompts, a take written as a WAV master, consent and bad files refused, a failed write keeps nothing, paging and removing takes with their files, the queue paged by a cursor, the manifest |
| `phonemes.py` | `test_phonemes.py` | 100% | done | the real espeak-ng: RP phonemes, stress patterns, folds into the inventory, a text that looks like an option, espeak missing or failing |
| `coverage.py` | `test_coverage.py` | 100% | done | sentence types, a text's units, an empty inventory, only usable takes counted, the ranker's order and redundancy, ranking every five usable takes, filling style and phonemes on old rows, coverage without espeak |
| `pilot.py` | `test_pilot.py` | 100% | done | nothing recorded; a session's verdicts, speech, crops and each check; a break starting a session; failures and near misses |
| `ingest.py` | `test_ingest.py` | 100% | done | a real ffmpeg on a FLAC of three sentences (one in another voice): levelling and its gain cap, sentences from words (ends, gaps, long ones split, short ones dropped, padding never past a neighbour), the voice reference from studio takes or the recording, an upload refused (consent, empty, duplicate, unreadable, no audio), the job end to end with strata-models down (waits, then a retry starts over) or without the speaker role (voices not checked), stopped part way, paged and removed with its files |
| `writing/clean.py` | `test_writing_clean.py` | 100% | done | quotes (attribution on one or two lines, with and without `>`), Outlook headers, forwards, signatures and footers as spans over the original; learnt signatures need repeats and the shape of one; the leak check |
| `writing/split.py` | `test_writing_split.py` | 100% | done | the draw, the frozen cutoff and held-out recipients, each split assigned, the highest of a cluster |
| `writing/source.py`, `writing/corpus.py` | `test_writing_corpus.py`, `test_writing_api.py` | 100% | done | a real SQLite file holding strata-takeout's three views (`tests/utils/writing.py`): chat runs and groups, mail cleaned and leaks flagged, posts and prompts, trivial rows, copies and clusters, the frozen split and checks kept over a rebuild, missing views named, paging, checks, summary, export; the build as a job over HTTP and the `writing` commands |
| `writer.py` | `test_writer.py` | 100% | done | a batch kept, phonemised and ranked; rule-breaking and repeated candidates dropped; the brief; batch size; the service down, a bad answer, a failed job, a timeout |
| `models.py`, `migrations/` | `test_database.py` | 100% | done | strata-python's standard tests: migrations up and down, schema matches the models |
| `system.py` | `test_system.py` | 100% | done | folder sizes (files that vanish mid-walk) |
| `cli.py`, `db.py` | `test_cli.py` | 100% | done | doctor, prompts, takes and manifest (text and JSON), ingest (kept, refused), set, serve delegation, openapi |
| `server/app.py` | `test_server.py` | 100% | done | the committed `openapi.json`, landing/static index with its relative `<base>`, consent then a WAV kept, refusals (channels, too short, too big), skip and unskip, paging, take audio, removal, the manifest, system, settings, `main` |
