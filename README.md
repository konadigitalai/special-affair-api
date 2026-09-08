# Special Affair backend

FastAPI modular monolith with PostgreSQL, Auth0 authorization, a separate polling
worker, and sandbox commerce workflows. This repository contains backend code only.
Read [the architecture review](docs/architecture-review.md) for coverage and remaining work.

## Local setup

Requires Python 3.12 and PostgreSQL 16. A local `.env` exists in this workspace and
is ignored by Git. For a fresh checkout:

```powershell
python -m venv .venv
.venv/Scripts/Activate.ps1
pip install -e ".[dev]"
Copy-Item .env.example .env
```

Fill these values in `.env`:

| Setting | Required value |
| --- | --- |
| DATABASE_URL | Application-role URL using postgresql+asyncpg://. |
| DATABASE_MIGRATION_URL | Schema-owning role URL for the same database. |
| AUTH0_DOMAIN | Tenant hostname, without https://. |
| AUTH0_AUDIENCE | Auth0 API identifier. |
| FRONTEND_URLS | Comma-separated allowed frontend origins. |
| TOKEN_SIGNING_SECRET | Random stable secret; generated in this local workspace. |
| SANDBOX_PAYMENT_SECRET | Sandbox webhook secret; generated in this workspace. |

Optional settings configure return URL, stock TTL, refund threshold, return window,
provisional tax/shipping policies and Azure telemetry/storage. Live payment/shipping
keys can be added after choosing providers. No AI key is needed for the current copilot.

```powershell
python -m scripts.setup_development
python -m scripts.seed_local
python -m scripts.seed_inventory
uvicorn app.main:app --reload
```

In a second terminal with the same environment:

```powershell
python -m app.workers.main
```

Swagger: http://127.0.0.1:8000/docs. Health: /health/live and /health/ready.
The placeholder database URLs do not connect until edited. Use separate application
and migration identities. Run `python -m scripts.grant_runtime YOUR_RUNTIME_ROLE`
with the migration identity after migration to enforce history permissions.

## Main API groups

- Public catalog, collections, search, content and stock availability.
- Guest/customer carts, login merge, checkout and payment retries.
- Guest-token order views, customer order listing and staff fulfillment actions.
- Sandbox callbacks, returns, refunds and separate approvals.
- Profiles, addresses, consent, support cases and erasure requests.
- Staff catalog/publication/pricing/promotions/inventory and audit/outbox controls.
- Grounded copilot conversations with ownership tokens.

Guest routes require X-Cart-Token or X-Order-Token. Staff routes require Auth0 Bearer
permissions. Never assign refund:request and refund:approve to the same role.
Checkout/refunds require Idempotency-Key; changed-body replay returns 409.

Sandbox callback body, authenticated with X-Sandbox-Secret:

```json
{
  "event_id": "unique-provider-event-id",
  "provider_reference": "sandbox_reference_from_checkout",
  "status": "captured",
  "amount_minor": 11800,
  "currency": "INR"
}
```

The amount must match checkout exactly. Status may also be failed. Browser redirects
never confirm orders. Late captures after stock expiry require reconciliation.

## Verification

```powershell
pytest -q
mypy app tests
python -m scripts.export_openapi .test-artifacts/openapi.json
```

Integration tests require a disposable migrated database named sf_test*:

```powershell
$env:TEST_DATABASE_URL="postgresql+asyncpg://sa_test:local-test-only@127.0.0.1:55432/sf_test"
pytest -q
```

Integration fixtures truncate that database. They are explicitly skipped without
TEST_DATABASE_URL. CI starts PostgreSQL, migrates, runs tests and publishes OpenAPI.
The separate frontend repository must regenerate/review its client independently.

## Deployment

Use separate API/worker deployments of the same image, isolated resources and managed
identity. Install .[azure] and set APPLICATIONINSIGHTS_CONNECTION_STRING for Azure
telemetry. App Service Key Vault references resolve into normal environment variables.
Set ENVIRONMENT=prod in production; sandbox payment execution is disabled there.

Release migrations before new API/worker code, backfill old captures and reconcile
legacy checkouts first. History migrations have guarded downgrade paths. See the
architecture review for rollout limits and deliberately deferred live integrations.

## Optional semantic search

Leave SEMANTIC_SEARCH_ENABLED=false for grounded keyword retrieval without AI keys.
To enable semantic retrieval, configure EMBEDDING_API_URL, EMBEDDING_API_KEY,
EMBEDDING_MODEL and EMBEDDING_DIMENSIONS, then run:

```powershell
python -m scripts.enable_semantic_search
python -m scripts.index_embeddings
```

Enable SEMANTIC_SEARCH_ENABLED after successful indexing. The endpoint contract is
POST {model,input}, returning data[0].embedding. Other provider formats require an
adapter. Azure PostgreSQL must allow the vector extension. Provisioning uses the
migration identity and adds a native vector column while preserving legacy JSONB.
Changing dimensions requires a reviewed reindex/migration; it is not automatic.

## Existing development databases

The development setup command requires PostgreSQL client tools (pg_dump), takes a
backup, migrates, applies runtime grants and backfills existing payment balances.
Migration 0008 also supports the older customer-only 0006 layout without a reset.
Use `python -m scripts.verify_configuration` for read-only checks and
`python -m scripts.verify_development_flows` for rolled-back sandbox checks.
See [the current verification report](docs/configuration-verification.md).
