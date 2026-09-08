# Backend verification against Architecture v2

Source: `Special_Affair_Architecture_v2 (2).docx`, supplied by the project owner.
The document is a proposed design, not authorization to deploy resources, send
customer messages, choose live providers, or modify the frontend repository.

## Assessment

This repository contains a FastAPI backend and worker only. No frontend has been
added. The modular monolith and PostgreSQL design fit the proposed boundaries.
The original branch was an early sandbox, not a complete architecture implementation.

Original checkout did not reserve stock, reused cached cart prices, rejected replay
after cart conversion, and confirmed callbacks without checking amounts or recording
an inbox event. The worker only executed `SELECT 1`; several domain folders were empty.

## Implemented

| Area | Behavior |
| --- | --- |
| Configuration | Ignored `.env`, documented example, generated local signing secrets, production secret validation. |
| Catalog | Staff product/variant creation, version-checked publication, effective price books, baseline non-stacking percentage promotions, Azure media metadata registration. |
| Inventory | Locations, stock ledger, row-locked reservations, TTL sweeper, release/dispatch consumption, availability. Unconfigured stock is unavailable. |
| Checkout | Cart lock, current sellability/prices, integer half-up line tax/discounts, immutable snapshots, cached response replay, committed preparation before external provider work. |
| Payments | Provider protocol and deterministic sandbox, retries, event deduplication, exact amount/currency checks, transactional confirmation, late-event reconciliation. |
| Customers | Auth0 subject-linked profiles/addresses, consent history, saved carts, owned order listing, maximum-quantity guest merge with explicit stock adjustments. |
| Orders | Token-authorized guest access, customer listing, status history, allocation/cancellation, partial/full dispatch quantity checks and delivery. |
| Returns/refunds | Delivered-order eligibility/window, purchased-quantity limits, inspection transitions, capture-bounded refunds, pending-refund accounting, separate maker/checker approval, sandbox settlement. |
| Worker | PostgreSQL polling, SKIP LOCKED, per-aggregate ordering, leases, retries, poison-event quarantine, dead-event replay, stock/retention sweeps. |
| Governance | Permission-gated staff APIs, audit evidence, append-only database triggers, runtime grants, support cases, approved local profile erasure. |
| Reliability | Split health, bounded local abuse guard, private cache controls, redacted logs, correlation propagation, optional Azure telemetry initialization. |
| Copilot | Grounded read-only workflow; session ownership tokens; opt-in embedding endpoint, indexing and native pgvector retrieval. |
| Delivery | Additive migrations, OpenAPI export, PostgreSQL CI, integration regressions. |

## Decisions and compatibility

- Payment/shipping providers are deferred at the owner's request. Sandbox execution
  is disabled in production. No actual charges, customer messages or carrier bookings occur.
- COD preserves the existing repository behavior: confirmation commits stock without
  inventing an online captured payment. COD refunds need an offline receipt process.
- Sandbox auto-captures. Authorize-at-checkout/capture-at-dispatch is still a business
  decision; expanded database states do not imply an implemented live capture adapter.
- Tax percentage, shipping fee, 15-minute holds, 30-day returns and refund threshold
  are provisional development policies. Production tax classification and regional
  rules need approval. This is not a legal/tax-policy validation.
- Idempotency scopes use `checkout:`/`refund:` prefixes in the existing primary key,
  avoiding destructive replacement. Expiry is recorded but keys remain tombstones
  and are not automatically reusable. Legacy 0005 keys need a rollout decision.
- Existing catalog display uses legacy variant prices. Checkout resolves effective
  price books and promotions; frontend must surface authoritative total changes.
- Sandbox webhooks additionally require `event_id`, `amount_minor`, `currency`.
  `X-Sandbox-Secret` is development authentication, not a live signature format.
- Existing routes remain and `GET /orders/{id}` is added. Continuing copilot sessions
  requires the returned `session_token`; old unowned sessions cannot be resumed.
- Checkout now requires real stocked inventory. Development seeding must be explicit;
  migrations never fabricate stock for existing products.
- History tables have append-only triggers. Commerce commands use row/advisory locks;
  optimistic versions are enforced for publication, not yet uniformly on every entity.
- Worker order events currently create durable local audit receipts, not notification
  delivery. Unknown/reconciliation events are quarantined for operator action.
