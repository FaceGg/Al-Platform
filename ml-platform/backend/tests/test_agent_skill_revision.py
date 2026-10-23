"""Bounded RSI tests (AutoML Agent plan, Task A4.1).

Contract under test (spec v0.9 §10.3): debounce (one unresolved proposal per
skill), tightening-only gate changes, risk classification, bounded regression
sampling (≤10, domain representatives + newest), S3 never re-runs, any
degradation rejects and annotates the basis lessons, low-risk auto-activation,
human approval for medium/high, and versioned one-click rollback.
"""

import os
import unittest
from uuid import uuid4

os.environ.setdefault("LLM_MASTER_KEY", __import__(
    "cryptography.fernet", fromlist=["Fernet"]
).Fernet.generate_key().decode("ascii"))

from app.database import Base, SessionLocal, engine  # noqa: E402
from app.models.experience_entry import ExperienceEntry  # noqa: E402
from app.models.recipe import PipelineRecipe, PipelineRecipeVersion  # noqa: E402
from app.services.agent.recipe import create_recipe  # noqa: E402
from app.services.agent.skill_revision import (  # noqa: E402
    REGRESSION_STAGES,
    RevisionDebounced,
    RevisionNotPermitted,
    RevisionStateError,
    classify_risk,
    decide_revision,
    propose_revision,
    rollback_skill,
    run_regression,
    select_representative_recipes,
)

Base.metadata.create_all(bind=engine)

_CURRENT_GATES = {"recall_minority": 0.90}


