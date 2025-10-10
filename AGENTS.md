# Repository Guidelines

## Project Structure & Module Organization
- `osm_meet_your_mappers/` contains the FastAPI application: `api.py` exposes routes, `db.py` handles Postgres access, and `config.py` stores runtime settings.
- `osm_meet_your_mappers/static/` serves the bundled single-page frontend.
- `scripts/` hosts data pipeline tools (`archive_loader.py`, `backfill.py`, `load_admin_boundaries.py`) and `setup_db.sql`; trigger them through Docker services.
- `docker-compose.yml` wires database, loader, and API containers, and the `Makefile` offers wrappers; copy `.env.example` to `.env` before starting.

## Build, Test, and Development Commands
- `pip install -e .[dev]` installs the app plus developer extras in your virtualenv.
- `make dev` launches the dev Compose profile (API + database); `make up-dev` runs it in the background.
- `make initialization` (or `make up-init -d`) performs the initial changeset import using `.env` paths.
- `docker compose --profile production up -d` mirrors production locally for regression checks.
- `make logs` and `make status` inspect container output and health across profiles.

## Coding Style & Naming Conventions
- Target Python 3.9+ and keep code formatted with `black` (88 columns) and imports sorted with `isort`; run both before every PR.
- Follow PEP 8: 4-space indentation, snake_case for modules/functions, PascalCase for classes, uppercase for constants and env vars.
- Prefer type hints on new functions and keep endpoint behavior self-explanatory.

## Testing Guidelines
- Use `pytest` for new coverage; place files under `tests/` mirroring the module under test (`tests/test_api.py`, etc.).
- Name test functions `test_<behavior>` and reuse fixtures for Postgres logic; spin up the Compose database when integration coverage is needed.
- Run `pytest --cov=osm_meet_your_mappers` to confirm new code is exercised and note any intentional gaps in the PR.

## Commit & Pull Request Guidelines
- Craft commits in imperative mood (`Add loader retry logic`), keeping the first line under ~72 characters; mention related issues with `#<id>` when applicable.
- Squash noisy WIP commits before pushing and document database or loader impacts when touching `scripts/setup_db.sql`.
- PRs should include a concise summary, configuration or environment updates, relevant command output, and UI screenshots when static assets change.

## Configuration & Security Tips
- Keep secrets in `.env` only; never commit OAuth credentials or large data paths (`PG_DATA_HOST_PATH`, `LOADER_CHANGESET_FILE`).
- When sharing reproduction steps, reference sanitized paths and avoid leaking local disk locations or authenticated download URLs.
