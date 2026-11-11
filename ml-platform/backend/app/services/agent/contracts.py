"""AutoML Agent contracts (spec v0.9 §三): AnalysisReport / FeatureScript /
ReviewVerdict. Every LLM output is validated against these models; validation
failures feed back into the self-correction loop (P2 runner).
"""

from __future__ import annotations

import json
import re

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator


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
    # LLM 评审常把 observed/expected 写成裸数字（如 0.99 而非 "0.99"），
    # 语义无损——仅此模型放宽数字→字符串，其余契约仍严格 fail-closed
    # （真机 7c9415b1 run：alignment[8..11].observed 数字违约整轮升级）。
    model_config = ConfigDict(coerce_numbers_to_str=True)

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
    # 全量数据训练（默认 True=百分百真实实验）：S3 验收训练用全部行、
    # 类别编码不截断。仅在超大数据集（数十万行+）验收阶段过慢时由用户
    # 显式关闭——降采样触发时任务档案与验收指标旁会显式标注，绝不静默。
    full_data: bool = Field(default=True)


class GuidanceFeature(BaseModel):
    # 数据形态全局单选已退役（向导改列级标注）：默认改中性 mixed，
    # 避免 UI 不再传该字段时把 S2 带偏成纯表格处理。
    data_shape: str = Field(default="mixed", pattern="^(tabular|waveform|mixed)$")
    # 列级数据类型标注（tabular|waveform），向导按 dtype/高基数自动预填、
    # 用户可改；随引导引述块进入 S2 提示词。
    column_shapes: dict[str, str] = Field(default_factory=dict)
    must_keep: list[str] = Field(default_factory=list)
    suggest_drop: list[dict] = Field(default_factory=list)
    prompts: list[str] = Field(default_factory=list)


class GuidanceEnsemble(BaseModel):
    """集成学习（多模型加权投票）：S3 训练后取主指标前 K 名候选做
    soft-voting，权重按验证集少数类召回比例自动分配；冠军取集成与
    最佳单模型中 recall 更高者（持平取集成——多模型平均更稳）。"""

    enabled: bool = Field(default=False)
    top_k: int = Field(default=3, ge=2, le=5)


ANOMALY_TASK_TYPE = "anomaly"
SUPERVISED_TASK_TYPE = "supervised"
AGENT_TASK_TYPES = (SUPERVISED_TASK_TYPE, ANOMALY_TASK_TYPE)


class GuidanceModeling(BaseModel):
    algorithm_whitelist: list[str] = Field(default_factory=list)
    param_hints: dict = Field(default_factory=dict)
    ensemble: GuidanceEnsemble = Field(default_factory=GuidanceEnsemble)
    prompts: list[str] = Field(default_factory=list)
    # 无监督（anomaly_detection）专用：预期异常比例先验，宁低勿高（§3.4）。
    # 有监督任务恒为 None；trainer/gate 按 task_type 分支消费。
    contamination: float | None = Field(default=None, gt=0.0, le=0.5)


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
    # 搜索轮数上限（1-10，默认 3）：双门禁迭代的安全阀，用户可收紧/放宽。
    max_rounds: int = Field(default=3, ge=1, le=10)
    # 启动并服务化：验收通过（accepted）后自动起草 S5 三资产（发布仍需人工批准）。
    auto_servitize: bool = Field(default=False)
    # 知识源（向导第一步「知识源」卡片）：平台经验默认注入（L2 检索），
    # 知识中心知识库按用户多选检索相关块进 S1。检索失败静默降级。
    use_platform_experience: bool = Field(default=True)
    knowledge_base_ids: list[str] = Field(default_factory=list)
    # 平台经验注入参数（向导可配）：注入条数与最低置信度；entry_ids 非空时
    # 按用户勾选的具体条目注入（跳过检索 top-k，仍校验 active+置信度）。
    experience_top_k: int = Field(default=5, ge=3, le=5)
    experience_min_confidence: float = Field(default=0.80, ge=0.80, le=1.00)
    experience_entry_ids: list[str] = Field(default_factory=list)
    # 建模范式（技术方案 §2.1）：supervised（默认，存量行为零变化）| anomaly
    # （无监督异常检测）。随 guidance 固化终身不改，重放天然互斥；
    # anomaly 时 target_column 必须为空（合同镜像），S1-S4 按范式走分支。
    task_type: str = Field(default=SUPERVISED_TASK_TYPE)

    @field_validator("task_type")
    @classmethod
    def _validate_task_type(cls, value: str) -> str:
        if value not in AGENT_TASK_TYPES:
            raise ValueError("task_type must be one of: " + ", ".join(AGENT_TASK_TYPES))
        return value

    def is_empty(self) -> bool:
        return not (
            self.analysis.column_notes
            or self.analysis.row_notes
            or self.analysis.prompts
            or self.analysis.suspect_focus
            or self.feature.must_keep
            or self.feature.suggest_drop
            or self.feature.column_shapes
            or self.feature.prompts
            or self.modeling.algorithm_whitelist
            or self.modeling.param_hints
            or self.modeling.ensemble.enabled
            or self.modeling.prompts
            or self.evaluation.custom_test_dataset_id
            or self.evaluation.metric_gates
            or self.evaluation.review_focus
            or not self.analysis.full_data
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
