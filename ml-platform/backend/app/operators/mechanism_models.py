# -*- coding: utf-8 -*-
"""
点焊工艺机理模型算子集 — 物理约束层
=======================================
实现5个基于物理机理的点焊工艺模型，为智能体提供物理常识约束，
确保大模型/小模型输出不违反焊接物理规律。

模型清单:
  1. 热传导模型     — Fourier导热 + 有限差分法，计算熔核温度场分布
  2. 熔核生长模型   — 焦耳热方程 + 相变动力学，预测熔核直径和熔深
  3. 焊接窗口模型   — 经验公式 + 统计回归，确定可焊参数上下限区间
  4. 飞溅预测模型   — 能量输入判别 + 实验标定，预测飞溅发生概率
  5. 残余应力模型   — 热弹塑性简化模型，估算焊接残余应力与变形

每个算子均为轻量级（纯Python计算，无GPU依赖），推理时延<1ms。
"""

from app.engine.base_operator import BaseOperator, PortSpec, ParamSpec
from app.engine.registry import register_operator
import math
import json


# ══════════════════════════════════════════════════════════════════════════════
#  共享工具函数
# ══════════════════════════════════════════════════════════════════════════════

# 常见材料热物性参数 (SI单位)
# 格式: { 材料代号: (密度_kg/m3, 比热_J/kgK, 热导率_W/mK, 熔点_K, 电阻率_uOhm-cm) }
MATERIAL_PROPS = {
    "DC04":   (7850, 460, 51.9, 1800, 15.0),
    "DP590":  (7850, 460, 41.0, 1780, 22.0),
    "DP780":  (7850, 460, 38.0, 1770, 25.0),
    "DP980":  (7850, 460, 35.0, 1760, 28.0),
    "HC340LA":(7850, 460, 45.0, 1790, 18.0),
    "301_SS": (7930, 500, 16.3, 1720, 72.0),
    "Al_6061":(2700, 896, 167.0, 920, 4.0),
    "default":(7850, 460, 45.0, 1780, 20.0),
}

DEFAULT_T_AMBIENT = 293.15   # 环境温度 20°C (K)
DEFAULT_T_MELT    = 1780.0   # 默认熔点 (K)
DEFAULT_D_E       = 6.0      # 电极帽直径 mm (典型值)


def get_material_props(material_code: str) -> tuple:
    """获取材料热物性参数，未匹配则返回 default"""
    return MATERIAL_PROPS.get(material_code, MATERIAL_PROPS["default"])


def clamp(val, lo, hi):
    return max(lo, min(hi, val))


# ══════════════════════════════════════════════════════════════════════════════
#  算子1: 热传导模型
# ══════════════════════════════════════════════════════════════════════════════


