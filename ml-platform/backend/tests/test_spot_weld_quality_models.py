import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base


class TestSpotWeldQualityModels(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine)()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_quality_tables_register_run_sample_rule_revision_and_snapshot(self):
        from app.models.spot_weld_quality import (
            SpotWeldLabelRevision,
            SpotWeldLabelSnapshot,
            SpotWeldQualityRun,
            SpotWeldQualitySample,
            SpotWeldQualityRuleSet,
        )

        self.assertEqual(SpotWeldQualityRun.__tablename__, "spot_weld_quality_runs")
        self.assertEqual(SpotWeldQualitySample.__tablename__, "spot_weld_quality_samples")
        self.assertEqual(SpotWeldQualityRuleSet.__tablename__, "spot_weld_quality_rule_sets")
        self.assertEqual(SpotWeldLabelRevision.__tablename__, "spot_weld_label_revisions")
        self.assertEqual(SpotWeldLabelSnapshot.__tablename__, "spot_weld_label_snapshots")

        tables = Base.metadata.tables
        self.assertTrue({
            "spot_weld_quality_runs",
            "spot_weld_quality_samples",
            "spot_weld_quality_rule_sets",
            "spot_weld_label_revisions",
            "spot_weld_label_snapshots",
        }.issubset(tables))
        sample_constraints = {
            constraint.name
            for constraint in tables["spot_weld_quality_samples"].constraints
        }
        self.assertIn("uq_spot_weld_quality_sample_run_row", sample_constraints)
        self.assertTrue({
            "ix_spot_weld_quality_samples_run_review",
            "ix_spot_weld_quality_samples_run_warning",
        }.issubset({
            index.name for index in tables["spot_weld_quality_samples"].indexes
        }))

    def test_project_owned_foreign_keys_cascade_with_quality_run(self):
        from app.models.spot_weld_quality import SpotWeldQualitySample  # noqa: F401

        sample_table = Base.metadata.tables["spot_weld_quality_samples"]
        foreign_keys = {
            tuple(constraint.column_keys): constraint.ondelete
            for constraint in sample_table.foreign_key_constraints
        }
        self.assertEqual(foreign_keys[("run_id",)], "CASCADE")


if __name__ == "__main__":
    unittest.main()