class TestSkillRevision(unittest.TestCase):
    def setUp(self):
        with SessionLocal() as db:
            from app.models.skill_revision import SkillRevision

            db.query(SkillRevision).delete()
            db.query(ExperienceEntry).delete()
            db.commit()

    # ------------------------------------------------------------- proposal
    def test_risk_classification(self):
        self.assertEqual(classify_risk(["prompts"]), "low")
        self.assertEqual(classify_risk(["defaults"]), "medium")
        self.assertEqual(classify_risk(["prompts", "gates"]), "high")
        self.assertEqual(classify_risk(["unknown"]), "medium")

    def test_propose_and_debounce(self):
        with SessionLocal() as db:
            first = propose_revision(
                db,
                skill_name="automl-agent",
                base_version=1,
                current_gates=_CURRENT_GATES,
                proposal={"diff": "- 更正错别字", "touched": ["prompts"]},
            )
            with self.assertRaises(RevisionDebounced):
                propose_revision(
                    db,
                    skill_name="automl-agent",
                    base_version=1,
                    current_gates=_CURRENT_GATES,
                    proposal={"diff": "x", "touched": ["prompts"]},
                )
        self.assertEqual(first.status, "proposed")
        self.assertEqual(first.risk_level, "low")

    def test_gate_relaxation_rejected_at_proposal(self):
        with SessionLocal() as db:
            with self.assertRaises(RevisionNotPermitted):
                propose_revision(
                    db,
                    skill_name="automl-agent",
                    base_version=1,
                    current_gates=_CURRENT_GATES,
                    proposal={
                        "diff": "降低召回门槛",
                        "touched": ["gates"],
                        "gate_changes": {"recall_minority": 0.80},
                    },
                )

    def test_gate_tightening_accepted_and_high_risk(self):
        with SessionLocal() as db:
            revision = propose_revision(
                db,
                skill_name="automl-agent",
                base_version=1,
                current_gates=_CURRENT_GATES,
                proposal={
                    "diff": "召回门槛收紧到 0.95",
                    "touched": [],
                    "gate_changes": {"recall_minority": 0.95},
                },
            )
            risk = revision.risk_level
            changes = dict(revision.proposal_json["gate_changes"])
        self.assertEqual(risk, "high")
        self.assertEqual(changes["recall_minority"], 0.95)

    # ------------------------------------------------------------ regression
    def test_sampling_caps_at_ten_domain_representatives(self):
        created = []
        with SessionLocal() as db:
            for index in range(12):
                recipe = create_recipe(
                    db,
                    project_id=None,
                    name="rsi-sample-%s" % uuid4().hex[:6],
                    content={
                        "domain": "tightening" if index % 2 == 0 else "welding",
                        "baseline_metrics": {"recall_minority": 0.9},
                    },
                )
                created.append(recipe.id)
            versions = (
                db.query(PipelineRecipeVersion)
                .join(PipelineRecipe, PipelineRecipe.id == PipelineRecipeVersion.recipe_id)
                .filter(PipelineRecipeVersion.status == "current")
                .all()
            )
            sample = select_representative_recipes(versions, limit=10)
        self.assertEqual(len(sample), 10)
        domains = {(v.content_json or {}).get("domain") for v in sample}
        self.assertEqual(domains, {"tightening", "welding"})

    def test_regression_runs_only_s1_s2_s4_and_never_s3(self):
        seen_stages = []

        def regression_fn(content, stages):
            seen_stages.append(list(stages))
            return {"metrics": dict(content.get("baseline_metrics") or {})}

        with SessionLocal() as db:
            revision = propose_revision(
                db,
                skill_name="automl-agent",
                base_version=1,
                current_gates=_CURRENT_GATES,
                proposal={"diff": "d", "touched": ["prompts"]},
            )
            revision_id = revision.id
            create_recipe(
                db,
                project_id=None,
                name="rsi-reg-%s" % uuid4().hex[:6],
                content={
                    "domain": "tightening",
                    "baseline_metrics": {"recall_minority": 0.92},
                },
            )
            result = run_regression(db, revision_id=revision_id, regression_fn=regression_fn)
        self.assertEqual(result.status, "auto_activated")  # low risk auto path
        self.assertEqual(result.new_version, 1)
        self.assertTrue(all(stages == list(REGRESSION_STAGES) for stages in seen_stages))
        self.assertNotIn("s3", seen_stages[0])

    def test_any_degradation_rejects_and_annotates_lesson(self):
        with SessionLocal() as db:
            entry = ExperienceEntry(
                domain="tightening",
                situation="s",
                lesson="索引列默认剔除",
                action="a",
                status="active",
                confidence=0.9,
                origin="distilled",
                evidence_json={"source_tasks": ["t1"]},
            )
            db.add(entry)
            db.commit()
            entry_id = str(entry.id)
            revision = propose_revision(
                db,
                skill_name="automl-agent",
                base_version=1,
                current_gates=_CURRENT_GATES,
                proposal={"diff": "d", "touched": ["prompts"]},
                basis_entries=[entry_id],
            )
            revision_id = revision.id
            create_recipe(
                db,
                project_id=None,
                name="rsi-deg-%s" % uuid4().hex[:6],
                content={
                    "domain": "tightening",
                    "baseline_metrics": {"recall_minority": 0.92},
                },
            )

            def degrading(content, stages):
                return {"metrics": {"recall_minority": 0.70}}

            result = run_regression(db, revision_id=revision_id, regression_fn=degrading)
        self.assertEqual(result.status, "regression_failed")
        self.assertFalse(result.regression_passed)
        with SessionLocal() as db:
            refreshed = db.get(ExperienceEntry, entry.uuid if hasattr(entry, "uuid") else _to_uuid(entry_id))
            self.assertIn("不可泛化", refreshed.human_note or "")

    # -------------------------------------------------------------- approval
    def test_medium_risk_requires_human_decision(self):
        with SessionLocal() as db:
            revision = propose_revision(
                db,
                skill_name="automl-agent",
                base_version=1,
                current_gates=_CURRENT_GATES,
                proposal={"diff": "默认剔除程序号列", "touched": ["defaults"]},
            )
            revision_id = revision.id
            create_recipe(
                db,
                project_id=None,
                name="rsi-med-%s" % uuid4().hex[:6],
                content={
                    "domain": "tightening",
                    "baseline_metrics": {"recall_minority": 0.92},
                },
            )
            staged = run_regression(
                db, revision_id=revision_id,
                regression_fn=lambda content, stages: {
                    "metrics": dict(content.get("baseline_metrics") or {})
                },
            )
            self.assertEqual(staged.status, "pending_approval")
            with self.assertRaises(RevisionStateError):
                run_regression(db, revision_id=revision_id, regression_fn=None)
            decided = decide_revision(db, revision_id=revision_id, approve=True, actor_id=None)
        self.assertEqual(decided.status, "activated")
        self.assertEqual(decided.new_version, 1)

    def test_rejection_records_decision(self):
        with SessionLocal() as db:
            revision = propose_revision(
                db,
                skill_name="automl-agent",
                base_version=1,
                current_gates=_CURRENT_GATES,
                proposal={"diff": "d", "touched": ["defaults"]},
            )
            revision_id = revision.id
            create_recipe(
                db,
                project_id=None,
                name="rsi-rej-%s" % uuid4().hex[:6],
                content={
                    "domain": "tightening",
                    "baseline_metrics": {"recall_minority": 0.92},
                },
            )
            run_regression(
                db, revision_id=revision_id,
                regression_fn=lambda content, stages: {
                    "metrics": dict(content.get("baseline_metrics") or {})
                },
            )
            rejected = decide_revision(db, revision_id=revision_id, approve=False, actor_id=None)
        self.assertEqual(rejected.status, "rejected")

    def test_rollback_marks_version_and_counter_advances(self):
        with SessionLocal() as db:
            revision = propose_revision(
                db,
                skill_name="automl-agent",
                base_version=1,
                current_gates=_CURRENT_GATES,
                proposal={"diff": "d", "touched": ["prompts"]},
            )
            first_id = revision.id
            create_recipe(
                db,
                project_id=None,
                name="rsi-roll-%s" % uuid4().hex[:6],
                content={
                    "domain": "tightening",
                    "baseline_metrics": {"recall_minority": 0.92},
                },
            )
            activated = run_regression(
                db, revision_id=first_id,
                regression_fn=lambda content, stages: {
                    "metrics": dict(content.get("baseline_metrics") or {})
                },
            )
            self.assertEqual(activated.new_version, 1)
            rolled = rollback_skill(
                db, skill_name="automl-agent", to_version=1, actor_id=None
            )
            # After rollback the counter keeps moving forward, never reuses 1.
            second = propose_revision(
                db,
                skill_name="automl-agent",
                base_version=1,
                current_gates=_CURRENT_GATES,
                proposal={"diff": "d2", "touched": ["prompts"]},
            )
            second_id = second.id
            reactivated = run_regression(
                db, revision_id=second_id,
                regression_fn=lambda content, stages: {
                    "metrics": dict(content.get("baseline_metrics") or {})
                },
            )
            rolled_status = rolled.status
            reactivated_version = reactivated.new_version
        self.assertEqual(rolled_status, "rolled_back")
        self.assertEqual(reactivated_version, 2)


def _to_uuid(value):
    import uuid as uuid_module

    return uuid_module.UUID(str(value))