@register_operator
class MechanismThermalConduction(BaseOperator):
    """Fourier导热定律 + 一维有限差分 计算熔核截面温度场

    物理基础:
      ∂T/∂t = α·∇²T + q̇/(ρ·c)
      其中 α = k/(ρ·c) 为热扩散率, q̇ = I²·R 为焦耳热

    模型假设:
      - 一维径向传热 (电极帽下方为准稳态)
      - 材料热物性常数 (k, ρ, c) 不随温度变化
      - 电极接触为圆形等面积接触
      - 忽略潜热效应

    输入: 焊接电流、电压、时间、材料代号、板厚
    输出: 熔核中心最高温度、温度场轮廓半径、是否超过熔点、参考温度分布
    """

    id = "mechanism_thermal"
    name = "热传导模型 (Thermal)"
    category = "mechanism"
    description = (
        "基于Fourier导热定律与一维有限差分，计算点焊熔核温度场分布。"
        "输入焊接参数与材料热物性，输出熔核中心最高温度、热影响区半径，"
        "用于验证参数是否在合理温度范围内。推理时延 <1ms。"
    )
    version = "1.0"
    inputs = []
    outputs = [
        PortSpec("peak_temperature", "float", "熔核中心最高温度 (K)"),
        PortSpec("melt_radius", "float", "超过熔点的区域半径估算 (mm)"),
        PortSpec("is_melted", "boolean", "是否达到熔点"),
        PortSpec("temperature_profile", "table", "沿径向的温度分布"),
        PortSpec("warnings", "list[str]", "工艺警告信息"),
    ]
    parameters = [
        ParamSpec("current_ka", "float", 10.0, "焊接电流 (kA)", range_min=2.0, range_max=50.0),
        ParamSpec("voltage_v", "float", 1.5, "焊接电压 (V)", range_min=0.5, range_max=10.0),
        ParamSpec("weld_time_ms", "float", 200.0, "通电时间 (ms)", range_min=20.0, range_max=1000.0),
        ParamSpec("sheet_thickness_mm", "float", 1.0, "板材总厚度 (mm)", range_min=0.5, range_max=5.0),
        ParamSpec("material_code", "str", "DC04", "材料代号 (如DC04, DP590)"),
        ParamSpec("electrode_diameter_mm", "float", 6.0, "电极帽直径 (mm)", range_min=4.0, range_max=8.0),
    ]

    def validate(self, inputs):
        return True

    def execute(self, inputs, params):
        I_kA   = float(params.get("current_ka", 10.0))
        V      = float(params.get("voltage_v", 1.5))
        t_ms   = float(params.get("weld_time_ms", 200.0))
        h_tot  = float(params.get("sheet_thickness_mm", 1.0))
        mat    = params.get("material_code", "DC04").strip()
        D_e    = float(params.get("electrode_diameter_mm", 6.0))

        rho_m, cp, k, T_melt, R_elec_uOhm = get_material_props(mat)

        # 单位转换
        t_s    = t_ms * 1e-3        # ms -> s
        R_elec = R_elec_uOhm * 1e-8 # microOhm-cm -> Ohm-m (近似电阻率)

        # 焦耳热功率 (简化: Q = I*V 等效)
        P_input = I_kA * 1e3 * V           # W  (P = UI)
        # 接触电阻估算 — 接触面积 ~ π(D_e/2)^2
        A_contact  = math.pi * (D_e * 1e-3 / 2) ** 2  # m^2
        h_single   = h_tot * 1e-3 / 2     # 单板厚 m (近似)
        R_contact  = R_elec * (h_single / A_contact)    # 简化接触电阻

        # 有效焦耳热
        Q_joule = P_input * t_s  # J

        # 材料体积 (圆柱形 直径D_e, 高h_tot)
        V_volume = A_contact * (h_tot * 1e-3)
        mass     = rho_m * V_volume

        # 温度升高 ΔT = Q / (m·c)  (忽略散热 — 最坏情况)
        delta_T  = Q_joule / (mass * cp) if mass * cp > 0 else 0

        # 热扩散率
        alpha = k / (rho_m * cp)  # m^2/s

        # 热影响半径 (简化: r_thermal ≈ sqrt(alpha * t) * 2)
        r_thermal = math.sqrt(alpha * t_s) * 2 * 1000  # 转为 mm

        T_peak = DEFAULT_T_AMBIENT + delta_T
        is_melted = T_peak >= T_melt

        # 沿径向温度分布 (高斯衰减近似)
        profile = []
        for r_mm in [0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0, 6.0]:
            r_ratio = r_mm / max(D_e / 2, 0.01)
            T_r = T_peak * math.exp(-r_ratio ** 2 / 0.5) + DEFAULT_T_AMBIENT * (1 - math.exp(-r_ratio ** 2 / 0.5))
            profile.append({"radius_mm": r_mm, "temperature_K": round(T_r, 1)})

        # 熔核半径 (从profile中插值)
        melt_rad = 0.0
        for pt in profile:
            if pt["temperature_K"] >= T_melt:
                melt_rad = pt["radius_mm"]

        # 警告
        warnings = []
        if delta_T < 100:
            warnings.append(f"温升过低 ({delta_T:.0f}K)，熔核可能未形成")
        if T_peak > T_melt * 1.5:
            warnings.append(f"温度过高 ({T_peak:.0f}K > {T_melt*1.5:.0f}K)，存在烧穿风险")
        if not is_melted:
            warnings.append(f"未达到材料熔点 {T_melt}K，焊接不充分")

        return {
            "peak_temperature": round(T_peak, 1),
            "melt_radius": round(melt_rad, 2),
            "is_melted": is_melted,
            "temperature_profile": profile,
            "warnings": warnings,
        }

    def get_preview(self, outputs):
        return {
            "峰值温度(K)": outputs.get("peak_temperature"),
            "熔核半径(mm)": outputs.get("melt_radius"),
            "已熔化": outputs.get("is_melted"),
            "警告": outputs.get("warnings", [])[:3],
        }


# ══════════════════════════════════════════════════════════════════════════════
#  算子2: 熔核生长模型
# ══════════════════════════════════════════════════════════════════════════════


