"""SPC pure-function statistics (补齐路线第一批 F4, B1-06).

统计过程控制的纯函数库：不依赖数据库与框架，口径可独立测试。

- 控制图：X-bar R、X-bar S、I-MR（计量型）；P、NP、C、U（计数型）；
- 判异：Nelson 规则 1–8；
- 能力指数：Cp / Cpk / Pp / Ppk / Cpm / Cr / σ 水平 / 估计 PPM。

口径（诚实设计②，页面须注明）：
- **Cp / Cpk 用组内标准差**（子组极差或标准差估计），**Pp / Ppk 用整体标准差**；
- 组内标准差只能由子组（容量 2–10）或外部给定的冻结基线 σ 得到；两者都没有时
  回退为整体标准差，并在结果里把 `within_sigma_source` 标成 `overall`——调用方
  必须据此提示「组内 σ 由整体估计」，不得当成真正的 Cpk；
- 缺规格限时能力指数一律留空（None），不报错；
- 估计 PPM 按正态分布近似，用整体标准差计算。

控制图常数取自常规控制图常数表（与 ISO 7870、ASTM MNL 7 一致）。
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Sequence

# 子群容量 n → 常数
CONSTANTS: dict[int, dict[str, float]] = {
    2: {"A2": 1.880, "A3": 2.659, "d2": 1.128, "D3": 0.000, "D4": 3.267, "B3": 0.000, "B4": 3.267, "c4": 0.7979},
    3: {"A2": 1.023, "A3": 1.954, "d2": 1.693, "D3": 0.000, "D4": 2.574, "B3": 0.000, "B4": 2.568, "c4": 0.8862},
    4: {"A2": 0.729, "A3": 1.628, "d2": 2.059, "D3": 0.000, "D4": 2.282, "B3": 0.000, "B4": 2.266, "c4": 0.9213},
    5: {"A2": 0.577, "A3": 1.427, "d2": 2.326, "D3": 0.000, "D4": 2.114, "B3": 0.000, "B4": 2.089, "c4": 0.9400},
    6: {"A2": 0.483, "A3": 1.347, "d2": 2.534, "D3": 0.000, "D4": 2.004, "B3": 0.030, "B4": 1.970, "c4": 0.9515},
    7: {"A2": 0.419, "A3": 1.289, "d2": 2.704, "D3": 0.076, "D4": 1.924, "B3": 0.118, "B4": 1.882, "c4": 0.9594},
    8: {"A2": 0.373, "A3": 1.182, "d2": 2.847, "D3": 0.136, "D4": 1.864, "B3": 0.185, "B4": 1.815, "c4": 0.9650},
    9: {"A2": 0.337, "A3": 1.156, "d2": 2.970, "D3": 0.184, "D4": 1.816, "B3": 0.239, "B4": 1.761, "c4": 0.9693},
    10: {"A2": 0.308, "A3": 1.128, "d2": 3.078, "D3": 0.223, "D4": 1.777, "B3": 0.284, "B4": 1.716, "c4": 0.9727},
}

MIN_SUBGROUP = 2
MAX_SUBGROUP = 10


class SpcError(ValueError):
    """输入不满足控制图的前提（子群容量越界、数据不足等）。"""


def _finite(values: Sequence[float]) -> list[float]:
    cleaned = [float(value) for value in values if value is not None and math.isfinite(float(value))]
    return cleaned


def _mean(values: Sequence[float]) -> float:
    return sum(values) / len(values)


def sample_std(values: Sequence[float]) -> float:
    """样本标准差（n-1）。少于两个点返回 0。"""
    if len(values) < 2:
        return 0.0
    average = _mean(values)
    return math.sqrt(sum((value - average) ** 2 for value in values) / (len(values) - 1))


def within_sigma(subgroups: Sequence[Sequence[float]], method: str = "r") -> float:
    """组内标准差：method='r' 用平均移动极差 / d2（R 图口径），'s' 用 Sbar / c4。"""
    sizes = {len(group) for group in subgroups}
    if len(sizes) != 1:
        raise SpcError("子群容量必须一致")
    size = sizes.pop()
    if size not in CONSTANTS:
        raise SpcError("SPC_SUBGROUP_SIZE_INVALID（子群容量须为 2–10）")
    constants = CONSTANTS[size]
    if method == "r":
        ranges = [max(group) - min(group) for group in subgroups]
        return _mean(ranges) / constants["d2"]
    deviations = [sample_std(group) for group in subgroups]
    return _mean(deviations) / constants["c4"]


@dataclass
class ChartLimits:
    center: float
    ucl: float
    lcl: float
    sigma: float


@dataclass
class ChartPoint:
    index: int
    value: float
    violations: list[int] = field(default_factory=list)
    # 控制限随样本量变化的图（P / NP / U）逐点给出上下限；其余图为空，用 ChartResult.limits
    ucl: float | None = None
    lcl: float | None = None


@dataclass
class ChartResult:
    kind: str
    points: list[ChartPoint]
    limits: ChartLimits
    # 离散图的下控制限在数学上可以为负，但计数不可能为负：按惯例截到 0
    violations: list[dict] = field(default_factory=list)
    in_control_count: int = 0
    notes: list[str] = field(default_factory=list)

    @property
    def in_control_rate(self) -> float | None:
        return (self.in_control_count / len(self.points)) if self.points else None


def _apply_rules(kind: str, values: Sequence[float], center: float, sigma: float, rules) -> tuple[list[ChartPoint], list[dict]]:
    points: list[ChartPoint] = []
    violations: list[dict] = []
    for index, value in enumerate(values):
        hits = nelson_rules(values, center, sigma, rules=rules, at=index)
        points.append(ChartPoint(index=index, value=value, violations=list(hits)))
        for rule in hits:
            violations.append({"chart": kind, "rule": rule, "index": index, "value": value})
    return points, violations


def _chart(kind: str, values: Sequence[float], center: float, sigma: float, lower: float | None, rules) -> ChartResult:
    lower = center - 3 * sigma if lower is None else lower
    upper = center + 3 * sigma
    points, violations = _apply_rules(kind, values, center, sigma, rules)
    return ChartResult(
        kind=kind, points=points,
        limits=ChartLimits(center=center, ucl=upper, lcl=lower, sigma=sigma),
        violations=violations,
        in_control_count=sum(1 for point in points if not point.violations),
    )


def subgroup_charts(
    subgroups: Sequence[Sequence[float]], *, chart: str = "xbar_r", rules=range(1, 9),
) -> dict[str, ChartResult]:
    """X-bar R / X-bar S：返回 {"xbar": …, "r" | "s": …} 两张图。"""
    if chart not in ("xbar_r", "xbar_s"):
        raise SpcError("SPC_CHART_KIND_INVALID")
    sizes = {len(group) for group in subgroups}
    if len(sizes) != 1:
        raise SpcError("子群容量必须一致")
    size = sizes.pop()
    if size not in CONSTANTS:
        raise SpcError("SPC_SUBGROUP_SIZE_INVALID（子群容量须为 2–10）")
    constants = CONSTANTS[size]
    means = [_mean(group) for group in subgroups]
    # 控制限直接用常数表上的 A2 / A3（与教科书、竞品口径一致）；表值只保留三位小数，
    # 不用 3·σ/√n 反算——两者在末位有舍入差
    if chart == "xbar_r":
        dispersions = [max(group) - min(group) for group in subgroups]
        dispersion_center = _mean(dispersions)
        individual_sigma = dispersion_center / constants["d2"]
        xbar = _chart("xbar", means, _mean(means), constants["A2"] * dispersion_center / 3, None, rules)
        # R 的下控制限 D3·Rbar 可以为 0；不套用 σ 规则（极差不是正态量），只判越限
        secondary = _chart("r", dispersions, dispersion_center, individual_sigma,
                           constants["D3"] * dispersion_center, rules=())
        secondary.limits.ucl = constants["D4"] * dispersion_center
    else:
        dispersions = [sample_std(group) for group in subgroups]
        dispersion_center = _mean(dispersions)
        individual_sigma = dispersion_center / constants["c4"]
        xbar = _chart("xbar", means, _mean(means), constants["A3"] * dispersion_center / 3, None, rules)
        secondary = _chart("s", dispersions, dispersion_center, individual_sigma,
                           constants["B3"] * dispersion_center, rules=())
        secondary.limits.ucl = constants["B4"] * dispersion_center
    secondary.violations = [
        {"chart": secondary.kind, "rule": 1, "index": point.index, "value": point.value}
        for point in secondary.points if point.value > secondary.limits.ucl or point.value < secondary.limits.lcl
    ]
    for point in secondary.points:
        if any(item["index"] == point.index for item in secondary.violations):
            point.violations.append(1)
    secondary.in_control_count = sum(1 for point in secondary.points if not point.violations)
    return {"xbar": xbar, secondary.kind: secondary}


def i_mr_chart(values: Sequence[float], *, rules=range(1, 9)) -> dict[str, ChartResult]:
    """I-MR（单值 - 移动极差）：中心 = 均值，σ = 平均移动极差 / 1.128（与基线冻结同口径）。"""
    if len(values) < 2:
        raise SpcError("SPC_NOT_ENOUGH_POINTS（I-MR 至少需要 2 个点）")
    moving_ranges = [abs(values[index] - values[index - 1]) for index in range(1, len(values))]
    mr_center = _mean(moving_ranges)
    sigma = mr_center / CONSTANTS[2]["d2"]
    individuals = _chart("i", values, _mean(values), sigma, None, rules)
    moving = _chart("mr", moving_ranges, mr_center, sigma, 0.0, rules=())
    moving.limits.ucl = CONSTANTS[2]["D4"] * mr_center
    moving.violations = [
        {"chart": "mr", "rule": 1, "index": point.index, "value": point.value}
        for point in moving.points if point.value > moving.limits.ucl
    ]
    for point in moving.points:
        if any(item["index"] == point.index for item in moving.violations):
            point.violations.append(1)
    moving.in_control_count = sum(1 for point in moving.points if not point.violations)
    return {"i": individuals, "mr": moving}


def attribute_chart(
    kind: str, counts: Sequence[int], sizes: Sequence[int] | None = None, *, rules=range(1, 9),
) -> ChartResult:
    """P / NP / C / U 图。P、U 的控制限随样本量变化，逐点计算。"""
    if kind not in ("p", "np", "c", "u"):
        raise SpcError("SPC_CHART_KIND_INVALID")
    sizes = list(sizes) if sizes is not None else [1] * len(counts)
    if len(sizes) != len(counts):
        raise SpcError("SPC_SIZE_MISMATCH（样本量与计数个数不一致）")
    if any(size <= 0 for size in sizes):
        raise SpcError("SPC_SIZE_INVALID（样本量须为正）")
    total = sum(sizes)
    if total <= 0:
        raise SpcError("SPC_SIZE_INVALID（样本量须为正）")
    violations: list[dict] = []
    points: list[ChartPoint] = []
    if kind in ("p", "np"):
        p_bar = sum(counts) / total
        center_line = p_bar
        per_unit = [count / size for count, size in zip(counts, sizes)]
        for index, (count, size) in enumerate(zip(counts, sizes)):
            if kind == "p":
                center, sigma = p_bar, math.sqrt(p_bar * (1 - p_bar) / size)
                value = per_unit[index]
            else:
                center, sigma, value = p_bar * size, math.sqrt(size * p_bar * (1 - p_bar)), count
            lower, upper = max(0.0, center - 3 * sigma), center + 3 * sigma
            hits = [1] if value > upper or value < lower else []
            points.append(ChartPoint(index=index, value=value, violations=hits, ucl=upper, lcl=lower))
    else:
        # C / U：泊松口径，σ = sqrt(中心)。U 图的中心线是加权平均（总缺陷数 / 总样本量），
        # 不是各点单位缺陷数的简单平均——样本量不等时两者不同
        units = sum(sizes)
        c_bar = sum(counts) / units if kind == "u" else _mean([float(count) for count in counts])
        center = c_bar
        center_line = c_bar
        for index, (count, size) in enumerate(zip(counts, sizes)):
            value = count / size if kind == "u" else float(count)
            sigma = math.sqrt(c_bar / size) if kind == "u" else math.sqrt(c_bar)
            lower, upper = max(0.0, center - 3 * sigma), center + 3 * sigma
            hits = [1] if value > upper or value < lower else []
            points.append(ChartPoint(index=index, value=value, violations=hits, ucl=upper, lcl=lower))
    for point in points:
        for rule in point.violations:
            violations.append({"chart": kind, "rule": rule, "index": point.index, "value": point.value})
    upper_limits = [point.ucl for point in points if point.ucl is not None]
    lower_limits = [point.lcl for point in points if point.lcl is not None]
    center = center_line
    variable_limits = len(set(sizes)) > 1
    return ChartResult(
        kind=kind, points=points,
        # 汇总限取最紧的一组（最大下限、最小上限）；各点真实限见 ChartPoint
        limits=ChartLimits(
            center=center,
            ucl=min(upper_limits) if upper_limits else center,
            lcl=max(lower_limits) if lower_limits else center,
            sigma=0.0,
        ),
        violations=violations,
        in_control_count=sum(1 for point in points if not point.violations),
        notes=(["样本量不一致：控制限逐点变化，见各点上下限"] if variable_limits else []),
    )


def nelson_rules(
    values: Sequence[float], center: float, sigma: float, *, rules=range(1, 9), at: int | None = None,
) -> list[int]:
    """Nelson 判异规则 1–8。

    at=None：返回整条序列命中的规则（去重升序）；给定 at：只判「以第 at 个点结尾」的模式。
    σ 为 0 时不判（没有可用的尺度）。
    """
    if sigma <= 0 or not values:
        return []
    wanted = set(rules)
    hits: set[int] = set()

    def beyond(index: int, level: float) -> bool:
        return abs(values[index] - center) > level * sigma

    def same_side(indices) -> bool:
        return all(values[index] > center for index in indices) or all(values[index] < center for index in indices)

    def run(indices, level: float, needed: int) -> bool:
        """indices 这一段里至少 needed 个点在同一侧超出 level·σ。"""
        upper = sum(1 for index in indices if values[index] - center > level * sigma)
        lower = sum(1 for index in indices if center - values[index] > level * sigma)
        return upper >= needed or lower >= needed

    for index in (range(len(values)) if at is None else [at]):
        window = lambda length: list(range(max(0, index - length + 1), index + 1))  # noqa: E731
        if 1 in wanted and beyond(index, 3):
            hits.add(1)
        nine = window(9)
        if 2 in wanted and len(nine) == 9 and same_side(nine):
            hits.add(2)
        six = window(6)
        if 3 in wanted and len(six) == 6:
            if all(values[later] > values[earlier] for earlier, later in zip(six, six[1:])) or \
                    all(values[later] < values[earlier] for earlier, later in zip(six, six[1:])):
                hits.add(3)
        fourteen = window(14)
        if 4 in wanted and len(fourteen) == 14:
            signs = [1 if values[later] > values[earlier] else -1 if values[later] < values[earlier] else 0
                     for earlier, later in zip(fourteen, fourteen[1:])]
            if 0 not in signs and all(sign != previous for sign, previous in zip(signs, signs[1:])):
                hits.add(4)
        if 5 in wanted and len(window(3)) == 3 and run(window(3), 2, 2):
            hits.add(5)
        if 6 in wanted and len(window(5)) == 5 and run(window(5), 1, 4):
            hits.add(6)
        fifteen = window(15)
        if 7 in wanted and len(fifteen) == 15 and all(not beyond(item, 1) for item in fifteen):
            hits.add(7)
        eight = window(8)
        if 8 in wanted and len(eight) == 8 and all(beyond(item, 1) for item in eight):
            hits.add(8)
    return sorted(hits)


@dataclass
class Capability:
    count: int
    mean: float
    usl: float | None
    lsl: float | None
    target: float | None
    within_sigma: float
    overall_sigma: float
    # range：子群极差估计；baseline：外部给定的冻结基线 σ；overall：回退为整体标准差
    within_sigma_source: str
    cp: float | None = None
    cpk: float | None = None
    pp: float | None = None
    ppk: float | None = None
    cpm: float | None = None
    cr: float | None = None
    sigma_level: float | None = None
    ppm: float | None = None


def _normal_cdf(value: float) -> float:
    return 0.5 * (1.0 + math.erf(value / math.sqrt(2.0)))


def capability(
    values: Sequence[float], *, usl: float | None = None, lsl: float | None = None,
    target: float | None = None, subgroups: Sequence[Sequence[float]] | None = None,
    baseline_sigma: float | None = None,
) -> Capability:
    """能力指数：Cp / Cpk 用组内 σ，Pp / Ppk 用整体 σ；缺规格限时全部留空。"""
    data = _finite(values)
    mean = _mean(data) if data else 0.0
    overall = sample_std(data)
    within, source = overall, "overall"
    if baseline_sigma is not None and baseline_sigma > 0:
        within, source = float(baseline_sigma), "baseline"
    elif subgroups and all(MIN_SUBGROUP <= len(group) <= MAX_SUBGROUP for group in subgroups):
        within, source = within_sigma(subgroups, "r"), "range"
    result = Capability(
        count=len(data), mean=mean, usl=usl, lsl=lsl, target=target,
        within_sigma=within, overall_sigma=overall, within_sigma_source=source,
    )
    if usl is None and lsl is None:
        return result
    spread = (usl - lsl) if (usl is not None and lsl is not None) else None

    def one_sided(sigma: float, width: float) -> float | None:
        return (width / (3 * sigma)) if sigma > 0 else None

    if spread is not None and within > 0:
        result.cp = spread / (6 * within)
        result.cr = 1.0 / result.cp
        result.pp = spread / (6 * overall) if overall > 0 else None
        if target is not None:
            result.cpm = spread / (6 * math.sqrt(within ** 2 + (mean - target) ** 2))
    upper = one_sided(within, usl - mean) if usl is not None else None
    lower = one_sided(within, mean - lsl) if lsl is not None else None
    result.cpk = min(item for item in (upper, lower) if item is not None) if (upper is not None or lower is not None) else None
    upper_o = one_sided(overall, usl - mean) if usl is not None else None
    lower_o = one_sided(overall, mean - lsl) if lsl is not None else None
    result.ppk = min(item for item in (upper_o, lower_o) if item is not None) if (upper_o is not None or lower_o is not None) else None
    distances = [item for item in (
        (usl - mean) if usl is not None else None,
        (mean - lsl) if lsl is not None else None,
    ) if item is not None]
    if distances and overall > 0:
        result.sigma_level = min(distances) / overall
        tail = 0.0
        if usl is not None:
            tail += 1.0 - _normal_cdf((usl - mean) / overall)
        if lsl is not None:
            tail += _normal_cdf((lsl - mean) / overall)
        result.ppm = max(0.0, min(1.0, tail)) * 1_000_000
    return result


def histogram(values: Sequence[float], bins: int = 20) -> dict:
    """等宽直方图：边界 bins + 1 个、计数 bins 个。所有值相同时退化成一个极窄区间。"""
    data = _finite(values)
    if not data:
        return {"edges": [], "counts": []}
    bins = max(1, int(bins))
    low, high = min(data), max(data)
    if high == low:
        low, high = low - 0.5, high + 0.5
    width = (high - low) / bins
    counts = [0] * bins
    for value in data:
        bucket = min(bins - 1, int((value - low) / width))
        counts[bucket] += 1
    edges = [low + index * width for index in range(bins + 1)]
    return {"edges": edges, "counts": counts}
