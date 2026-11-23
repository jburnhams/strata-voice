# Deploying

The app is one process: `uv run strata-voice serve` (FastAPI plus the built React app). Run it however you run long-lived services; [deploy/strata-voice.service](../deploy/strata-voice.service) is a systemd user-unit example.

1. Build the web app once per checkout: `cd web && npm ci && npm run build` (writes into `src/stratavoice/server/static/`).
2. `uv sync --locked --no-dev` installs the runtime dependencies only.
3. Choose where the takes go: `recordings_dir` (default `~/.stratavoice/recordings`). They are the masters a model is trained from and can be used to imitate the speaker, so keep the folder private and backed up.
4. Choose where the records go. With nothing set they go to a SQLite file in the app's home, `~/.stratavoice/stratavoice.db` (move it with `STRATAVOICE_HOME`), outside the checkout, so a fresh checkout keeps them. For the shared Postgres, give the service `STRATAVOICE_DATABASE_URL` (or `STRATA_DB_URL`) and `STRATA_DB_LIVE=1` from an environment file only the service user can read; strata-python's README ("Database") has the rest. The schema is migrated when the server first needs it.
5. Start `uv run --locked --no-dev strata-voice serve --host 127.0.0.1 --port <port>`. In a service, give uv's full path: systemd does not search `~/.local/bin`.
6. **The microphone needs a secure page**: browsers allow recording only at `https://` or `http://localhost`. On the machine itself, open `http://localhost:<port>/`. From anywhere else, put a reverse proxy with TLS **and a login** in front: the app has no accounts of its own, and anyone who reaches it can list, play and remove the takes. It listens on 127.0.0.1 unless `--host` says otherwise; keep it that way behind a proxy. The app works under a path prefix (`/<prefix>/`) with no configuration: see "Reverse-proxy support" in [AGENTS.md](../AGENTS.md). Forward the prefix-stripped path to the app.
7. Check `GET /api/health`: it returns `{"ok": true, "version": ..., "commit": ...}` (`commit` is the checkout's, or null for an installed wheel).

## Keep the service and the repo in step

A service file that names a launch command can go stale when the repo is restructured, and the failure only shows as a restart loop. So:

- Start the app only through the `strata-voice` console script (`uv run strata-voice serve`), never through a path to a source file.
- Change the unit in the same change as any rename of the package, the command or the port.
- After a restart, a port that answers is not proof the right app is running: compare `/api/health`'s `commit` with the checkout's (`git rev-parse HEAD`).
- Records live outside the checkout (step 3), so redeploying never touches them; a new revision in `src/stratavoice/migrations/` is applied on the first request after the restart.
