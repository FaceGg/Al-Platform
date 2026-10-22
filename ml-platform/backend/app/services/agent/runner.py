"""Agent Runner (spec v0.9 §二/§三): the thin orchestration loop.

Bounded iteration (≤3 rounds), S2 self-correction (≤8 attempts with a meta
hint after 3 identical failures), L1 run memory carried into the next round's
S1 prompt, a token-budget fuse, S4 hard gates evaluated BEFORE the LLM review
(so a review can never relax them), and mandatory recording of the LLM
profile/model used. S3 is an injected trainer callable — the P3 milestone
binds it to the platform AutoML engine; tests inject a deterministic fake.
"""

from __future__ import annotations

import uuid
from collections import Counter
from typing import Callable

from sqlalchemy.orm import Session

from app.config import settings
from app.models.agent_run import AgentRun
from app.services.agent.contracts import AnalysisReport
from app.services.agent.hard_gates import PRIMARY_METRIC, evaluate_hard_gates
from app.services.agent.llm_client import run_s1, run_s2, run_s4
from app.services.agent.sandbox import ast_violations, check_contract, run_sandbox
from app.services.llm_gateway import GatewayLLMConfig

MAX_ROUNDS = 3
MAX_S2_ATTEMPTS = 8
META_HINT_AFTER_SAME_ERROR = 3
DEFAULT_GATES = {PRIMARY_METRIC: 0.90}
S2_SAMPLE_ROWS = 5000

Trainer = Callable[[object, object, dict], dict]


