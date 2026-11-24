# Changelog

Newest first, grouped by day. One entry per change, in the same commit or PR as the change.

## 2026-11-24

**strata-voice: no free-talk prompts (branch `claude/project-thread-cvjjmf`)**
Jonathan does not want "talk freely" prompts, so the starter set's spontaneous group is removed and every prompt is read from its text. The prompt writer already wrote only phonetic, prosodic and expressive prompts.
- `src/stratavoice/curriculum.py`: the `spont-*` seeds and the `spontaneous` kind removed; `style()` always gives one.
- `src/stratavoice/studio.py`: `seed` drops starter prompts the curriculum no longer has unless they have a take; the manifest's text and phonemes are always the prompt's.
- `src/stratavoice/scoring.py`, `coverage.py`, `pilot.py`, `models.py`: the free-talk branches (no WER, the transcript as text) removed.
- Web: `api.ts` (no "Talk freely" group name), `StudioScreen.tsx` (`TakeVerdict` no longer needs the prompt), mock fixtures (`phon-03` and `phon-04` in place of the two free-talk prompts), the free-talk studio test removed. Visual baselines rewritten by `update-visual-baselines.yml`: the studio, takes and coverage shots show the new fixture prompts.
- Tests: the free-talk scoring test removed; a seeding test for an older database; coverage, pilot, studio and integration tests read prompts with text.
- Docs: overview, progress, tests/unit/README.

