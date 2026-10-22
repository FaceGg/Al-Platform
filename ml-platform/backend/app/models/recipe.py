"""Pipeline Recipe models (AutoML Agent plan, Task A3.1).

Spec v0.9 §四/§13.1: a recipe is the sedimented agent product; versions are
append-only with a single ``current`` pointer, and a rollback issues a new
version carrying the old content (nothing is ever mutated in place).
"""

import uuid

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID

from app.database import Base


class PipelineRecipe(Base):
    __tablename__ = "pipeline_recipes"
    __table_args__ = (
        UniqueConstraint("project_id", "name", name="ux_pipeline_recipes_scope_name"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="SET NULL"),
        nullable=True,
    )
    name = Column(String(64), nullable=False)
    domain = Column(String(64), nullable=True)
    target_column = Column(String(256), nullable=True)
    current_version = Column(Integer, nullable=False, default=1)
    created_by = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )


class PipelineRecipeVersion(Base):
    __tablename__ = "pipeline_recipe_versions"
    __table_args__ = (
        CheckConstraint(
            "status IN ('current','superseded')",
            name="ck_recipe_versions_status",
        ),
        UniqueConstraint("recipe_id", "version", name="ux_recipe_versions_number"),
        Index("ix_recipe_versions_recipe", "recipe_id", "version"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    recipe_id = Column(
        UUID(as_uuid=True),
        ForeignKey("pipeline_recipes.id", ondelete="CASCADE"),
        nullable=False,
    )
    version = Column(Integer, nullable=False)
    status = Column(String(16), nullable=False, default="current")
    content_json = Column(JSON, nullable=False, default=dict)
    change_note = Column(String(500), nullable=True)
    llm_profile_id = Column(
        UUID(as_uuid=True),
        ForeignKey("llm_profiles.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_by = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at = Column(DateTime, nullable=False, server_default=func.now())
