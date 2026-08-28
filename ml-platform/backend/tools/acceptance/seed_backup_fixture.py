"""Seed deterministic business data for isolated backup acceptance."""

from __future__ import annotations

import json
import os

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.models import ModelLibrary, Project, User, Workflow


def main() -> None:
    database_url = os.environ["DATABASE_URL"]
    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        with Session(engine) as session:
            user = session.scalar(
                select(User).where(User.username == "backup-fixture-owner"),
            )
            if user is None:
                user = User(
                    username="backup-fixture-owner",
                    password_hash="fixture-not-loginable",
                    role="engineer",
                )
                session.add(user)
                session.flush()

            project = session.scalar(
                select(Project).where(Project.name == "Backup fixture project"),
            )
            if project is None:
                project = Project(
                    name="Backup fixture project",
                    description="isolated backup acceptance fixture",
                    owner_id=user.id,
                )
                session.add(project)
                session.flush()

            workflow = session.scalar(
                select(Workflow).where(Workflow.name == "Backup fixture workflow"),
            )
            if workflow is None:
                session.add(
                    Workflow(
                        project_id=project.id,
                        name="Backup fixture workflow",
                        created_by=user.id,
                    ),
                )

            model = session.scalar(
                select(ModelLibrary).where(ModelLibrary.name == "Backup fixture model"),
            )
            if model is None:
                session.add(
                    ModelLibrary(
                        name="Backup fixture model",
                        owner_id=user.id,
                        project_id=project.id,
                    ),
                )
            session.commit()
    finally:
        engine.dispose()

    print(json.dumps({"status": "passed", "fixture": "backup"}, sort_keys=True))


if __name__ == "__main__":
    main()
