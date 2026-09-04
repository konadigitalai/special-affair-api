# specialaffair-api

Phase 1 FastAPI infrastructure for SpecialAffair. It intentionally contains no business-domain API or tables.

## Local setup

Requires Python 3.12 and PostgreSQL 16. Create a virtual environment, then install the app and development tools:

```bash
python -m venv .venv
.venv/Scripts/activate
pip install -e ".[dev]"
copy .env.example .env
```

Set `ENVIRONMENT`, `DATABASE_URL`, `DATABASE_MIGRATION_URL`, `AUTH0_DOMAIN`, and `AUTH0_AUDIENCE`; `LOG_LEVEL` defaults to `INFO`. Keep the application DML role and schema-owning migration role separate.

Run the API with `uvicorn app.main:app --reload`. Run the worker with `python -m app.workers.main`.

Create a migration with `alembic revision --autogenerate -m "description"` and apply migrations with `alembic upgrade head`. Alembic exclusively uses `DATABASE_MIGRATION_URL`.

Run checks with `pytest` and `mypy app tests`.