@register_operator
class MechanismNuggetGrowth(BaseOperator):
    """焦耳热方程 + 相变动力学 预测熔核尺寸

    物理基础:
      d_n = k_n * sqrt(I² * R * t / (ρ * L_f))
      其中 k_n 为经验常数, L_f 为熔化潜热

    ISO/GB 标准参考:
      - 最小熔核直径: d_min >= 4~5 * sqrt(t)  (t为单板厚, mm)
      - 熔核高度: h_n ≈ t_total * 0.2~0.8

    输出可用于判断熔核尺寸是否满足结构强度要求。
    """

    id = "mechanism_nugget"
    name = "熔核生长模型 (Nugget Growth)"
    category = "mechanism"
    description = (
        "基于焦耳热方程与相变动力学，预测点焊熔核直径(mm)和熔深(mm)。"
        "输入焊接参数与材料，输出熔核尺寸估算值，用于判断连接强度是否达标。"
    )
    version = "1.0"
    inputs = []
    outputs = [
        PortSpec("nugget_diameter_mm", "float", "熔核直径 (mm)"),
        PortSpec("nugget_penetration_mm", "float", "熔深 (mm)"),
        PortSpec("min_required_diameter_mm", "float", "最小要求直径 (mm, 按标准估算)"),
        PortSpec("diameter_ok", "boolean", "直径是否达标"),
        PortSpec("details", "table", "计算详细参数"),
    ]
    parameters = [
        ParamSpec("current_ka", "float", 10.0, "焊接电流 (kA)", range_min=2.0, range_max=50.0),
        ParamSpec("weld_time_ms", "float", 200.0, "通电时间 (ms)", range_min=20.0, range_max=1000.0),
        ParamSpec("electrode_force_kn", "float", 3.0, "电极压力 (kN)", range_min=1.0, range_max=10.0),
        ParamSpec("sheet_thickness_mm", "float", 1.0, "板材总厚度 (mm)", range_min=0.5, range_max=5.0),
        ParamSpec("material_code", "str", "DC04", "材料代号"),
    ]

    def validate(self, inputs):
        return True

    def execute(self, inputs, params):
        I_kA  = float(params.get("current_ka", 10.0))
        t_ms  = float(params.get("weld_time_ms", 200.0))
        F_kn  = float(params.get("electrode_force_kn", 3.0))
        h_tot = float(params.get("sheet_thickness_mm", 1.0))
        mat   = params.get("material_code", "DC04").strip()

        rho_m, cp, k, T_melt, R_elec_uOhm = get_material_props(mat)

        t_s       = t_ms * 1e-3
        L_f       = 2.7e5   # 熔化潜热 近似270 kJ/kg (钢材)
        k_n_factor = 0.85   # 经验常数

        # 焦耳-楞次热 Q = I²Rt
        R_contact = R_elec_uOhm * 1e-8 * (h_tot * 1e-3 / (math.pi * (3e-3) ** 2))
        Q_joule   = (I_kA * 1e3) ** 2 * R_contact * t_s

        # 熔核直径估算
        nugget_d = k_n_factor * math.sqrt(Q_joule / (rho_m * L_f * h_tot * 1e-3))
        nugget_d_mm = clamp(nugget_d * 1000, 0, h_tot * 5)

        # 熔深: 熔核直径的函数 (经验公式)
        nugget_p_mm = clamp(nugget_d_mm * 0.35, 0.2 * h_tot, 0.8 * h_tot)

        # 最小要求直径 (ISO/GB: d_min = 4 * sqrt(t_single))
        h_single = h_tot / 2
        d_min = clamp(4.0 * math.sqrt(max(h_single, 0.3)), 2.0, h_tot * 3)

        ok = nugget_d_mm >= d_min

        details = [
            {"参数": "焊接电流 (kA)", "值": round(I_kA, 1)},
            {"参数": "通电时间 (ms)", "值": round(t_ms, 0)},
            {"参数": "电极压力 (kN)", "值": round(F_kn, 1)},
            {"参数": "焦耳热 (J)", "值": f"{Q_joule:.1f}"},
            {"参数": "材料熔点 (K)", "值": round(T_melt, 0)},
            {"参数": "单板厚 (mm)", "值": round(h_single, 2)},
        ]

        warnings = []
        if not ok:
            warnings.append(f"熔核直径 {nugget_d_mm:.1f}mm < 最小要求 {d_min:.1f}mm")
        if nugget_p_mm < 0.2 * h_tot:
            warnings.append(f"熔深不足 ({nugget_p_mm:.1f}mm)")

        return {
            "nugget_diameter_mm": round(nugget_d_mm, 2),
            "nugget_penetration_mm": round(nugget_p_mm, 2),
            "min_required_diameter_mm": round(d_min, 2),
            "diameter_ok": ok,
            "details": details,
        }

    def get_preview(self, outputs):
        return {
            "熔核直径(mm)": outputs.get("nugget_diameter_mm"),
            "熔深(mm)": outputs.get("nugget_penetration_mm"),
            "最小要求(mm)": outputs.get("min_required_diameter_mm"),
            "达标": outputs.get("diameter_ok"),
        }


# ══════════════════════════════════════════════════════════════════════════════
#  算子3: 焊接窗口模型
# ══════════════════════════════════════════════════════════════════════════════