class AgentRunner:
    def __init__(
        self,
        db: Session,
        *,
        run: AgentRun,
        config: GatewayLLMConfig,
        profile_report: dict,
        dataset_frame: object,
        guidance: dict | None = None,
        trainer: Trainer,
        actor=None,
    ) -> None:
        self.db = db
        self.run = run
        self.config = config
        self.profile_report = profile_report
        self.frame = dataset_frame
        self.guidance = guidance
        self.trainer = trainer
        self.actor = actor
        self.memory: dict = {"rounds": []}
        self._usage_total = 0

    # ------------------------------------------------------------------ util
    def _absorb_usage(self, usage: dict) -> bool:
        """Accumulate token usage; returns False when the budget is blown."""
        self._usage_total += int((usage or {}).get("total_tokens") or 0)
        self.run.token_used = self._usage_total
        budget = self.run.token_budget
        if budget and self._usage_total > budget:
            return False
        return True

    def _memory_digest(self) -> dict | None:
        """L1 digest the next round must carry (errors, fixes, hints)."""
        rounds = self.memory.get("rounds", [])
        if not rounds:
            return None
        last = rounds[-1]
        return {
            "last_round": last.get("round"),
            "s2_error_fixes": last.get("s2_attempts", [])[-4:],
            "s4_verdict": last.get("verdict"),
            "hints": last.get("hints", []),
        }

    def _record_round(
        self, round_number: int, *, s2_attempts: list, verdict: str | None, hints: list
    ) -> None:
        self.memory.setdefault("rounds", []).append(
            {
                "round": round_number,
                "s2_attempts": s2_attempts,
                "verdict": verdict,
                "hints": hints,
            }
        )

    def _escalate(self, error_code: str) -> AgentRun:
        self.run.status = "waiting_escalate"
        self.run.error_code = error_code
        self.run.memory_json = self.memory
        self.run.result_json = {"token_used": self._usage_total}
        self.db.commit()
        return self.run

    # ----------------------------------------------------------------- stages
    def _run_s2_stage(self, report: AnalysisReport):
        """Generate + sandbox-verify the feature script; returns (df, attempts)."""
        sample = self.frame.head(S2_SAMPLE_ROWS)
        columns = [
            {"name": str(name), "dtype": str(dtype)}
            for name, dtype in sample.dtypes.items()
        ]
        leakage = [item.column for item in report.leakage_suspects]
        error_history: list[dict] = []
        attempts: list[dict] = []
        guidance_feature = (self.guidance or {}).get("feature")

        for attempt in range(1, MAX_S2_ATTEMPTS + 1):
            counter = Counter(entry.get("error", "") for entry in error_history)
            meta_hint = bool(
                counter and counter.most_common(1)[0][1] >= META_HINT_AFTER_SAME_ERROR
            )
            script, error, usage = run_s2(
                self.db,
                config=self.config,
                brief=report.feature_engineering_brief,
                columns=columns,
                leakage_suspects=leakage,
                error_history=error_history,
                meta_hint=meta_hint,
                guidance=guidance_feature,
                actor=self.actor,
            )
            if not self._absorb_usage(usage):
                raise _BudgetExceeded()
            attempt_record: dict = {"attempt": attempt}
            if error:
                attempt_record["error"] = error
                error_history.append(attempt_record)
                attempts.append(attempt_record)
                continue

            ast_problems = ast_violations(script.script)
            if ast_problems:
                attempt_record["error"] = "ast_violations"
                attempt_record["detail"] = ast_problems[:4]
                error_history.append(attempt_record)
                attempts.append(attempt_record)
                continue

            result = run_sandbox(script.script, sample, timeout_seconds=180)
            if not result.ok:
                attempt_record["error"] = result.error or "sandbox_failed"
                error_history.append(attempt_record)
                attempts.append(attempt_record)
                continue
            out_violations = check_contract(
                sample, result.output, leakage_columns=leakage
            )
            if out_violations:
                attempt_record["error"] = "contract_violations"
                attempt_record["detail"] = out_violations
                error_history.append(attempt_record)
                attempts.append(attempt_record)
                continue
            attempts.append({"attempt": attempt, "ok": True})
            self.run.current_stage = "s3"
            return result.output, attempts

        return None, attempts

    # ------------------------------------------------------------------ main
    def run_to_completion(self) -> AgentRun:
        """Drive the bounded S1→S4 loop and persist terminal state."""
        try:
            return self._execute()
        except _BudgetExceeded:
            return self._escalate("AGENT_TOKEN_BUDGET_EXCEEDED")

    def _execute(self) -> AgentRun:
        self.run.status = "running"
        self.run.llm_profile_id = (
            uuid.UUID(self.config.profile_id) if self.config.profile_id else None
        )
        self.run.llm_model_id = self.config.model_id
        self.db.commit()

        round_number = 0
        while round_number < MAX_ROUNDS:
            round_number += 1
            self.run.round_count = round_number
            self.run.current_stage = "s1"
            self.db.commit()

            # ---- S1 -------------------------------------------------
            report, error, usage = run_s1(
                self.db,
                config=self.config,
                profile_report=self.profile_report,
                prior_memory=self._memory_digest(),
                guidance=(self.guidance or {}).get("analysis"),
                actor=self.actor,
            )
            if not self._absorb_usage(usage):
                return self._escalate("AGENT_TOKEN_BUDGET_EXCEEDED")
            if error:
                return self._escalate("AGENT_S1_CONTRACT_FAILED")

            # ---- S2 -------------------------------------------------
            self.run.current_stage = "s2"
            self.db.commit()
            feature_df, s2_attempts = self._run_s2_stage(report)
            if feature_df is None:
                self._record_round(
                    round_number, s2_attempts=s2_attempts, verdict=None, hints=[]
                )
                return self._escalate("AGENT_S2_NOT_CONVERGED")

            # ---- S3 -------------------------------------------------
            self.run.current_stage = "s3"
            self.db.commit()
            target = self.run.target_column
            frame_columns = getattr(self.frame, "columns", [])
            y = self.frame[target] if target and target in frame_columns else None
            trainer_result = self.trainer(feature_df, y, {})

            # ---- S4 hard gates (before any LLM sees the numbers) ----
            self.run.current_stage = "s4"
            self.db.commit()
            gates = dict(DEFAULT_GATES)
            user_gates = ((self.guidance or {}).get("evaluation") or {}).get("metric_gates")
            if user_gates:
                gates = {**gates, **user_gates}
            gate_report = evaluate_hard_gates(
                trainer_result.get("metrics", {}),
                gates=gates,
                topk_metrics=trainer_result.get("topk_metrics"),
                importance=trainer_result.get("importance"),
                leakage_columns=[item.column for item in report.leakage_suspects],
            )

            if not gate_report.passed:
                # Hard-gate failure: back to S1 with hints. The review is not
                # even consulted — the LLM can never relax the gates.
                hints = [f"hard_gate: {failure}" for failure in gate_report.failures]
                self._record_round(
                    round_number,
                    s2_attempts=s2_attempts,
                    verdict="gate_failed",
                    hints=hints,
                )
                continue

            verdict, error, usage = run_s4(
                self.db,
                config=self.config,
                metrics=trainer_result.get("metrics", {}),
                importance=trainer_result.get("importance", []),
                expectations=[
                    item.model_dump() for item in report.expected_important_features
                ],
                gate_failures=[],
                round_number=round_number,
                actor=self.actor,
            )
            if not self._absorb_usage(usage):
                return self._escalate("AGENT_TOKEN_BUDGET_EXCEEDED")
            if error:
                return self._escalate("AGENT_S4_CONTRACT_FAILED")

            if verdict.verdict == "pass":
                self._record_round(
                    round_number, s2_attempts=s2_attempts, verdict="pass", hints=[]
                )
                self.run.status = "accepted"
                self.run.current_stage = "done"
                self.run.memory_json = self.memory
                self.run.result_json = {
                    "token_used": self._usage_total,
                    "metrics": trainer_result.get("metrics", {}),
                    "rounds": round_number,
                }
                self.db.commit()
                return self.run
            if verdict.verdict == "escalate":
                self._record_round(
                    round_number,
                    s2_attempts=s2_attempts,
                    verdict="escalate",
                    hints=list(verdict.next_iteration_hints),
                )
                return self._escalate("AGENT_REVIEW_ESCALATE")
            self._record_round(
                round_number,
                s2_attempts=s2_attempts,
                verdict="fail",
                hints=list(verdict.next_iteration_hints),
            )

        return self._escalate("AGENT_MAX_ROUNDS")


class _BudgetExceeded(Exception):
    """Internal: token fuse blown mid-stage."""
