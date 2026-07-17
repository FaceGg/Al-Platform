# Artifact Migration

Preview legacy local artifacts with `python tools/migrate_artifacts.py --dry-run`. Execute with `python tools/migrate_artifacts.py`, optionally adding `--project-id <uuid>`.

The command uploads each legacy file, validates size and SHA-256, updates `storage_uri` in its own transaction, preserves `storage_path`, and can be safely repeated.

Stop artifact writes for the final cutover and retain the local files until all object URIs have been verified. On rollback, switch `ARTIFACT_STORAGE_BACKEND` back to `local`; preserved `storage_path` values remain the compatibility source. Failed uploads are not committed, and failed database commits trigger object deletion compensation.
