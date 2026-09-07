from sqlalchemy.orm import Session

from app.services.label_schema import write_label_revision


def write_with_revision_guard(db: Session, task_id, sample_id: str, values, author_id, base_revision: int):
    return write_label_revision(db, task_id, sample_id, values, author_id, base_revision)
