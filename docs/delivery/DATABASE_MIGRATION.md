# Database Migration

1. Back up the source database.
2. Run `alembic upgrade head` against the production PostgreSQL database.
3. For SQLite migration, run `python tools/migrate_database.py --source-url <sqlite> --target-url <postgresql>`.
4. Verify `alembic current` reports the expected head and rerun the migration command to confirm idempotency.

Production startup refuses an outdated Alembic revision.

Use an empty target database or an explicitly reviewed Alembic revision. The copy command preserves UUID, JSON, datetime, null values and cyclic nullable foreign keys. Existing primary keys with different content are reported and never overwritten. Back up both databases before cutover, stop writes during the final copy, and compare every per-table source/target count before switching the API.

Rollback keeps the PostgreSQL database intact, restores the previous SQLite configuration, and reopens writes only after application health checks pass. Never run the baseline revision over an unversioned SQLite database that already contains business tables.