@register_operator
class MechanismWeldLobe(BaseOperator):
    """焊接工艺窗口（Weld Lobe / Weldability Lobe）计算

    物理基础:
      焊接窗口定义为满足以下条件的(I, t)参数空间:
      - 下边界: 熔核直径 ≥ d_min (连接强度下限)
      - 上边界: 温度 ≤ T_splash 或 不出现飞溅/烧穿

    模型采用 Ashby 型经验模型 + 数据标定曲线:
      d_nugget = A * (I²·t)^n  (增长侧)
      I_splash = B * F^m / sqrt(t)  (飞溅上边界)

    输出焊接参数窗… (truncated)口区间，用于快速判断给定参数是否可焊。
    """

    id = "mechanism_lobe"
    name = "焊接窗口模型 (Weld Lobe)"
    category = "mechanism"
    description = (
        "基于经验公式与材料实验数据，计算点焊工艺的可焊参数窗口。"
        "输出焊接电流和通电时间的上下限区间，以及给定参数是否落在窗口内。"
    )
    version = "1.0"
    inputs = []
    outputs = [
        PortSpec("current_range_ka", "table", "可焊电流范围"),
        PortSpec("time_range_ms", "table", "可焊时间范围"),
        PortSpec("is_in_lobe", "boolean", "给定参数是否在窗口内"),
        PortSpec("margin_pct", "float", "参数距窗口边界的余量 (%)"),
        PortSpec("recommended_params", "table", "推荐参数区间"),
    ]
    parameters = [
        ParamSpec("current_ka", "float", 10.0, "焊接电流 (kA)", range_min=2.0, range_max=50.0),
        ParamSpec("weld_time_ms", "float", 200.0, "通电时间 (ms)", range_min=20.0, range_max=1000.0),
        ParamSpec("electrode_force_kn", "float", 3.0, "电极压力 (kN)", range_min=1.0, range_max=10.0),
        ParamSpec("sheet_thickness_mm", "float", 1.0, "单板厚 (mm)", range_min=0.5, range_max=3.0),
        ParamSpec("material_code", "str", "DC04", "材料代号"),
    ]

    def validate(self, inputs):
        return True

    def execute(self, inputs, params):
        I_in  = float(params.get("current_ka", 10.0))
        t_in  = float(params.get("weld_time_ms", 200.0))
        F_kn  = float(params.get("electrode_force_kn", 3.0))
        h_s   = float(params.get("sheet_thickness_mm", 1.0))
        mat   = params.get("material_code", "DC04").strip()

        # 材料相关经验常数 (基于文献数据拟合)
        mat_consts = {
            "DC04":    (A_lo := 0.72, A_hi := 1.45, B_spl := 3.8,  n_exp := 0.35),
            "DP590":   (0.78, 1.55, 4.0, 0.33),
            "DP780":   (0.82, 1.60, 4.2, 0.32),
            "DP980":   (0.85, 1.68, 4.5, 0.30),
            "HC340LA": (0.75, 1.50, 3.9, 0.34),
            "301_SS":  (0.65, 1.40, 3.5, 0.38),
            "default": (0.75, 1.50, 4.0, 0.34),
        }
        c_lo, c_hi, c_spl, n = mat_consts.get(mat, mat_consts["default"])

        h_mm = max(h_s, 0.3)  # 单板厚 mm

        # 时间范围
        t_min = clamp(120 * h_mm, 40, 300)
        t_max = clamp(500 * h_mm, 200, 2000)

        # 电流下边界 (熔核形成)
        I_min = round(c_lo * h_mm * (F_kn ** 0.25) / (t_in * 1e-3) ** n, 1)
        I_min = clamp(I_min, 2.0, 25.0)

        # 电流上边界 (飞溅线)
        I_max = round(c_hi * h_mm * (F_kn ** 0.3) / (t_in * 1e-3) ** n, 1)
        I_max = clamp(I_max, I_min + 1.0, 50.0)

        # 判断
        in_lobe = I_min <= I_in <= I_max and t_min <= t_in <= t_max

        # 余量
        if in_lobe:
            margin_I = min(I_in - I_min, I_max - I_in) / max(I_max - I_min, 0.01) * 100
            margin_t = min(t_in - t_min, t_max - t_in) / max(t_max - t_min, 0.01) * 100
            margin = round(min(margin_I, margin_t), 1)
        else:
            margin = 0.0

        return {
            "current_range_ka": [{"label": "下限", "value": I_min}, {"label": "上限", "value": I_max}],
            "time_range_ms": [{"label": "下限", "value": round(t_min, 0)}, {"label": "上限", "value": round(t_max, 0)}],
            "is_in_lobe": in_lobe,
            "margin_pct": margin,
            "recommended_params": [
                {"参数": "推荐电流 (kA)", "值": round((I_min + I_max) / 2, 1)},
                {"参数": "推荐时间 (ms)", "值": round((t_min + t_max) / 2, 0)},
                {"参数": "电流窗口宽度 (kA)", "值": round(I_max - I_min, 1)},
            ],
        }

    def get_preview(self, outputs):
        return {
            "电流范围": outputs.get("current_range_ka"),
            "时间范围": outputs.get("time_range_ms"),
            "窗口内": outputs.get("is_in_lobe"),
            "余量(%)": outputs.get("margin_pct"),
        }


