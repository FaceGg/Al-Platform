"""Wizard guidance helpers (spec v0.9 §11): UserGuidance contract application.

注入优先级（§11.3）：用户引导 > 跨任务经验（L2）> 技能默认。用户明确的
选择是硬约束；metric_gates 替换默认硬门禁，但低于平台默认的项必须产生
黄条警示并记入配方审计（RSI 的"只收紧"约束技能演进，用户引导不受限但
全程留痕）。
"""

from __future__ import annotations

from app.services.agent.contracts import UserGuidance

STAGES = ("s1", "s2", "s3", "s4")


def merge_gates(defaults: dict, user_gates: dict | None) -> tuple[dict, list[str]]:
    """用户门禁替换默认；低于默认的项产生黄条警示文案（11.3 护栏）。"""
    merged = dict(defaults or {})
    warnings: list[str] = []
    for key, value in (user_gates or {}).items():
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            warnings.append("invalid_gate_ignored: %s=%r" % (key, value))
            continue
        merged[key] = numeric
        default_value = (defaults or {}).get(key)
        if default_value is not None and numeric < float(default_value):
            warnings.append(
                "gate_below_platform_default: %s=%.4f < %.4f（低于平台默认，"
                "模型质量风险自担；已记入配方审计）" % (key, numeric, float(default_value))
            )
    return merged, warnings


def algorithm_scope(guidance: UserGuidance | dict | None) -> list[str]:
    """S3 搜索空间：算法白名单是硬约束（空 = 全族搜索）。"""
    if guidance is None:
        return []
    if isinstance(guidance, dict):
        return [str(name) for name in guidance.get("modeling", {}).get(
            "algorithm_whitelist", []
        )]
    return [str(name) for name in guidance.modeling.algorithm_whitelist]


def pause_plan(guidance: UserGuidance | dict | None) -> set[str]:
    """逐步确认模式：合法暂停位（S1–S4 之间各一）。"""
    if guidance is None:
        return set()
    if isinstance(guidance, dict):
        requested_list = guidance.get("pause_at_stages") or []
    else:
        requested_list = guidance.pause_at_stages or []
    return set(requested_list) & set(STAGES)
