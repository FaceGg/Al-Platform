"""Recipe versioning tests (AutoML Agent plan, Task A3.1).

Contract under test (spec v0.9 §四/§13.1): versioned recipe documents with
git-style rollback (a rollback issues a NEW current version carrying the old
content) and the delta check that decides reuse-vs-full-iteration for new
data.
"""

import os
import unittest
from uuid import uuid4

os.environ.setdefault("LLM_MASTER_KEY", __import__(
    "cryptography.fernet", fromlist=["Fernet"]
).Fernet.generate_key().decode("ascii"))

from app.database import Base, SessionLocal, engine  # noqa: E402
from app.services.agent.recipe import (  # noqa: E402
    RecipeVersionNotFound,
    create_recipe,
    delta_check,
    get_current_version,
    list_versions,
    rollback_recipe,
    update_recipe,
)

Base.metadata.create_all(bind=engine)

_RECIPE_BODY = {
    "domain": "tightening",
    "inputs": {"target_column": "DECIDE(判定结果)"},
    "analysis_digest": "扭矩域，偏差主导",
    "analysis_profile": {
        "row_count": 8000,
        "columns": [
            {"name": "ACTUAL_TORQUE", "dtype": "float64"},
            {"name": "DECIDE(判定结果)", "dtype": "int64"},
        ],
    },
    "feature_script": "def transform(df):\n    return df",
    "automl_config": {"families": ["lightgbm"], "trials": 30},
    "acceptance_gates": {"recall_minority": 0.90},
}


class TestRecipeVersioning(unittest.TestCase):
    def setUp(self):
        with SessionLocal() as db:
            recipe = create_recipe(
                db,
                project_id=None,
                name="tightening-v1-" + uuid4().hex[:6],
                content=dict(_RECIPE_BODY),
                change_note="首轮固化",
            )
            self.recipe_id = recipe.id

    def test_create_makes_v1_current(self):
        with SessionLocal() as db:
            version = get_current_version(db, self.recipe_id)
            versions = list_versions(db, self.recipe_id)
        self.assertEqual(version.version, 1)
        self.assertEqual(version.status, "current")
        self.assertEqual(version.content_json["domain"], "tightening")
        self.assertEqual(len(versions), 1)

    def test_update_supersedes_old_version(self):
        with SessionLocal() as db:
            update_recipe(
                db,
                self.recipe_id,
                content=dict(_RECIPE_BODY, analysis_digest="更新摘要"),
                change_note="v2 修订",
            )
            current = get_current_version(db, self.recipe_id)
            versions = list_versions(db, self.recipe_id)
        self.assertEqual(current.version, 2)
        self.assertEqual(current.content_json["analysis_digest"], "更新摘要")
        statuses = {v.version: v.status for v in versions}
        self.assertEqual(statuses[1], "superseded")
        self.assertEqual(statuses[2], "current")

    def test_rollback_issues_new_version_with_old_content(self):
        with SessionLocal() as db:
            update_recipe(
                db,
                self.recipe_id,
                content=dict(_RECIPE_BODY, acceptance_gates={"recall_minority": 0.5}),
                change_note="v2 误放宽",
            )
            rolled = rollback_recipe(db, self.recipe_id, to_version=1, change_note="回滚")
            current = get_current_version(db, self.recipe_id)
            versions = list_versions(db, self.recipe_id)
        self.assertEqual(rolled.version, 3)
        self.assertEqual(current.version, 3)
        self.assertEqual(
            current.content_json["acceptance_gates"], {"recall_minority": 0.90}
        )
        statuses = {v.version: v.status for v in versions}
        self.assertEqual(statuses[2], "superseded")
        self.assertEqual(statuses[3], "current")

    def test_rollback_to_missing_version_raises(self):
        with SessionLocal() as db:
            with self.assertRaises(RecipeVersionNotFound):
                rollback_recipe(db, self.recipe_id, to_version=99)

    def test_delta_check_small_vs_large(self):
        same_profile = {
            "row_count": 10000,
            "columns": [
                {"name": "ACTUAL_TORQUE", "dtype": "float64"},
                {"name": "DECIDE(判定结果)", "dtype": "int64"},
            ],
        }
        with SessionLocal() as db:
            result = delta_check(db, self.recipe_id, same_profile)
        self.assertTrue(result["small"])
        self.assertEqual(result["reasons"], [])

    def test_delta_check_flags_drift(self):
        drifted = {
            "row_count": 120,
            "columns": [
                {"name": "ACTUAL_TORQUE", "dtype": "object"},
                {"name": "DECIDE(判定结果)", "dtype": "int64"},
                {"name": "NEW_COLUMN", "dtype": "float64"},
            ],
        }
        with SessionLocal() as db:
            result = delta_check(db, self.recipe_id, drifted)
        self.assertFalse(result["small"])
        self.assertTrue(result["reasons"])
