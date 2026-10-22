"""Recipe-gated retrain swap tests (AutoML Agent plan, Task A3.2b).

Contract under test (spec v0.9 §12.3): a bound recipe's acceptance_gates veto
the swap candidate — no registration, no approval, no deployment rotation —
while the un-bound path keeps its existing behavior.
"""

import os
import unittest
from unittest import mock
from uuid import uuid4

os.environ.setdefault("LLM_MASTER_KEY", __import__(
    "cryptography.fernet", fromlist=["Fernet"]
).Fernet.generate_key().decode("ascii"))

from app.database import Base, SessionLocal, engine  # noqa: E402
from app.services.agent.recipe import create_recipe  # noqa: E402
from app.services.agent.hard_gates import evaluate_hard_gates  # noqa: E402

Base.metadata.create_all(bind=engine)


class TestGateEvaluationOnCandidates(unittest.TestCase):
    """The veto predicate complete_retrain_swap applies before registering."""

    def test_candidate_below_recipe_gate_is_vetoed(self):
        report = evaluate_hard_gates(
            {"recall_minority": 0.71, "f1": 0.88},
            gates={"recall_minority": 0.90},
        )
        self.assertFalse(report.passed)

    def test_candidate_meeting_recipe_gate_passes(self):
        report = evaluate_hard_gates(
            {"recall_minority": 0.94},
            gates={"recall_minority": 0.90},
        )
        self.assertTrue(report.passed)

    def test_candidate_missing_metric_is_vetoed(self):
        report = evaluate_hard_gates(
            {"f1": 0.9},
            gates={"recall_minority": 0.90},
        )
        self.assertFalse(report.passed)
        self.assertTrue(any("metric_missing" in item for item in report.failures))


class TestCompleteRetrainSwapRecipePath(unittest.TestCase):
    def test_recipe_gate_veto_skips_registration_and_swap(self):
        """With a bound recipe whose gates fail, the swap returns None and the
        registry service is never invoked (no registration/approval)."""
        from app.services import closed_loop_actions

        job = mock.Mock()
        job.id = uuid4()
        job.status = "completed"
        candidates = [
            {
                "candidate_id": "cand-1",
                "name": "lightgbm",
                "metrics": {"recall_minority": 0.71},
                "model_artifact_id": str(uuid4()),
            }
        ]
        with SessionLocal() as db:
            recipe = create_recipe(
                db,
                project_id=None,
                name="gated-recipe-" + uuid4().hex[:6],
                content={
                    "domain": "tightening",
                    "acceptance_gates": {"recall_minority": 0.90},
                },
            )
            recipe_id = recipe.id
            with mock.patch.object(
                closed_loop_actions.ModelRegistryService,
                "list_registerable_candidates",
                return_value=candidates,
            ), mock.patch.object(
                closed_loop_actions.ModelRegistryService,
                "register_automl_candidate",
            ) as register:
                result = closed_loop_actions.complete_retrain_swap(
                    db,
                    deployment_id=str(uuid4()),
                    job=job,
                    actor_id=str(uuid4()),
                    model_name="gated-model",
                    recipe_id=str(recipe_id),
                )
        self.assertIsNone(result)
        register.assert_not_called()

    def test_without_recipe_registration_proceeds(self):
        """No bound recipe: existing behavior — registration is attempted."""
        from app.services import closed_loop_actions

        job = mock.Mock()
        job.id = uuid4()
        job.status = "completed"
        candidates = [
            {
                "candidate_id": "cand-1",
                "name": "lightgbm",
                "metrics": {"recall_minority": 0.71},
                "model_artifact_id": str(uuid4()),
            }
        ]
        with SessionLocal() as db:
            with mock.patch.object(
                closed_loop_actions.ModelRegistryService,
                "list_registerable_candidates",
                return_value=candidates,
            ), mock.patch.object(
                closed_loop_actions.ModelRegistryService,
                "register_automl_candidate",
                side_effect=AssertionError("must not reach registration in this stub"),
            ) as register:
                # register_automl_candidate raising here proves the call was
                # attempted; the swap path beyond it is covered by demo_loop
                # regression tests. We only assert the attempted call.
                try:
                    closed_loop_actions.complete_retrain_swap(
                        db,
                        deployment_id=None,
                        job=job,
                        actor_id=str(uuid4()),
                        model_name="ungated-model",
                    )
                except AssertionError:
                    pass
        register.assert_called_once()
