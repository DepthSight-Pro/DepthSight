# Open Source Guide

This document is a short public companion to the main README. It focuses on the minimum information a new contributor needs to get the project running and to avoid unsafe defaults.

## Recommended path

1. Read [README.md](../README.md) for the high-level system map.
2. Copy `.env.example` to `.env`.
3. Start with testnet or paper trading.
4. Run the backend tests.
5. Bring up the frontend only after the API is healthy.

## Runtime model

The project is organized as a small service cluster:

- `api.depthsight_api:app` provides the REST API.
- `api.websocket_server:app` pushes real-time state to clients.
- `bot_runner.py` starts the trading runtime.
- `tasks.py` exposes the Celery app used for long-running jobs.
- `frontend/` is the web dashboard.
- `pwa/` is the mobile-oriented client.

Docker Compose wires these services together with PostgreSQL and Redis.

On Windows, activate the virtual environment with `.venv\Scripts\activate`. On Unix-like shells, use `source .venv/bin/activate`.

## Configuration rules

- Keep `.env` local.
- Never commit API keys, secrets, backups, or generated data.
- Use testnet credentials for first boot.
- Treat live-trading settings as production-only.
- If you enable optional integrations such as email, push notifications, AI providers, or billing, verify each one independently.

## Suggested verification

After changing backend logic:

```bash
pytest
```

After changing the web dashboard:

```bash
cd frontend
npm run build
```

After changing the PWA:

```bash
cd pwa
npm run build
```

For changes touching order execution, risk controls, or backtesting, prefer the existing test suite over manual spot checks.

## Contributing notes

- Keep edits scoped to the behavior you changed.
- Add regression tests when you fix a bug.
- Document new environment variables in `.env.example`.
- If a change alters startup order, update the README and this guide together.

## Publishing checklist

Before making the repository public:

- Add a license file.
- Remove any leftover secrets from the worktree and git history.
- Verify `.gitignore` still excludes generated data, logs, caches, and local state.
- Confirm that the README starts cleanly from a fresh clone.
