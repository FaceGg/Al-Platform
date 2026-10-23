"""AutoML Agent contracts (spec v0.9 §三): AnalysisReport / FeatureScript /
ReviewVerdict. Every LLM output is validated against these models; validation
failures feed back into the self-correction loop (P2 runner).
"""

from __future__ import annotations

import json
import re

from pydantic import BaseModel, Field, ValidationError


class AgentContractError(ValueError):
    """Contract validation failure with per-field details for the retry loop."""

    def __init__(self, message: str, details: list[str] | None = None) -> None:
        super().__init__(message)
        self.details = details or []


class FocusChannel(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    columns: list[str] = Field(min_length=1)
    why: str = Field(min_length=1, max_length=2000)


class ExpectedFeature(BaseModel):
    name_hint: str = Field(min_length=1, max_length=128)
    reason: str = Field(min_length=1, max_length=2000)
    priority: str = Field(default="medium", pattern="^(high|medium|low)$")


class QualityAction(BaseModel):
    column: str = Field(min_length=1, max_length=256)
    issue: str = Field(min_length=1, max_length=2000)
    action: str = Field(min_length=1, max_length=256)


class LeakageSuspect(BaseModel):
    column: str = Field(min_length=1, max_length=256)
    why: str = Field(min_length=1, max_length=2000)


class AnalysisReport(BaseModel):
    domain_hypothesis: str = Field(min_length=1, max_length=200)
    domain_reasoning: str = Field(min_length=1, max_length=4000)
    focus_channels: list[FocusChannel] = Field(min_length=1)
    expected_important_features: list[ExpectedFeature] = Field(min_length=1)
    data_quality_actions: list[QualityAction] = Field(default_factory=list)
    leakage_suspects: list[LeakageSuspect] = Field(default_factory=list)
    class_balance_concern: str | None = Field(default=None, max_length=2000)
    feature_engineering_brief: str = Field(min_length=1, max_length=8000)
    kb_citations: list[dict] = Field(default_factory=list)


class FeatureScript(BaseModel):
    """The S2 deliverable: a pure DataFrame→DataFrame transformation script."""

    script: str = Field(min_length=1, max_length=100_000)
    description: str = Field(min_length=1, max_length=4000)
    generated_columns: list[str] = Field(default_factory=list)
    dropped_columns: list[str] = Field(default_factory=list)
    data_shape: str = Field(default="tabular", pattern="^(tabular|waveform|mixed)$")


class ReviewAlignment(BaseModel):
    expected: str = Field(min_length=1, max_length=256)
    observed: str = Field(min_length=1, max_length=256)
    aligned: bool


class ReviewVerdict(BaseModel):
    verdict: str = Field(pattern="^(pass|fail|escalate)$")
    alignment: list[ReviewAlignment] = Field(default_factory=list)
    surprises: list[str] = Field(default_factory=list)
    business_readiness: str = Field(min_length=1, max_length=8000)
    next_iteration_hints: list[str] = Field(default_factory=list)


class GuidanceAnalysis(BaseModel):
    column_notes: list[dict] = Field(default_factory=list)
    row_notes: list[dict] = Field(default_factory=list)
    prompts: list[str] = Field(default_factory=list)
    suspect_focus: list[str] = Field(default_factory=list)


class GuidanceFeature(BaseModel):
    data_shape: str = Field(default="tabular", pattern="^(tabular|waveform|mixed)$")
    must_keep: list[str] = Field(default_factory=list)
    suggest_drop: list[dict] = Field(default_factory=list)
    prompts: list[str] = Field(default_factory=list)


class GuidanceModeling(BaseModel):
    algorithm_whitelist: list[str] = Field(default_factory=list)
    param_hints: dict = Field(default_factory=dict)
    prompts: list[str] = Field(default_factory=list)


class GuidanceEvaluation(BaseModel):
    custom_test_dataset_id: str | None = Field(default=None, max_length=64)
    metric_gates: dict = Field(default_factory=dict)
    review_focus: list[str] = Field(default_factory=list)


class UserGuidance(BaseModel):
    """第四契约（§11.2）：四步向导的可选注入，全不填即全自动。"""

    analysis: GuidanceAnalysis = Field(default_factory=GuidanceAnalysis)
    feature: GuidanceFeature = Field(default_factory=GuidanceFeature)
    modeling: GuidanceModeling = Field(default_factory=GuidanceModeling)
    evaluation: GuidanceEvaluation = Field(default_factory=GuidanceEvaluation)
    pause_at_stages: list[str] = Field(default_factory=list)

    def is_empty(self) -> bool:
        return not (
            self.analysis.column_notes
            or self.analysis.row_notes
            or self.analysis.prompts
            or self.analysis.suspect_focus
            or self.feature.must_keep
            or self.feature.suggest_drop
            or self.feature.prompts
            or self.modeling.algorithm_whitelist
            or self.modeling.param_hints
            or self.modeling.prompts
            or self.evaluation.custom_test_dataset_id
            or self.evaluation.metric_gates
            or self.evaluation.review_focus
        )


class UnsatisfactoryItem(BaseModel):
    issue: str = Field(min_length=1, max_length=2000)
    cause: str = Field(min_length=1, max_length=2000)
    missing: str = Field(min_length=1, max_length=2000)
    suggestion: str = Field(min_length=1, max_length=2000)


class OptimizationReport(BaseModel):
    """第五契约（§13.2）：每次任务结束自动生成，数字一律取自平台计量。"""

    what_optimized: list[str] = Field(default_factory=list)
    findings: list[str] = Field(default_factory=list)
    strengths: list[str] = Field(default_factory=list)
    unsatisfactory: list[UnsatisfactoryItem] = Field(default_factory=list)
    next_hints: list[str] = Field(default_factory=list)
    cost: dict = Field(default_factory=dict)


_CODE_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


def parse_llm_json(text: str) -> dict:
    """Parse a JSON object from LLM output, tolerating markdown code fences."""
    if not text or not text.strip():
        raise AgentContractError("empty LLM output")
    candidates: list[str] = []
    fenced = _CODE_FENCE_RE.findall(text)
    candidates.extend(fragment.strip() for fragment in fenced)
    stripped = text.strip()
    candidates.append(stripped)
    brace_start = stripped.find("{")
    brace_end = stripped.rfind("}")
    if brace_start != -1 and brace_end > brace_start:
        candidates.append(stripped[brace_start : brace_end + 1])
    errors: list[str] = []
    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError as error:
            errors.append(str(error))
            continue
        if isinstance(parsed, dict):
            return parsed
        errors.append("top-level JSON value is not an object")
    raise AgentContractError("LLM output is not a JSON object", errors)


def validate_contract(model_cls: type[BaseModel], data: dict) -> BaseModel:
    try:
        return model_cls.model_validate(data)
    except ValidationError as error:
        details = [
            f"{'.'.join(str(part) for part in item['loc'])}: {item['msg']}"
            for item in error.errors()
        ]
        raise AgentContractError(
            f"{model_cls.__name__} contract violation", details
        ) from error
