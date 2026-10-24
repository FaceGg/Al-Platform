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
from app.services.agent.wizard import merge_gates, pause_plan
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
        self._finalize_reports()
        return self.run

    def _l2_references(self) -> list[dict]:
        """§10.4 任务启动/S1 注入：检索 L2 top-k active 经验（独立引述块）。

        检索失败静默降级为空——经验注入是增益，不是依赖。"""
        from app.services.agent.experience import retrieve_for_task

        try:
            entries = retrieve_for_task(
                self.db,
                domain=getattr(self, "_last_domain", None) or "cross-domain",
                profile_fingerprint={},
                top_k=5,
                project_id=getattr(self.run, "project_id", None),
            )
        except Exception:  # noqa: BLE001 - 经验库故障不应阻断建模
            return []
        return [
            {
                "entry": str(entry.id)[:13],
                "situation": entry.situation,
                "lesson": entry.lesson,
                "action": entry.action,
                "confidence": entry.confidence,
                "origin": entry.origin,
            }
            for entry in entries
        ]

    def _finalize_reports(self) -> None:
        """终态收尾（§10.1 蒸馏 + §13.2 优化报告）：任何失败都不改终态。"""
        try:
            from app.services.agent.optimization_report import build_report

            build_report(self.db, run=self.run, config=self.config, actor=self.actor)
        except Exception:  # noqa: BLE001
            pass
        try:
            from app.services.agent.experience import distill_experience_entries

            created = distill_experience_entries(
                self.db, config=self.config, run=self.run, memory=self.memory
            )
            if created:
                result = dict(self.run.result_json or {})
                result["distilled_experience"] = [str(item) for item in created]
                self.run.result_json = result
                self.db.commit()
        except Exception:  # noqa: BLE001
            pass

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
            attempts.append({"attempt": attempt, "ok": True,
                             "script": script.script})
            self.run.current_stage = "s3"
            return result.output, attempts

        return None, attempts

    # ------------------------------------------------------------------ main
    def _pause_if_requested(
        self, stage: str, pause_at: set, resume_state, round_number: int
    ) -> bool:
        """逐步确认模式（§11.1）：stage 完成后若请求了暂停且本轮未暂停过，
        转 waiting_guidance 并记录；下一次 run_to_completion 跳过该位继续。"""
        if stage not in pause_at:
            return False
        memory = self.run.memory_json or {}
        done_key = "paused:%s:%d" % (stage, round_number)
        already = (memory.get("resume") or {}).get("done", [])
        if resume_state is not None or done_key in already:
            return False
        already.append(done_key)
        memory["resume"] = {"done": already, "next_stage": stage, "round": round_number}
        self.run.memory_json = memory
        self.run.status = "waiting_guidance"
        self.db.commit()
        return True

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

        guidance_model = self.guidance if isinstance(self.guidance, dict) else None
        pause_at = pause_plan(self.guidance) if self.guidance is not None else set()
        resume_state = self.run.memory_json.get("resume") if self.run.memory_json else None

        round_number = 0
        while round_number < MAX_ROUNDS:
            round_number += 1
            self.run.round_count = round_number
            self.run.current_stage = "s1"
            self.db.commit()

            # ---- S1 -------------------------------------------------
            l2_refs = self._l2_references()
            report, error, usage = run_s1(
                self.db,
                config=self.config,
                profile_report=self.profile_report,
                prior_memory=self._memory_digest(),
                experience_references=l2_refs,
                guidance=(self.guidance or {}).get("analysis") if isinstance(self.guidance, dict) else None,
                actor=self.actor,
            )
            if not self._absorb_usage(usage):
                return self._escalate("AGENT_TOKEN_BUDGET_EXCEEDED")
            if error:
                return self._escalate("AGENT_S1_CONTRACT_FAILED")
            # 注入的 L2 引用落档案（前端"注入的经验"面板数据源）。
            if l2_refs:
                memory = self.run.memory_json or {}
                memory["injected_experience"] = l2_refs
                self.run.memory_json = memory
            # 下一轮 L2 检索按本轮域假设聚焦（§10.4 domain 匹配）。
            self._last_domain = str(report.domain_hypothesis)[:32]
            if self._pause_if_requested("s1", pause_at, resume_state, round_number):
                return self.run

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
            user_gates = None
            if isinstance(self.guidance, dict):
                user_gates = ((self.guidance or {}).get("evaluation") or {}).get(
                    "metric_gates"
                )
            gates, gate_warnings = merge_gates(DEFAULT_GATES, user_gates)
            if gate_warnings:
                memory = self.run.memory_json or {}
                gate_log = list(memory.get("gate_warnings") or [])
                gate_log.extend(
                    "round %d: %s" % (round_number, warning)
                    for warning in gate_warnings
                )
                memory["gate_warnings"] = gate_log
                self.run.memory_json = memory  # 黄条警示随任务档案留痕（§11.3）
            if resume_state is not None:
                memory = self.run.memory_json or {}
                memory.pop("resume", None)
                self.run.memory_json = memory
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
                self._finalize_reports()
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