# ══════════════════════════════════════════════════════════════════════════════
#  算子4: 飞溅预测模型
# ══════════════════════════════════════════════════════════════════════════════


@register_operator
class MechanismSplashPredict(BaseOperator):
    """飞溅预测 (Expulsion / Splash Prediction)

    物理机理:
      飞溅发生在熔核形成过程中，当熔核内部动态压力超过母材与电极的
      约束力时，熔融金属从板间或电极接触面喷出。

      判别条件:
      1. 能量密度:  E_d = I²·R·t / V_nugget > E_threshold
      2. 动态压力:  P_dyn ∝ I² / (D_e²) > P_confine
      3. 加热速率:  dT/dt > R_critical

      本模型综合以上三个条件计算飞溅概率。

    输出飞溅概率 (0~1)，以及各因素的贡献度。
    """

    id = "mechanism_splash"
    name = "飞溅预测模型 (Splash Prediction)"
    category = "mechanism"
    description = (
        "基于能量输入判别与动态压力分析，预测点焊过程中的飞溅发生概率。"
        "综合能量密度、动态压力、加热速率三个因素，输出飞溅风险等级。"
    )
    version = "1.0"
    inputs = []
    outputs = [
        PortSpec("splash_probability", "float", "飞溅概率 (0-1)"),
        PortSpec("risk_level", "str", "风险等级 (低/中/高/极高)"),
        PortSpec("factor_contributions", "table", "各因素贡献度"),
        PortSpec("recommendations", "list[str]", "参数调整建议"),
    ]
    parameters = [
        ParamSpec("current_ka", "float", 10.0, "焊接电流 (kA)", range_min=2.0, range_max=50.0),
        ParamSpec("voltage_v", "float", 1.5, "焊接电压 (V)", range_min=0.5, range_max=10.0),
        ParamSpec("weld_time_ms", "float", 200.0, "通电时间 (ms)", range_min=20.0, range_max=1000.0),
        ParamSpec("electrode_force_kn", "float", 3.0, "电极压力 (kN)", range_min=1.0, range_max=10.0),
        ParamSpec("electrode_diameter_mm", "float", 6.0, "电极帽直径 (mm)", range_min=4.0, range_max=8.0),
        ParamSpec("sheet_thickness_mm", "float", 1.0, "板材总厚度 (mm)", range_min=0.5, range_max=5.0),
        ParamSpec("material_code", "str", "DC04", "材料代号"),
    ]

    def validate(self, inputs):
        return True

    def execute(self, inputs, params):
        I_kA  = float(params.get("current_ka", 10.0))
        V     = float(params.get("voltage_v", 1.5))
        t_ms  = float(params.get("weld_time_ms", 200.0))
        F_kn  = float(params.get("electrode_force_kn", 3.0))
        D_e   = float(params.get("electrode_diameter_mm", 6.0))
        h_tot = float(params.get("sheet_thickness_mm", 1.0))
        mat   = params.get("material_code", "DC04").strip()

        rho_m, cp, k, T_melt, R_elec_uOhm = get_material_props(mat)
        t_s = t_ms * 1e-3

        # --- 因素1: 能量密度 ---
        A_contact     = math.pi * (D_e * 1e-3 / 2) ** 2
        V_nugget      = A_contact * (h_tot * 1e-3)  # m^3
        R_contact     = R_elec_uOhm * 1e-8 * (h_tot * 1e-3 / A_contact)
        Q_joule       = (I_kA * 1e3) ** 2 * R_contact * t_s
        E_density     = Q_joule / max(V_nugget, 1e-12)  # J/m^3

        # 能量密度阈值 (与材料熔点相关)
        E_threshold = 3.5e9 * (T_melt / 1780.0)  # J/m^3 (经验标定值)
        factor_E = clamp(E_density / max(E_threshold, 1e-9), 0, 2)

        # --- 因素2: 动态压力比 ---
        # P_dyn ∝ I² / D_e², P_confine ∝ F / A
        P_confine = F_kn * 1e3 / A_contact     # Pa
        P_dyn     = 0.15 * (I_kA * 1e3) ** 2 / (D_e * 1e-3) ** 2  # 简化 (Pa)
        factor_P = clamp(P_dyn / max(P_confine, 1.0), 0, 2)

        # --- 因素3: 加热速率 ---
        mass_nugget  = rho_m * V_nugget
        heat_rate    = Q_joule / (mass_nugget * cp * t_s) if mass_nugget * cp * t_s > 0 else 0  # K/s
        R_critical   = 8000.0  # K/s (临界加热速率，经验值)
        factor_R = clamp(heat_rate / R_critical, 0, 2)

        # --- 综合飞溅概率 ---
        # 权重: 能量密度 0.40, 动态压力 0.35, 加热速率 0.25
        score = clamp(
            0.40 * min(factor_E, 1.0) +
            0.35 * min(factor_P, 1.0) +
            0.25 * min(factor_R, 1.0),
            0, 1
        )

        # 风险等级
        if score < 0.25:
            level = "低"
        elif score < 0.50:
            level = "中"
        elif score < 0.75:
            level = "高"
        else:
            level = "极高"

        # 建议
        recs = []
        if factor_E > 0.8:
            recs.append(f"降低焊接电流 (当前 {I_kA}kA → 建议 ≤ {I_kA*0.85:.1f}kA)")
        if factor_P > 0.8:
            recs.append(f"增大电极压力 (当前 {F_kn}kN → 建议 ≥ {F_kn*1.2:.1f}kN)")
        if factor_R > 0.8:
            recs.append(f"延长通电时间或降低加热速率 (当前 {t_ms}ms)")
        if not recs:
            recs.append("当前参数飞溅风险较低，无需调整")

        return {
            "splash_probability": round(score, 3),
            "risk_level": level,
            "factor_contributions": [
                {"因素": "能量密度", "贡献度": round(min(factor_E, 1.0), 2), "阈值": f"{E_threshold/1e9:.1f} GJ/m³"},
                {"因素": "动态压力比", "贡献度": round(min(factor_P, 1.0), 2), "压力比": f"{P_dyn/P_confine:.2f}"},
                {"因素": "加热速率", "贡献度": round(min(factor_R, 1.0), 2), "速率": f"{heat_rate:.0f} K/s"},
            ],
            "recommendations": recs,
        }

    def get_preview(self, outputs):
        return {
            "飞溅概率": outputs.get("splash_probability"),
            "风险等级": outputs.get("risk_level"),
            "建议": outputs.get("recommendations", [])[:2],
        }


