# strata-voice

Records a person's spoken voice, and later their written one, so a model of it can be built. Step one is the recording studio: it shows one prompt at a time, records a lossless take from the browser, plays back what was kept, and keeps a dataset manifest of the takes. Later steps crop and score each take automatically and ask again for the ones that are not good enough, then generate new prompts aimed at what the recordings still lack ([docs/implementation-plan.md](docs/implementation-plan.md)).

Everything runs on the speaker's own computer. The takes stay in a folder there and are sent nowhere else. Model work (transcribing, scoring, generating prompts) goes through [strata-models](https://github.com/jburnhams/strata-models), which hosts and evaluates the models; this app only orchestrates.

It is a FastAPI server and CLI (`src/stratavoice/`) on [strata-python](https://github.com/jburnhams/strata-python), with a React web app (`web/`) on [strata-react](https://github.com/jburnhams/strata-react), made from [python-app-template](https://github.com/jburnhams/python-app-template).

## Quick start

```bash
uv sync                                   # creates .venv from uv.lock (install uv: https://docs.astral.sh/uv/)
cd web && npm ci && npm run build && cd ..
uv run strata-voice doctor                # check the environment
uv run strata-voice serve                 # the studio on http://127.0.0.1:8370/
uv run strata-voice prompts               # the queue, in order
uv run strata-voice takes                 # the takes kept, newest first
uv run strata-voice manifest -o takes.jsonl   # one record per prompt (its newest take), for training
```

`./strata-voice` and `strata-voice.cmd` wrap `uv run strata-voice`.

**The microphone needs a secure page.** Browsers allow `getUserMedia` only at `https://` or `http://localhost` (and `127.0.0.1`), so open the studio at one of those. From another machine, put it behind HTTPS ([docs/deploying.md](docs/deploying.md)). The studio turns off the browser's echo cancellation, noise suppression and automatic gain, because each one reshapes a voice, and it records 16-bit PCM WAV at the microphone's own rate.

Takes go to `~/.stratavoice/recordings/human/` (`uv run strata-voice set recordings_dir /path` moves them), and the records go to a SQLite file in `~/.stratavoice/` unless `STRATA_DB_URL` or `STRATAVOICE_DATABASE_URL` names a database. Nothing is recorded until the speaker agrees on the consent card; withdrawing consent in Settings stops recording.

For hot-reload frontend work, run `uv run strata-voice serve` in one terminal and `cd web && npm run dev` in another (Vite proxies `/api` to `127.0.0.1:8370`).

## Documentation

| Document | What it is |
|---|---|
| [docs/overview.md](docs/overview.md) | The design brief: goals, architecture, layout. |
| [docs/implementation-plan.md](docs/implementation-plan.md) | The steps, in order, and what is done. |
| [docs/progress.md](docs/progress.md) | The log of what was tried, measured and decided. |
| [docs/deploying.md](docs/deploying.md) | Running it as a service. |
| [AGENTS.md](AGENTS.md) | Repository conventions and commands (for people and coding agents). |

## Tests

```bash
uv run pytest tests/unit --cov                 # unit tests + coverage (CI gates on fail_under in pyproject.toml)
uv run pytest tests/integration -n auto        # CLI and HTTP API end to end, with real WAV uploads
uv run pytest tests/unit --pg                  # the unit suite on a throwaway Postgres (needs Postgres installed)
uv run strata-db check                         # the migrations match the models
scripts/check                                  # the whole gate (strata-check): lockfile, ruff, pyright strict, ty, unit tests + coverage
cd web && npm run lint                         # Biome, then oxlint with type information
cd web && npm run api-types:check              # api.generated.ts matches web/openapi.json
cd web && npm run test:coverage:gate           # web unit + jsdom integration tests against coverage-floor.json
cd web && npm run storybook                    # every screen in every server state, on :6006
cd web && npm run test:visual                  # screenshots of the app and Storybook, light and dark, against the baselines
```

The tests record from strata-react's `fakeMicrophone` (a tone at a chosen level, or a refusal), because the microphone is hardware. The web app needs Node 26 (`.nvmrc`). The visual suite needs the Chromium of the pinned Playwright (`cd web && npx playwright install chromium`); write baselines in that Chromium on Linux, as CI does, or run the `update-visual-baselines` workflow on the branch.

See [tests/README.md](tests/README.md) and [web/tests/README.md](web/tests/README.md) for the test layout and conventions.
