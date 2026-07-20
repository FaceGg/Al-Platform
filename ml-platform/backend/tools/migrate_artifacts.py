"""CLI wrapper for migrating legacy Artifact files."""

import argparse
import json
import sys
from uuid import UUID

from app.config import settings
from app.database import SessionLocal
from app.services.artifact_migration import migrate_artifacts
from app.storage.factory import create_artifact_storage


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-id")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    project_id = UUID(args.project_id) if args.project_id else None
    with SessionLocal() as db:
        result = migrate_artifacts(
            db,
            create_artifact_storage(settings),
            project_id=project_id,
            dry_run=args.dry_run,
        )
    print(json.dumps(result.__dict__, sort_keys=True))
    return 0 if result.failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
