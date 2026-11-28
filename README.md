# strata-voice

Records a person's spoken voice, and later their written one, so a model of it can be built. Step one is the recording studio: it shows one prompt at a time, records a lossless take from the browser, plays back what was kept, and keeps a dataset manifest of the takes. Each take is cropped and scored as it is kept, and one that is not good enough is asked for again. The Hands-free screen listens all the time instead: read the prompts aloud one after another, and each take is cut out, kept and judged in the background, with a poor one put back in the queue. After the starter set, a cloud model writes new prompts aimed at what the recordings still lack (sounds, sentence types, styles), and a local ranker asks for the ones that add the most first ([docs/implementation-plan.md](docs/implementation-plan.md)). The Upload screen brings in a recording made elsewhere (a voice note, a talk, a video, in any format ffmpeg reads): it is levelled, transcribed, cut into sentences, each sentence checked for the speaker's voice against their studio takes, and the sentences that pass are judged like studio takes and join the dataset. The My writing screen is step 1 of the written voice: everything the speaker sent (emails, chats, posts, prompts to assistants, read from strata-takeout's views), cleaned of quoted text and signatures, chat lines joined, short replies set aside, and split into train, dev and a sealed test set frozen before anything learns from it ([docs/written-voice.md](docs/written-voice.md)).

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
uv run strata-voice coverage              # which sounds, stress patterns, sentence types and styles are said, least first
uv run strata-voice write --count 40      # have the prompt writer (strata-models' `write` role) add prompts, then rank them
uv run strata-voice rank                  # order the written prompts by what they would add
uv run strata-voice pilot                 # the newest session's takes against each scoring threshold, to tune them
uv run strata-voice ingest talk.m4a       # bring in a recording: level, transcribe, cut into sentences, keep the speaker's
uv run strata-voice writing build         # the written corpus from strata-takeout's views: clean, join, split
uv run strata-voice writing corpus        # what it holds, by medium and split
uv run strata-voice writing export -o writing.jsonl   # the pieces as JSON lines, copies and short replies left out
```

**Install espeak-ng** (`apt install espeak-ng`, `brew install espeak-ng`, or the MSI from [its releases](https://github.com/espeak-ng/espeak-ng/releases) on Windows). It turns each prompt into British (RP) phonemes for the coverage ranker. Without it the studio still records, but sounds are not counted; `uv run strata-voice set espeak /path/to/espeak-ng` names it when it is not on the PATH, and `doctor` says whether it was found. CI installs it on every runner.

**Install ffmpeg** (`apt install ffmpeg`, `brew install ffmpeg`, `winget install Gyan.FFmpeg`). Bringing in a recording decodes and levels it with `ffmpeg` and `ffprobe`; the studio itself does not need them. CI installs them on every runner. Checking whose voice a sentence is needs strata-models' `speaker-embedding` role (its `speaker` worker venv); without it the sentences are kept with "voices not checked".

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