**strata-voice: the pilot report (branch `claude/project-thread-cvjjmf`)**
Step 4 of the plan is a recorded session, then thresholds tuned from it; the session is Jonathan's to record, so this adds the report that the tuning reads.
- `src/stratavoice/pilot.py` (**new**): `session` (the newest run of takes with no gap over 30 minutes, or every take from a day), `report` (verdicts, takes per prompt, recorded speech, kept speech counted from each prompt's newest usable take as the manifest exports it (Codex review), speech per minute, the crop's lead and tail, and each of `scoring.py`'s checks with its spread, failures and near misses) and `describe`.
- `src/stratavoice/cli.py`: `pilot [--since YYYY-MM-DD] [--json]`.
- Tests: `tests/unit/test_pilot.py` (**new**), `test_cli.py` (the command), integration `test_cli.py` (a fresh studio). Coverage 100%.
- Docs: AGENTS (module and command), overview, implementation-plan (step 4 split into the report, the session and the tuning, with how to run it), progress, tests/unit/README ledger.

**strata-voice: prompts written by a cloud model and ranked by en-GB coverage (branch `claude/project-thread-cvjjmf`)**
Step 3 of docs/implementation-plan.md (Jonathan: "Next work"). After the starter set, a cloud model writes prompts aimed at what the recordings lack, and a local, deterministic ranker asks for the ones that add the most per second first (spec §6, §7.1, §7.3). Needs strata-models#119 (the `write` role) for writing; coverage and ranking need only espeak-ng.

- `src/stratavoice/phonemes.py` (**new**): RP phonemes of a text from espeak-ng (`en-gb-x-rp`, run with the text on stdin), parsed into words with stress patterns, folded into a 43-phoneme inventory (RP's 44 less /ʊə/, merged into /ɔː/ as espeak's RP has it); `Unavailable` when espeak is missing or fails.
- `src/stratavoice/coverage.py` (**new**): a text's units (phonemes, phoneme pairs, stress patterns, length, sentence type, style), counted over every prompt with a usable take (a spontaneous one by its transcript); `rank` orders the generated prompts by new coverage per second, cut by overlap with what is recorded or ranked above (greedy); `due` every 5 usable takes; `coverage()` for the screen and CLI.
- `src/stratavoice/writer.py` (**new**): `write(db, count)` asks strata-models' `write` role for a batch with a brief of what is missing and a JSON schema, keeps the candidates that pass (3 to 30 words, no digits, a known kind; an unknown style is neutral), keyed by a hash of words and cue, then ranks; `WriterFailed` (502) for a bad answer, a failed job or a timeout, `Unavailable` (503) when strata-models is down.
- `src/stratavoice/curriculum.py`: `STYLES` (EmotionML everyday categories, neutral, four stances) and each starter prompt's style.
- `src/stratavoice/models.py`, `migrations/20261124_7866650ef15c_prompt_coverage.py` (**new**): a prompt's `style`, `phonemes`, `writer` and `score`, all nullable.
- `src/stratavoice/studio.py`: seeding stores style and phonemes and fills them on older rows; starter positions counted among the starter set; `PromptOut` gains `style`, `source`, `score`; `score_take` ranks again when due; the manifest gains `phonemes`, `requested_style` as `{vocabulary, category, label}` and the prompt's `writer` (corrects step 1's `{label}` only).
- `src/stratavoice/scoring.py`: `usable()` moved here from studio so coverage can use it.
- `src/stratavoice/settings.py`: `espeak`, the program when it is not on the PATH.
- `src/stratavoice/server/app.py`: `GET /api/coverage`, `POST /api/prompts/write` (`WriterFailed` answers 502). `src/stratavoice/cli.py`: `coverage`, `write`, `rank`, and an optional espeak-ng check in `doctor`.
- Web: `screens/CoverageScreen.tsx` (**new**; what is said and missing per group, least said first, and Write 40 more prompts), on the nav and routes; `api.ts` types and key; mocks `coverage-sample.ts` (**new**, written by the server's own `coverage()` over the starter set's read prompts), handlers for coverage and writing with their states, fixtures with style, source and score; `stories/coverage.stories.tsx` (**new**); the visual config's `coverage` route.
- Web: keeping, keeping anyway, skipping and removing a take also invalidate `keys.coverage` (`StudioScreen.tsx`, `TakesScreen.tsx`), so Coverage is read again when visited next rather than kept for the stale window (Codex review); `CoverageScreen.test.tsx` checks it by keeping a take in the studio and going back.
- `writer.py`: a written prompt whose text matches any prompt already held (case and spacing aside, whatever its cue) is dropped, so a starter or eval sentence written again is neither recorded twice nor leaked into train (starter keys are names, not text hashes, so the key check alone missed them; Codex review); `test_writer.py` offers a starter sentence back.
- Web, from looking at the first baselines: a group's Meter reads "43 of 43" (`valueText`) instead of Meter's default "100% used" with the count under it; a stress pattern writes secondary stress as "Da", since folding it into "da" printed 02, 20 and 00 as three identical "da da" rows. Visual baselines written by `update-visual-baselines.yml`: every screen shot changed for the new Coverage nav item, and the coverage shots are new.
- Tests: `tests/unit/test_phonemes.py`, `test_coverage.py`, `test_writer.py` (**new**), `tests/utils/prompts.py` (**new**), CLI, server, studio and integration CLI tests; web `CoverageScreen.test.tsx` (**new**) and logic tests. Python and web coverage 100%.
- CI: `unit.yml` and `integration.yml` install espeak-ng on every runner (apt, brew, the project's MSI on Windows).
- Docs: README (espeak-ng, the new commands), AGENTS, overview, implementation-plan (step 3 checked), progress, tests/unit/README.

**strata-voice: auto-crop and score each take, and ask again for one that fails (branch `claude/project-thread-cvjjmf`)**
Step 2 of docs/implementation-plan.md, for prompted takes only (Jonathan: "Not much let's just do promoted recordings for now"), so importing existing audio is left for later. The level and word-error code went into strata-python first (jburnhams/strata-python#65), as the shared audio code does.

- `src/stratavoice/scoring.py` (**new**): a take's verdict (`good`, `retry`, `unchecked`) from its levels (`wav.measure`: clipping, quiet, noisy) and its words (strata-models' `transcribe` role through `clients.models`, the word error rate from `wer`), the crop from the word timings, and each problem as a sentence.
- `src/stratavoice/models.py`, `migrations/20261124_2259f52fcd11_take_scores.py` (**new**): the take's verdict, problems, levels, transcript, model, word error rate, crop and `accepted`; nullable or with a server default, so earlier takes read as not scored. The transcript is `Text`, unbounded (Codex review: a 2,000-character cap cut a long spontaneous take's training text).
- `src/stratavoice/studio.py`: `score_take`, `accept_take`, `unscored` (every take not transcribed yet, including a `retry` judged on its levels alone while strata-models was down: Codex review); the queue, progress and manifest count a take unless it is a `retry` not kept anyway; `TakeOut` carries the verdict; the manifest gains `speech`, `asr` and real `quality` fields, and a spontaneous prompt's text is its transcript.
- `src/stratavoice/server/app.py`: a take is judged before the upload answers (in a worker thread); `POST /api/takes/{id}/score`, `POST` and `DELETE /api/takes/{id}/accept`.
- `src/stratavoice/cli.py`: `score [--all]`; `takes` shows each verdict.
- `pyproject.toml`, `uv.lock`: `strata-python[db]>=0.2.14,<0.3` from PyPI, the first release with `wav.measure` and `wer` (strata-python#65; the branch used its commit until then); `pythonpath` for `tests/utils`.
- `tests/utils/takes.py` (**new**), `tests/conftest.py`: speech-like WAVs, transcribe answers, and the `models` fixture (strata-models stood in for, down by default). `tests/unit/test_scoring.py` (**new**), `test_server.py`, `test_cli.py`, `test_studio.py`, `tests/integration/test_server_api.py`: each verdict and problem, the crop, the queue and manifest, the routes and the command, end to end over real HTTP.
- `web/openapi.json`, `web/src/api.generated.ts`: regenerated. `web/src/api.ts`: `crop`, `usable`, `verdictWord`.
- `web/src/screens/StudioScreen.tsx`: the take played from its crop with its verdict; a `retry` take shows its problems with Record again as the filled button, Keep it anyway (K) and Skip; "Checking the take…" while it is judged. `TakesScreen.tsx`: each take's verdict, played from its crop.
- `web/src/mocks/fixtures.ts`, `handlers.ts`: every take judged (`goodScore`, `misreadScore`, `uncheckedScore`), the accept routes, and the `keepMisread`, `keepUnchecked`, `acceptFails` and `takesJudged` states. `web/stories/studio.stories.tsx`, `takes.stories.tsx`: Misread, NotChecked and EveryVerdict. `web/tests/**`: the retry flow, keep anyway, not checked, a spontaneous take, the verdict words.
- `AGENTS.md`, `docs/overview.md`, `docs/implementation-plan.md` (step 2 done), `docs/progress.md`, `tests/README.md`: what changed and why.

## 2026-11-23

**strata-voice: the recording studio shell, on shared recording code (branch `claude/project-thread-cvjjmf`)**
Jonathan asked for a plan for a voice-model app and agreed four steps (docs/implementation-plan.md); this is step 1: a studio that shows one prompt at a time, records a lossless take in the browser, plays back what was kept, and writes a dataset manifest. Midway he asked for the common code to go into strata-react and strata-python ("a lot of the audio components should be common UI stuff"), so capture, the WAV writer, the level meter and verdict are strata-react's (jburnhams/strata-react#303) and the WAV check strata-python's (jburnhams/strata-python#50). Both were taken from their PR commits until released, and now come from npm (1.3.4) and PyPI (0.2.9). The template's sample (greetings, the log screen) is gone.

- Renamed from the template: `src/app` -> `src/stratavoice`, the `strata-voice` console script and launchers (`./strata-voice`, `strata-voice.cmd`), `deploy/strata-voice.service`, `STRATAVOICE_*` settings, port 8370. `pyproject.toml`: name, description, script, `[tool.strata-db]`, `strata_tuning_vars`, `fail_under` 99, `tests/utils` and its `pythonpath` removed (WAVs come from `strata_python.testing.sine_wav`).
- `src/stratavoice/settings.py`: `recordings_dir`, `consented_on`, `max_take_seconds` (`numbers=True`).
- `src/stratavoice/models.py`, `migrations/20261123_..._prompts_and_takes.py` (**new**): prompts and takes; the greetings revision removed.
- `src/stratavoice/curriculum.py` (**new**): the en-GB starter set and an evaluation partition.
- `src/stratavoice/studio.py` (**new**): the queue, keeping a take (consent, `read_wav` with 0.3 s to `max_take_seconds`, an atomic write named by the row's id), paging and removing takes, the manifest. `greet.py` removed.
- `src/stratavoice/system.py`: takes, seconds of speech and the recordings' size on the System page.
- `src/stratavoice/server/app.py`, `landing.html`: the studio's routes; a take is a raw `audio/wav` body, refused over 64 MB from `Content-Length`.
- `src/stratavoice/cli.py`: `prompts`, `takes`, `manifest`; `hello` and `messages` removed.
- `web/openapi.json`, `web/src/api.generated.ts`: regenerated. `web/src/api.ts`: studio types, `postTake`, `takeAudio`, `kindName`.
- `web/src/screens/StudioScreen.tsx`, `TakesScreen.tsx` (**new**): the studio (consent, prompt, Record/Stop/Next on R, N and S, `InputLevel`, the take played back with `TakeLevel`, undoable skip, `Done` at the end) and every take (listen, undoable remove). `SettingsScreen.tsx`, `SystemScreen.tsx`, `Layout.tsx`, `NotFoundScreen.tsx`, `routes.tsx`: the app's settings, numbers and navigation. `GreetingsScreen.tsx`, `LogScreen.tsx` removed.
- `web/package.json`, `web/package-lock.json`: strata-react `^1.3.4` (the release with `useRecorder`), after a few commits that took it from the PR's commit.
- `web/openapi.json`, `web/src/api.generated.ts`: regenerated on strata-python 0.2.9, whose shared contracts are `ApiModel`s, so `Page.total`, `Folder.free_bytes`/`total_bytes` and `ServiceStatus.version`/`detail` are required. `web/src/mocks/handlers.ts`, `web/tests/unit/logic.test.ts`: send them. `web/src/screens/TakesScreen.tsx`: the `next ?? null` workaround removed.
- `web/src/mocks/*`, `web/stories/*`, `web/strata-visual.config.ts`, `web/tests/**`: handlers, fixtures, stories, route states and tests for the studio and takes; `fakeMicrophone` from `strata-react/testing`; the app's own copies of the recorder, microphone and WAV code (`web/src/audio/`, `web/src/mocks/microphone.ts`) removed once the libraries had them. `web/tests/visual/baselines/`: rewritten for the new screens.
- `tests/unit/*`, `tests/integration/*`: the studio, server and CLI tests with real WAV bytes; `test_greet.py` and `test_audio.py` removed.
- Review fixes (Codex on #1): a take keeps the folder it was written to (`takes.root`, folded into the first revision since nothing is released), so changing the recordings folder leaves earlier takes playable and removable and the manifest gives their absolute path; removing a take deletes the file before the row, so a file that cannot be removed leaves the take listed to try again; `docs/deploying.md` says a remote deployment needs a login in front, since the app has none.
- `README.md`, `AGENTS.md`, `docs/overview.md`, `docs/implementation-plan.md`, `docs/progress.md`, `docs/deploying.md` (the microphone needs `https://` or `localhost`), `tests/README.md`, `tests/unit/README.md`, `tests/integration/README.md`, `web/tests/README.md`: rewritten for the app.

**Latest strata-python and strata-react, every dependency current, the template as the example app (branch `claude/project-thread-61o806`)**
Jonathan asked for the template to use the latest strata-python and strata-react, for every other dependency to be at its latest, and for it to adopt the working practices that make it a good starting point for new apps. That meant taking strata-python from PyPI rather than a git source, keeping the sample's greetings in a database through `strata_python.db`, typing the API end to end, and moving the web tooling onto leaflet-node's stack (Biome + oxlint). Correction: the earlier rule that the template ships no database is superseded; greetings now live in SQLite (or Postgres) and `data_dir` is gone.

- `pyproject.toml`, `uv.lock`: `strata-python[db]>=0.2.9,<0.3` from PyPI (after a few commits that took it from #50's commit), dev group `strata-python[dev]` plus hypothesis and diff-cover; lock upgraded; `[tool.strata-db]`; pytest `--import-mode=importlib` so both suites run together.
- `.github/dependabot.yml`: grouped uv, npm and Actions updates. `.github/workflows/upgrade-strata-python.yml`: removed (Dependabot does it).
- `src/app/strata-db.toml`, `src/app/models.py`, `src/app/db.py`, `src/app/migrations/`: **new**; the greetings table, its first revision, and where the records are (`STRATA_DB_URL`/`APP_DATABASE_URL`, else `~/.app/app.db`).
- `src/app/settings.py`: `greeting` and `style` (`choices`); `data_dir` removed.
- `src/app/greet.py`: `ApiModel` contracts (`Greeting`, `Sent`, `Cleared`), database reads and writes, a cursor-paged `Page[Sent]`; times read back from Postgres answered in UTC.
- `src/app/system.py`: the app's own numbers on the shared `/api/system`.
- `src/app/server/app.py`: `base_app(commit=)`, `add_error_handlers`, `add_database`, `add_system`; typed routes. `src/app/server/landing.html`: no data folder.
- `src/app/cli.py`: `hello --save` and `messages` through `db.session()`; `openapi [--check]`.
- `web/openapi.json`, `web/src/api.generated.ts`: **new**, generated (`uv run app openapi`, `npm run api-types`).
- `web/package.json`, `web/package-lock.json`: strata-react 1.3.3 and every dependency at its latest (React Router 8, MSW 3, Vitest 5, Storybook 10.6, Playwright 1.65.1); the TypeScript 6/7 split; `lint`, `format`, `api-types`, `api-types:check`. `web/biome.json`, `web/.oxlintrc.json`: **new**.
- `web/src/api.ts`, `web/src/main.tsx`, `web/src/screens/*`, `web/src/mocks/*`: `createTypedApi`, `appBase()`, `ButtonLink`, `useAsyncAction` field errors, `ChoiceGroup`, the system page from `/api/system`; mocks answer the new shapes (new `systemUnread` state).
- `web/stories/`, `web/tests/`, `web/strata-visual.config.ts`: React Aria roles, `expectOneFilledButton`, new disk-unread story; the selected state presses Space on the row checkboxes.
- `web/tests/visual/baselines/`: all 78 rewritten (React Aria controls, lucide 1.78, Chromium 159, the new system and settings screens).
- `tests/`: the plugin's `db_session`/`db_env`/`live_app` and `strata_python.testing` (`run_cli`, `run_module`, `assert_openapi_current`, the standard database tests) replace the app's own helpers; `tests/utils/fakes.py` removed.
- `.github/workflows/unit.yml`: `strata-db check`, `strata-public-check` on the tree and wheel, unit tests on Postgres, web lint and generated-types check. `update-visual-baselines.yml`: checkout v7.
- `README.md`, `AGENTS.md`, `docs/*`, `deploy/app.service`, `tests/**/README.md`, `web/tests/README.md`: describe the database, the typed API and the new commands; `APP_DATA` and `withBase()` references removed.

## 2026-11-09

**Regenerate visual baselines on the CI runner (branch `claude/project-thread-iw7199`)**
Jonathan wants every dependency kept current, including Dependabot's playwright and lucide-react bumps. Those change the Chromium or the icons behind every screenshot, and a laptop cannot reproduce the CI Chromium, so the baselines are now written by a manual workflow.

- `.github/workflows/update-visual-baselines.yml`: **new**; manual run on a chosen branch: `test:visual:update`, then `test:visual` to prove stability, then commits `web/tests/visual/baselines` to that branch.
- `AGENTS.md`: CI section mentions it.

**Move onto the strata-python library (branch `claude/project-thread-iw7199`)**
Jonathan asked for the shared server code to live in a `strata-python` project (like strata-react) so the template stops duplicating it, and for apps to track its latest. This replaces the template's own copies; behaviour is unchanged except where noted.

- `pyproject.toml`, `uv.lock`: depend on `strata-python` as a git source tracking `main` (the lock pins the commit); pytest options `strata_env_prefix`/`strata_tuning_vars` configure the library's plugin.
- `src/app/oslib.py`, `scripts/check.py`, `tests/utils/http_server.py`, `tests/unit/test_oslib.py`, `tests/unit/test_http_server.py`: **removed**, now `strata_python.oslib`, `strata-check` and the plugin's `http_server` fixture (the library tests them, with real processes and sockets).
- `src/app/settings.py`: declares the two settings with `strata_python.settings.Settings`; same files and `APP_*` variables. Corrections: a bad `data_dir` or blank greeting now raises ValueError from `save` (the API answers 400, as it did for a relative path), `~` in `data_dir` is expanded when saved, and a bad stored or environment value falls back to the default instead of crashing.
- `src/app/server/app.py`, `src/app/cli.py`: health, settings and page routes, `serve`, `doctor` and `set` come from the library; the app keeps its own routes and `hello`/`messages`.
- `tests/conftest.py`: hermetic environment, no-network guard and `http_server` fixture removed (plugin). The `fake_*` fixtures stay as last resorts.
- `scripts/check`, `.github/workflows/unit.yml`: run `strata-check`. `.github/workflows/upgrade-strata-python.yml` **new**: weekly lock upgrade that runs the gate and opens a PR.
- `AGENTS.md`, `README.md`: describe the library, the tracking-main rule and the upgrade workflow.

**Testing policy: real code over mocks (branch `claude/project-thread-iw7199`)**
Asked to steer tests away from mocks towards real HTTP, embedded databases and installed tools, and to make skipping deliberate.

- `AGENTS.md`: **new** Testing policy section (real by default; mocks only for true externals in quick many-case unit tests; install ffmpeg and the like instead of mocking; no silent skips, a skip is a marker with a reason and a switch; machine-heavy tests are marked and run where the machine is).
- `tests/utils/http_server.py`, `tests/unit/test_http_server.py`: **new**. A real loopback HTTP server scripted per test (`http_server` fixture in `tests/conftest.py`); a request no route answers fails the test at teardown.
- `tests/utils/fakes.py`: docstring marks the doubles as a last resort. `tests/README.md`: layout notes point to the policy.
- `pyproject.toml`: ruff `TID` rules selected, `pytest.importorskip` banned with the reason.

**AGENTS.md reorganised as the basis for apps made from the template (branch `claude/project-thread-iw7199`)**
Asked to make the agent instructions suitable as the starting point for future apps, and to point database work at the shared database project.

- `AGENTS.md`: regrouped into rules for every change (run `scripts/check`, changelog and docs in the same commit, comment the why, no secrets or machine-specific details, strict types, tests, report what was run), layout, Python tooling, tests, web, CI and a closing checklist. Says which parts to keep unchanged in a derived app. Content of the earlier bullets is kept.
- `AGENTS.md`: **new** Database section. Apps use [jburnhams/database](https://github.com/jburnhams/database) (one shared database, one schema per app, models and migrations in the app repo, `dbtool check` in CI, never one database per app) and link its adoption guide rather than repeating it.

**Generic deployment notes and a systemd unit example (branch `claude/project-thread-iw7199`)**
A Docker image was dropped from the plan because apps are not deployed that way. These files are deliberately free of machine-specific details.

- `deploy/app.service`: **new**. Example systemd user unit running `uv run --locked --no-dev app serve`.
- `docs/deploying.md`: **new**. Build, install, run, reverse-proxy and how to keep a service file in step with the repo.
- `AGENTS.md`: points to them; the stale `setup_env` mention is gone (corrects the earlier line left behind by the uv change).

**Move the Python side to uv, typed strict, one gate (branch `claude/project-thread-iw7199`)**
Asked for an evaluation of this template against current best practice; the tooling gaps it found are closed here. Behaviour of the app is unchanged.

- `pyproject.toml`: now a real project (`[project]`, hatchling build, `app` console script, `[dependency-groups] dev`), with `--strict-markers --strict-config` for pytest, ruff rules `E,F,I,B,UP,SIM,RUF,C4,PT,S` at line length 120, and pyright strict.
- `uv.lock`, `.python-version`: **new**. Builds are reproducible; CI installs with `uv sync --locked`.
- `requirements.txt`, `requirements-test.txt`, `scripts/setup_env.sh`, `scripts/setup_env.ps1`: **removed**; `uv sync` replaces them. `app` and `app.cmd` stay as thin wrappers over `uv run app`.
- `scripts/check`, `scripts/check.py`: **new**. The one gate (lockfile, ruff lint and format, pyright, ty, unit tests with coverage) for git hooks, agents and CI.
- `src/app/`: fully annotated; `__version__` now reads the package metadata. `oslib.py` relaxes pyright for that one file because its Windows branches use APIs the Linux stubs lack. Formatting is `ruff format` (separate commit, no behaviour change).
- `tests/`: new `test_version.py` and a partial-settings test (coverage is 100% again); a few asserts split for ruff's PT018.
- `.github/workflows/unit.yml`, `integration.yml`: uv with cache; lint, format and types run once on Linux 3.13; weekly `uv audit`. `.github/dependabot.yml`: **new** (uv, npm, actions).
- README, AGENTS.md, test READMEs, docs: commands updated to uv and `scripts/check`.
- Not done yet: Dockerfile and systemd unit, copier conversion, release workflow (next phases).