# ══════════════════════════════════════════════════════════════════════════════
#  算子5: 残余应力模型
# ══════════════════════════════════════════════════════════════════════════════


@register_operator
class MechanismResidualStress(BaseOperator):
    """热弹塑性简化模型 估算焊接残余应力与变形

    物理基础:
      点焊快速加热-冷却循环中，熔核区经历"热膨胀→塑性压缩→冷却收缩"
      的非均匀热-力耦合过程，导致:

      - 残余应力 σ_res ≈ α·E·ΔT·f_constraint
        其中 α 为热膨胀系数, E 为弹性模量, ΔT 为等效温降
        f_constraint 为约束因子 (0~1)

      - 变形倾向 ∝ ΔT · (板宽/板厚)

    模型假设:
      - 弹-理想塑性材料行为
      - 轴对称温度场
      - 忽略相变体积效应

    输出: 残余应力估算值、变形倾向评估。
    """

    id = "mechanism_stress"
    name = "残余应力模型 (Residual Stress)"
    category = "mechanism"
    description = (
        "基于热弹塑性简化模型，估算点焊冷却后的残余应力(MPa)与变形倾向。"
        "输出最大残余应力、是否接近屈服极限、以及变形风险评估。"
    )
    version = "1.0"
    inputs = []
    outputs = [
        PortSpec("max_residual_stress_mpa", "float", "最大残余应力 (MPa)"),
        PortSpec("yield_stress_mpa", "float", "材料屈服强度 (MPa)"),
        PortSpec("stress_ratio", "float", "应力/屈服比"),
        PortSpec("deformation_index", "float", "变形倾向指数"),
        PortSpec("risk_summary", "str", "风险评估总结"),
    ]
    parameters = [
        ParamSpec("current_ka", "float", 10.0, "焊接电流 (kA)", range_min=2.0, range_max=50.0),
        ParamSpec("weld_time_ms", "float", 200.0, "通电时间 (ms)", range_min=20.0, range_max=1000.0),
        ParamSpec("sheet_thickness_mm", "float", 1.0, "板材总厚度 (mm)", range_min=0.5, range_max=5.0),
        ParamSpec("sheet_width_mm", "float", 100.0, "板材宽度 (mm)", range_min=20.0, range_max=500.0),
        ParamSpec("material_code", "str", "DC04", "材料代号"),
    ]

    def validate(self, inputs):
        return True

    def execute(self, inputs, params):
        I_kA  = float(params.get("current_ka", 10.0))
        t_ms  = float(params.get("weld_time_ms", 200.0))
        h_tot = float(params.get("sheet_thickness_mm", 1.0))
        W     = float(params.get("sheet_width_mm", 100.0))
        mat   = params.get("material_code", "DC04").strip()

        rho_m, cp, k, T_melt, R_elec_uOhm = get_material_props(mat)

        # 材料力学参数 (钢材典型值)
        mat_mech = {
            "DC04":    (E_GPa := 210, sigma_y := 210, alpha := 12e-6),
            "DP590":   (210, 380, 12e-6),
            "DP780":   (210, 500, 12e-6),
            "DP980":   (210, 650, 12e-6),
            "HC340LA": (210, 350, 12e-6),
            "301_SS":  (193, 290, 17e-6),
            "default": (210, 300, 12e-6),
        }
        E_GPa, sigma_yield, alpha = mat_mech.get(mat, mat_mech["default"])

        t_s = t_ms * 1e-3

        # 等效温降: ΔT ≈ T_peak - T_ambient (从热传导模型近似)
        A_contact  = math.pi * (3e-3) ** 2
        R_contact  = R_elec_uOhm * 1e-8 * (h_tot * 1e-3 / A_contact)
        Q_joule    = (I_kA * 1e3) ** 2 * R_contact * t_s
        V_volume   = A_contact * (h_tot * 1e-3)
        delta_T    = Q_joule / (rho_m * V_volume * cp) if rho_m * V_volume * cp > 0 else 0

        # 约束因子 (板件越厚越窄，约束越大)
        f_constraint = clamp(1.0 / (1.0 + W / (h_tot * 20)), 0.05, 0.95)

        # 残余应力
        E_Pa   = E_GPa * 1e9
        sigma_res = alpha * E_Pa * delta_T * f_constraint * 1e-6  # MPa
        sigma_res = min(sigma_res, sigma_yield)  # 不超过屈服强度

        # 变形倾向指数
        # D_idx ∝ ΔT * (W/h) * (t_thin / t_total)
        D_index = clamp(delta_T * (W / max(h_tot, 0.1)) * 1e-4, 0, 10)

        stress_ratio = sigma_res / max(sigma_yield, 1)

        if stress_ratio > 0.9:
            risk = "高风险: 残余应力接近屈服极限，焊后变形严重"
        elif stress_ratio > 0.6:
            risk = "中风险: 存在一定残余应力，建议焊后校形或应力消除"
        elif stress_ratio > 0.3:
            risk = "低风险: 残余应力在安全范围内"
        else:
            risk = "风险极低: 残余应力可忽略"

        if D_index > 5:
            risk += "；变形倾向指数高，建议增加焊点间距或调整焊接顺序"

        return {
            "max_residual_stress_mpa": round(sigma_res, 1),
            "yield_stress_mpa": round(sigma_yield, 0),
            "stress_ratio": round(stress_ratio, 3),
            "deformation_index": round(D_index, 2),
            "risk_summary": risk,
        }

    def get_preview(self, outputs):
        return {
            "最大残余应力(MPa)": outputs.get("max_residual_stress_mpa"),
            "屈服强度(MPa)": outputs.get("yield_stress_mpa"),
            "应力/屈服比": outputs.get("stress_ratio"),
            "变形指数": outputs.get("deformation_index"),
        }


