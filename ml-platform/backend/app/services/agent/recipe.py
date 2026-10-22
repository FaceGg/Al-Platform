"""Recipe versioning service (spec v0.9 §四/§13.1): append-only versions with
a single current pointer, git-style rollback (a rollback issues a NEW version
with the old content), and the delta check for new-data reuse.
"""

from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from app.models.recipe import PipelineRecipe, PipelineRecipeVersion


class RecipeNotFound(LookupError):
    pass


class RecipeVersionNotFound(LookupError):
    pass


def create_recipe(
    db: Session,
    *,
    project_id: uuid.UUID | None,
    name: str,
    content: dict,
    change_note: str | None = None,
    domain: str | None = None,
    target_column: str | None = None,
    llm_profile_id: uuid.UUID | None = None,
    created_by: uuid.UUID | None = None,
) -> PipelineRecipe:
    recipe = PipelineRecipe(
        project_id=project_id,
        name=name,
        domain=domain or content.get("domain"),
        target_column=target_column
        or (content.get("inputs") or {}).get("target_column"),
        current_version=1,
        created_by=created_by,
    )
    db.add(recipe)
    db.flush()
    version = PipelineRecipeVersion(
        recipe_id=recipe.id,
        version=1,
        status="current",
        content_json=content,
        change_note=change_note,
        llm_profile_id=llm_profile_id,
        created_by=created_by,
    )
    db.add(version)
    db.commit()
    return recipe


def _get_recipe(db: Session, recipe_id: uuid.UUID) -> PipelineRecipe:
    recipe = db.get(PipelineRecipe, recipe_id)
    if recipe is None:
        raise RecipeNotFound(str(recipe_id))
    return recipe


def _issue_version(
    db: Session,
    recipe: PipelineRecipe,
    *,
    version_number: int,
    content: dict,
    change_note: str | None,
    llm_profile_id: uuid.UUID | None,
    created_by: uuid.UUID | None,
) -> PipelineRecipeVersion:
    db.query(PipelineRecipeVersion).filter(
        PipelineRecipeVersion.recipe_id == recipe.id,
        PipelineRecipeVersion.status == "current",
    ).update({PipelineRecipeVersion.status: "superseded"}, synchronize_session=False)
    version = PipelineRecipeVersion(
        recipe_id=recipe.id,
        version=version_number,
        status="current",
        content_json=content,
        change_note=change_note,
        llm_profile_id=llm_profile_id,
        created_by=created_by,
    )
    db.add(version)
    recipe.current_version = version_number
    return version


def update_recipe(
    db: Session,
    recipe_id: uuid.UUID,
    *,
    content: dict,
    change_note: str | None = None,
    llm_profile_id: uuid.UUID | None = None,
    created_by: uuid.UUID | None = None,
) -> PipelineRecipeVersion:
    recipe = _get_recipe(db, recipe_id)
    version = _issue_version(
        db,
        recipe,
        version_number=recipe.current_version + 1,
        content=content,
        change_note=change_note,
        llm_profile_id=llm_profile_id,
        created_by=created_by,
    )
    db.commit()
    return version


def rollback_recipe(
    db: Session,
    recipe_id: uuid.UUID,
    *,
    to_version: int,
    change_note: str | None = None,
    created_by: uuid.UUID | None = None,
) -> PipelineRecipeVersion:
    """Git-style: the rollback issues a NEW current version with old content."""
    recipe = _get_recipe(db, recipe_id)
    source = (
        db.query(PipelineRecipeVersion)
        .filter(
            PipelineRecipeVersion.recipe_id == recipe.id,
            PipelineRecipeVersion.version == to_version,
        )
        .first()
    )
    if source is None:
        raise RecipeVersionNotFound(f"version {to_version} not found")
    version = _issue_version(
        db,
        recipe,
        version_number=recipe.current_version + 1,
        content=source.content_json,
        change_note=change_note or f"rollback to v{to_version}",
        llm_profile_id=source.llm_profile_id,
        created_by=created_by,
    )
    db.commit()
    return version


def get_current_version(db: Session, recipe_id: uuid.UUID) -> PipelineRecipeVersion:
    version = (
        db.query(PipelineRecipeVersion)
        .filter(
            PipelineRecipeVersion.recipe_id == recipe_id,
            PipelineRecipeVersion.status == "current",
        )
        .first()
    )
    if version is None:
        raise RecipeVersionNotFound(f"no current version for {recipe_id}")
    return version


def list_versions(db: Session, recipe_id: uuid.UUID) -> list[PipelineRecipeVersion]:
    return (
        db.query(PipelineRecipeVersion)
        .filter(PipelineRecipeVersion.recipe_id == recipe_id)
        .order_by(PipelineRecipeVersion.version.desc())
        .all()
    )


def delta_check(
    db: Session, recipe_id: uuid.UUID, new_profile: dict
) -> dict:
    """Decide reuse-vs-full-iteration for new data against the recipe digest.

    Small delta (spec §四): column set overlap ≥0.9, row count within [0.5, 2]
    of the recorded row count, and no dtype drift on shared columns.
    """
    current = get_current_version(db, recipe_id)
    digest_columns = {
        column["name"]: column.get("dtype")
        for column in (current.content_json.get("analysis_profile") or {}).get(
            "columns", []
        )
    } or _columns_from_digest(current.content_json)
    new_columns = {
        column["name"]: column.get("dtype")
        for column in new_profile.get("columns", [])
    }

    reasons: list[str] = []
    if digest_columns:
        shared = set(digest_columns) & set(new_columns)
        union = set(digest_columns) | set(new_columns)
        overlap = len(shared) / len(union) if union else 0.0
        if overlap < 0.9:
            reasons.append(f"column_overlap_low: {overlap:.2f} < 0.90")
        drifted = sorted(
            name
            for name in shared
            if digest_columns[name] and new_columns[name]
            and digest_columns[name] != new_columns[name]
        )
        if drifted:
            reasons.append(f"dtype_drift: {drifted[:5]}")
    else:
        reasons.append("analysis_digest_columns_missing")

    recorded_rows = (current.content_json.get("analysis_profile") or {}).get("row_count")
    new_rows = new_profile.get("row_count")
    if recorded_rows and new_rows:
        ratio = new_rows / max(recorded_rows, 1)
        if not 0.5 <= ratio <= 2.0:
            reasons.append(f"row_count_ratio_out_of_band: {ratio:.2f}")

    return {"small": not reasons, "reasons": reasons}


def _columns_from_digest(content: dict) -> dict:
    """Fallback: minimal columns digest embedded directly in the recipe."""
    digest = content.get("analysis_digest_columns")
    if isinstance(digest, dict):
        return digest
    return {}