- Split shipment quantities are supported; per-shipment financial capture is deferred.
- Local erasure removes profile/addresses/support bodies and pseudonymizes order links;
  commercial/consent/audit evidence is retained. Auth0, backups and provider copies
  require external approved steps. The endpoint does not claim global erasure.

## Remaining production requirements

1. Choose payment/carrier providers and implement their signature/settlement/tracking
   vocabulary, real reconciliation queries and hosted collection. Decide capture
   timing, COD settlement and guest-order claiming.
2. Provision isolated Azure API/worker/database resources, Auth0 roles, managed identity,
   Key Vault, storage, TLS and backups. Verify non-HTTP worker hosting on the selected
   plan. No cloud resources were deployed or production credentials used.
3. Connect consent-aware notification adapters to explicit outbox delivery events.
4. Configure Application Insights dashboards/alerts. Conversion baselines, p95 lag,
   webhook failures and provider drift need operational configuration and real data;
   initializing telemetry alone does not implement all four monitored indicators.
5. Select the embedding provider/model and configure the optional embedding endpoint.
   Run enable_semantic_search with migration identity and index_embeddings with approved
   catalog data, then enable SEMANTIC_SEARCH_ENABLED. Live provider calls remain untested.
   Keyword retrieval remains the default and answer generation is deterministic.
6. Approve financial/consent retention periods and configure resource-level retention.
   Local sweeps preserve unresolved payment evidence and never delete financial history.
7. Configure protected environments and deployment OIDC. Enforce generated-client diffs
   in the separate frontend repository; backend CI only exports its contract.
8. Finalize coupon limits, merchandising/admin coverage, distributed ingress limits
   and workforce step-up authentication. Promotions are intentionally a baseline.

These remain release requirements; they are not represented as completed integrations.

## Migration and rollback

0006 adds domains, retains legacy columns, widens state constraints and installs
history triggers with a five-second lock acquisition limit. 0007 adds nullable
copilot ownership hashes. Before an existing deployment changes:

1. Back up and rehearse on a staging copy.
2. Release migrations before the new application.
3. Run `python -m scripts.backfill_payment_balances` in batches; reconcile legacy
   open checkouts without reservations and load verified stock.
4. Apply `python -m scripts.grant_runtime YOUR_RUNTIME_ROLE` as the migration identity.
5. Deploy API/worker together and monitor health/dead events.

Downgrades deliberately reject deletion of history/ownership protection. Use forward
corrective migrations. Old code cannot operate every new order state, so review
rollback targets against live data before restoring traffic. Production rolling
deployment has not been rehearsed here.

## Verification and references

Tests use disposable PostgreSQL 16 and cover oversell races, replays, expiry,
callbacks, refund bounds, split shipments, cart merge, immutable audit and quarantine.
Cloud/Auth0/live-provider credentials were not supplied and were not tested.

Local verification result: **34 tests passed**, including native pgvector retrieval
with deterministic test embeddings; mypy passed across 96 source files; configured
lint checks passed. A real Uvicorn process returned 200 for liveness, readiness and
OpenAPI. The worker completed reservation/retention sweeps. The schema exports 62
route paths. Smoke processes were stopped after verification. Live embedding-provider
responses and Azure telemetry export were not exercised.

- [PostgreSQL locks](https://www.postgresql.org/docs/16/explicit-locking.html)
- [SQLAlchemy async sessions](https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html)
- [Azure Key Vault settings](https://learn.microsoft.com/en-us/azure/app-service/app-service-key-vault-references)
- [Azure telemetry initialization](https://learn.microsoft.com/en-us/troubleshoot/azure/azure-monitor/app-insights/telemetry/opentelemetry-troubleshooting-python)

Native vector provisioning follows [pgvector documentation](https://github.com/pgvector/pgvector).

## Development database reconciliation update

Migration 0008 now handles the previously discovered customer-only 0006 schema,
adds missing commerce objects, and retains/synchronizes legacy customer/address
columns. The configured development database has been backed up and upgraded to
0008 with original row counts preserved. The reconciled legacy-schema suite passed
35 tests, and configured-database checkout/callback checks passed with all test
writes rolled back. See [current verification](configuration-verification.md).