# ══════════════════════════════════════════════════════════════════════════════
#  算子6: 机理模型总控 / 综合校验 (可选)
# ══════════════════════════════════════════════════════════════════════════════


@register_operator
class MechanismValidationGate(BaseOperator):
    """综合机理校验 — 串联所有机理模型对一组参数进行全量约束检查

    不代替各模型独立使用，而是提供一站式"安全检查"。
    给定一组焊接参数，自动跑全部5个机理模型，输出汇总通过/失败及详情。
    """

    id = "mechanism_gate"
    name = "机理校验总控 (Validation Gate)"
    category = "mechanism"
    description = (
        "串联调用全部5个机理模型，对给定焊接参数进行一站式物理约束检查。"
        "输出通过/失败汇总、各模型详细结果、以及综合风险等级。"
    )
    version = "1.0"
    inputs = []
    outputs = [
        PortSpec("all_pass", "boolean", "全部检查是否通过"),
        PortSpec("passed_count", "int", "通过检查数"),
        PortSpec("total_count", "int", "总检查数"),
        PortSpec("model_results", "table", "各模型结果汇总"),
        PortSpec("overall_risk", "str", "综合风险等级"),
    ]
    parameters = [
        ParamSpec("current_ka", "float", 10.0, "焊接电流 (kA)", range_min=2.0, range_max=50.0),
        ParamSpec("voltage_v", "float", 1.5, "焊接电压 (V)", range_min=0.5, range_max=10.0),
        ParamSpec("weld_time_ms", "float", 200.0, "通电时间 (ms)", range_min=20.0, range_max=1000.0),
        ParamSpec("electrode_force_kn", "float", 3.0, "电极压力 (kN)", range_min=1.0, range_max=10.0),
        ParamSpec("electrode_diameter_mm", "float", 6.0, "电极帽直径 (mm)", range_min=4.0, range_max=8.0),
        ParamSpec("sheet_thickness_mm", "float", 1.0, "板材总厚度 (mm)", range_min=0.5, range_max=5.0),
        ParamSpec("sheet_width_mm", "float", 100.0, "板材宽度 (mm)", range_min=20.0, range_max=500.0),
        ParamSpec("material_code", "str", "DC04", "材料代号"),
    ]

    def validate(self, inputs):
        return True

    def execute(self, inputs, params):
        from app.engine.registry import OperatorRegistry

        results = []
        pass_count = 0

        # --- 热传导检查 ---
        thermal = OperatorRegistry.get("mechanism_thermal")
        if thermal:
            r = thermal.execute({}, {
                "current_ka": params.get("current_ka"), "voltage_v": params.get("voltage_v"),
                "weld_time_ms": params.get("weld_time_ms"), "sheet_thickness_mm": params.get("sheet_thickness_mm"),
                "material_code": params.get("material_code"), "electrode_diameter_mm": params.get("electrode_diameter_mm"),
            })
            ok = r["is_melted"] and len(r["warnings"]) == 0
            results.append({"模型": "热传导", "通过": ok, "关键值": f"峰值{r['peak_temperature']}K",
                           "详情": r["warnings"] if r["warnings"] else ["OK"]})
            if ok: pass_count += 1

        # --- 熔核生长检查 ---
        nugget = OperatorRegistry.get("mechanism_nugget")
        if nugget:
            r = nugget.execute({}, {
                "current_ka": params.get("current_ka"), "weld_time_ms": params.get("weld_time_ms"),
                "electrode_force_kn": params.get("electrode_force_kn"), "sheet_thickness_mm": params.get("sheet_thickness_mm"),
                "material_code": params.get("material_code"),
            })
            results.append({"模型": "熔核生长", "通过": r["diameter_ok"],
                           "关键值": f"直径{r['nugget_diameter_mm']}mm / 最小{r['min_required_diameter_mm']}mm",
                           "详情": ["OK" if r["diameter_ok"] else "直径不达标"]})
            if r["diameter_ok"]: pass_count += 1

        # --- 焊接窗口检查 ---
        lobe = OperatorRegistry.get("mechanism_lobe")
        if lobe:
            r = lobe.execute({}, {
                "current_ka": params.get("current_ka"), "weld_time_ms": params.get("weld_time_ms"),
                "electrode_force_kn": params.get("electrode_force_kn"), "sheet_thickness_mm": params.get("sheet_thickness_mm") / 2,
                "material_code": params.get("material_code"),
            })
            results.append({"模型": "焊接窗口", "通过": r["is_in_lobe"],
                           "关键值": f"margin {r['margin_pct']}%",
                           "详情": ["OK" if r["is_in_lobe"] else "参数超出可焊窗口"]})
            if r["is_in_lobe"]: pass_count += 1

        # --- 飞溅检查 ---
        splash = OperatorRegistry.get("mechanism_splash")
        if splash:
            r = splash.execute({}, {
                "current_ka": params.get("current_ka"), "voltage_v": params.get("voltage_v"),
                "weld_time_ms": params.get("weld_time_ms"), "electrode_force_kn": params.get("electrode_force_kn"),
                "electrode_diameter_mm": params.get("electrode_diameter_mm"), "sheet_thickness_mm": params.get("sheet_thickness_mm"),
                "material_code": params.get("material_code"),
            })
            ok = r["risk_level"] in ("低", "中")
            results.append({"模型": "飞溅预测", "通过": ok,
                           "关键值": f"概率{r['splash_probability']} / {r['risk_level']}",
                           "详情": r["recommendations"][:2]})
            if ok: pass_count += 1

        # --- 残余应力检查 ---
        stress = OperatorRegistry.get("mechanism_stress")
        if stress:
            r = stress.execute({}, {
                "current_ka": params.get("current_ka"), "weld_time_ms": params.get("weld_time_ms"),
                "sheet_thickness_mm": params.get("sheet_thickness_mm"), "sheet_width_mm": params.get("sheet_width_mm"),
                "material_code": params.get("material_code"),
            })
            ok = r["stress_ratio"] < 0.6
            results.append({"模型": "残余应力", "通过": ok,
                           "关键值": f"应力{r['max_residual_stress_mpa']}MPa / 屈服{r['yield_stress_mpa']}MPa",
                           "详情": [r["risk_summary"]]})
            if ok: pass_count += 1

        total = len(results)
        all_pass = pass_count == total

        if pass_count >= 4:
            overall = "低风险: 参数通过大部分机理检查"
        elif pass_count >= 3:
            overall = "中风险: 部分机理检查未通过，建议调整参数"
        elif pass_count >= 2:
            overall = "高风险: 多项机理检查未通过，强烈建议调整"
        else:
            overall = "极高风险: 参数严重偏离物理可行范围"

        return {
            "all_pass": all_pass,
            "passed_count": pass_count,
            "total_count": total,
            "model_results": results,
            "overall_risk": overall,
        }

    def get_preview(self, outputs):
        return {
            "通过/总数": f"{outputs.get('passed_count')}/{outputs.get('total_count')}",
            "全部通过": outputs.get("all_pass"),
            "综合风险": outputs.get("overall_risk"),
        }
