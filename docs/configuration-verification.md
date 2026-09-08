# Development database setup and verification

**The database setup mismatch is fixed.** The configured development database is
now at migration 0008 and matches the current backend tables and columns.

## What was completed

- Created a database backup before migration.
- Applied migrations 0007 and 0008 without deleting existing tables or data.
- Added the 22 missing commerce tables and missing columns.
- Preserved the older customer/address columns and added compatibility triggers
  so both the legacy and current representations work.
- Applied restricted application-role grants and backfilled legacy payment balances.
- Verified every pre-existing table retained its original row count.

The initial 0006 marker came from an earlier customer-only migration, while this
checkout used 0006 for commerce. New reconciliation migration 0008 handles both
layouts; no backward stamping or destructive database reset was used.

## Verification results

| Check | Result |
| --- | --- |
| Application/migration database connections | Pass |
| Required tables and columns | All present |
| Alembic version | Database and code both 0008 |
| Application permissions | Pass, including immutable-history restrictions |
| API liveness/readiness | HTTP 200 / 200 |
| Nonexistent order lookup | HTTP 404, replacing the previous SQL error |
| Configured worker startup | Reservation and retention sweeps passed |
| Auth0 discovery/issuer/signing keys | Pass |
| Customer profile/address creation | Pass in rolled-back verification |
| Cart, checkout and identical-request replay | Pass in rolled-back verification |
| Sandbox callback and confirmed order view | Pass in rolled-back verification |
| Full suite on reconciled legacy schema | 35 tests passed |
| Type/lint checks | Pass |

The configured-database flow verification ran inside an outer transaction that was
rolled back. No verification customers, addresses, orders, stock or outbox events
were retained. API/worker smoke processes were stopped after verification.

## Remaining configuration/data

- The two existing active variants have no inventory balances yet. Enter actual
  stock using the inventory APIs before normal checkout. For disposable demo data
  only, `python -m scripts.seed_inventory` explicitly creates development fixtures.
- Payment provider remains sandbox, as requested. Live payment/shipping credentials
  and integrations are still deferred.
- Full Auth0 login/audience/role validation still requires a real issued access token;
  public identity discovery is not a complete login test. Business flow verification
  used an explicit temporary identity override, not a bypass in the application.
- Optional Azure storage/telemetry/embeddings remain unconfigured and were not live-tested.

## Repeatable commands

```powershell
python -m scripts.setup_development
python -m scripts.verify_configuration
python -m scripts.verify_development_flows
```

Setup is guarded to development, backs up before migrations, and never automatically
seeds stock. The configuration diagnostic is read-only. Flow verification uses the
sandbox provider and rolls back its test writes.

The backup and migration diagnostics are under the ignored local directory:
`.test-artifacts/database-setup-20260907T102105Z/`.
No .env secrets were printed or committed.
