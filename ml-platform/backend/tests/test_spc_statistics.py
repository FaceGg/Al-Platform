"""补齐路线第一批 F4：SPC 纯函数统计库（B1-06，技术方案 §9C）。

口径用手算向量锁死（诚实设计②）：Cp / Cpk 用组内 σ、Pp / Ppk 用整体 σ；
Nelson 规则 1–8 每条各有单测；缺规格限时能力指数留空不报错。

关于「竞品同口径数据复算」：路线文档要求用竞品的 106,504 行数据（取最新 5,000、
5 样本/组）做回归，但该数据集没有随简报提供，本环境无法复算——登记为环境阻塞项，
口径正确性以下列手算向量为准。
"""
import math
import unittest

from app.services import spc_statistics as spc


class TestConstants(unittest.TestCase):
    def test_control_chart_constants_match_standard_table(self):
        # I-MR 与基线冻结共用 d2(2) = 1.128
        self.assertAlmostEqual(spc.CONSTANTS[2]["d2"], 1.128)
        # A2 = 3 / (d2 · √n)：X̄ ± A2·R̄ 与 3σ/√n 是同一回事；表值只保留三位小数，
        # 所以按舍入精度比较（容差 0.002），不能要求三位小数严格相等
        for size, constants in spc.CONSTANTS.items():
            self.assertLess(
                abs(constants["A2"] - 3.0 / (constants["d2"] * math.sqrt(size))), 0.002, msg=size,
            )


class TestIMrChart(unittest.TestCase):
    def test_limits_and_outlier(self):
        values = [10, 12, 9, 11, 10, 50]
        result = spc.i_mr_chart(values)
        # 均值 17；移动极差 2,3,2,1,40 → 均值 9.6；σ = 9.6 / 1.128
        individuals = result["i"]
        self.assertAlmostEqual(individuals.limits.center, 17.0)
        self.assertAlmostEqual(individuals.limits.sigma, 9.6 / 1.128, places=9)
        self.assertAlmostEqual(individuals.limits.ucl, 17.0 + 3 * 9.6 / 1.128, places=9)
        self.assertEqual([point.violations for point in individuals.points],
                         [[], [], [], [], [], [1]])
        self.assertEqual(individuals.in_control_count, 5)
        self.assertAlmostEqual(individuals.in_control_rate, 5 / 6)
        # 移动极差图：UCL = D4(2) × MRbar = 3.267 × 9.6，最后一个点越限
        moving = result["mr"]
        self.assertAlmostEqual(moving.limits.ucl, 3.267 * 9.6, places=9)
        self.assertEqual([item["index"] for item in moving.violations], [4])

    def test_needs_at_least_two_points(self):
        with self.assertRaises(spc.SpcError):
            spc.i_mr_chart([10])


class TestSubgroupCharts(unittest.TestCase):
    def test_xbar_r_limits_equal_a2_rbar(self):
        subgroups = [[10, 12], [9, 11], [11, 13], [10, 12], [20, 22]]
        charts = spc.subgroup_charts(subgroups)
        xbar = charts["xbar"]
        # 均值 11, 10, 12, 11, 21 → 中心 13；极差全是 2 → Rbar 2；X̄ ± A2·Rbar = 13 ± 3.76
        self.assertAlmostEqual(xbar.limits.center, 13.0)
        self.assertAlmostEqual(xbar.limits.ucl, 13.0 + 1.880 * 2, places=9)
        self.assertAlmostEqual(xbar.limits.lcl, 13.0 - 1.880 * 2, places=9)
        self.assertEqual([point.index for point in xbar.points if point.violations], [4])
        self.assertEqual(charts["r"].kind, "r")
        self.assertAlmostEqual(charts["r"].limits.ucl, 3.267 * 2, places=9)
        self.assertAlmostEqual(charts["r"].limits.lcl, 0.0)

    def test_xbar_s_chart_uses_c4_and_b_constants(self):
        subgroups = [[10, 12, 11], [9, 11, 10], [11, 13, 12]]
        charts = spc.subgroup_charts(subgroups, chart="xbar_s")
        s_chart = charts["s"]
        s_bar = spc._mean([spc.sample_std(group) for group in subgroups])
        self.assertAlmostEqual(s_chart.limits.center, s_bar, places=9)
        self.assertAlmostEqual(s_chart.limits.ucl, spc.CONSTANTS[3]["B4"] * s_bar, places=9)
        self.assertAlmostEqual(
            charts["xbar"].limits.ucl,
            11.0 + spc.CONSTANTS[3]["A3"] * s_bar, places=9,
        )

    def test_subgroup_size_out_of_range_is_rejected(self):
        with self.assertRaises(spc.SpcError):
            spc.subgroup_charts([[1.0] * 11])
        with self.assertRaises(spc.SpcError):
            spc.subgroup_charts([[1.0, 2.0], [1.0, 2.0, 3.0]])


class TestNelsonRules(unittest.TestCase):
    """每条规则用「只命中这一条」的序列验证（中心 0，σ 1）。"""

    def hits(self, values, at=None):
        return spc.nelson_rules(values, 0.0, 1.0, at=at)

    def test_rule_1_one_point_beyond_3_sigma(self):
        self.assertEqual(self.hits([0.1, 0.2, 3.5], at=2), [1])
        self.assertEqual(self.hits([0.1, 0.2, 2.5], at=2), [])

    def test_rule_2_nine_points_on_one_side(self):
        values = [0.5] * 9
        self.assertEqual(self.hits(values, at=8), [2])
        self.assertEqual(self.hits(values, at=7), [])

    def test_rule_3_six_monotonic_points(self):
        self.assertEqual(self.hits([0.1, 0.2, 0.3, 0.4, 0.5, 0.6], at=5), [3])
        self.assertEqual(self.hits([-0.1, -0.2, -0.3, -0.4, -0.5, -0.6], at=5), [3])

    def test_rule_4_fourteen_alternating_points(self):
        values = [0.5 if index % 2 == 0 else -0.5 for index in range(14)]
        self.assertIn(4, self.hits(values, at=13))
        self.assertNotIn(3, self.hits(values, at=13))

    def test_rule_5_two_of_three_beyond_2_sigma(self):
        self.assertEqual(self.hits([0.0, 2.5, -0.2, 2.2], at=3), [5])
        self.assertEqual(self.hits([0.0, 2.5, -0.2, 1.2], at=3), [])

    def test_rule_6_four_of_five_beyond_1_sigma(self):
        self.assertEqual(self.hits([0.0, 1.5, 1.2, 0.2, 1.4, 1.3], at=5), [6])

    def test_rule_7_fifteen_points_within_1_sigma(self):
        values = [0.5 if index % 2 == 0 else -0.5 for index in range(15)]
        self.assertIn(7, self.hits(values, at=14))

    def test_rule_8_eight_points_none_within_1_sigma(self):
        # 两侧混合且最后 5 个点里同侧超出 1σ 的不足 4 个：只命中规则 8
        values = [1.5, -1.5, 1.5, -1.5, 1.5, 1.5, 1.5, -1.5]
        self.assertEqual(self.hits(values, at=7), [8])

    def test_whole_series_returns_union_and_zero_sigma_judges_nothing(self):
        self.assertEqual(self.hits([0.5] * 9 + [3.5]), [1, 2])
        self.assertEqual(spc.nelson_rules([5.0, 5.0, 5.0], 5.0, 0.0), [])

    def test_rules_can_be_switched_off(self):
        self.assertEqual(spc.nelson_rules([0.5] * 9, 0.0, 1.0, at=8, rules=(1,)), [])


class TestCapability(unittest.TestCase):
    VALUES = [8, 10, 12, 11, 9]  # 均值 10，整体样本标准差 √2.5

    def test_indices_with_frozen_baseline_sigma(self):
        result = spc.capability(self.VALUES, usl=16, lsl=4, target=10, baseline_sigma=1.0)
        self.assertEqual(result.within_sigma_source, "baseline")
        self.assertAlmostEqual(result.cp, 2.0)
        self.assertAlmostEqual(result.cpk, 2.0)
        self.assertAlmostEqual(result.cpm, 2.0)
        self.assertAlmostEqual(result.cr, 0.5)
        self.assertAlmostEqual(result.pp, 12 / (6 * math.sqrt(2.5)), places=9)
        self.assertAlmostEqual(result.ppk, 6 / (3 * math.sqrt(2.5)), places=9)
        self.assertAlmostEqual(result.sigma_level, 6 / math.sqrt(2.5), places=9)
        # 两侧各 3.795σ 的尾部 → 约百万分之 150
        self.assertTrue(100 < result.ppm < 200, result.ppm)

    def test_within_sigma_from_subgroup_ranges(self):
        result = spc.capability(self.VALUES, usl=16, lsl=4, subgroups=[[8, 10], [12, 11], [9, 10.5]])
        self.assertEqual(result.within_sigma_source, "range")
        # 极差 2, 1, 1.5 → Rbar 1.5；σ = 1.5 / 1.128
        self.assertAlmostEqual(result.cp, 12 / (6 * 1.5 / 1.128), places=9)

    def test_falls_back_to_overall_sigma_and_says_so(self):
        result = spc.capability(self.VALUES, usl=16, lsl=4)
        self.assertEqual(result.within_sigma_source, "overall")
        self.assertAlmostEqual(result.cp, result.pp, places=12)

    def test_missing_spec_limits_leave_indices_blank(self):
        result = spc.capability(self.VALUES)
        for name in ("cp", "cpk", "pp", "ppk", "cpm", "cr", "sigma_level", "ppm"):
            self.assertIsNone(getattr(result, name), name)
        self.assertEqual(result.count, 5)

    def test_one_sided_spec_gives_only_cpk(self):
        result = spc.capability(self.VALUES, usl=16, baseline_sigma=1.0)
        self.assertIsNone(result.cp)
        self.assertIsNone(result.cpm)
        self.assertAlmostEqual(result.cpk, 2.0)


class TestHistogramAndAttributeCharts(unittest.TestCase):
    def test_histogram_edges_and_counts(self):
        self.assertEqual(spc.histogram([1, 2, 3, 4], bins=2), {"edges": [1, 2.5, 4], "counts": [2, 2]})
        self.assertEqual(spc.histogram([], bins=3), {"edges": [], "counts": []})
        single = spc.histogram([7, 7], bins=4)
        self.assertEqual(sum(single["counts"]), 2)

    def test_p_chart_flags_a_point_above_three_sigma(self):
        chart = spc.attribute_chart("p", [2, 12, 1], [100, 100, 100])
        p_bar = 15 / 300
        self.assertAlmostEqual(chart.limits.center, p_bar, places=12)
        self.assertAlmostEqual(chart.points[1].ucl, p_bar + 3 * math.sqrt(p_bar * (1 - p_bar) / 100), places=12)
        self.assertEqual([item["index"] for item in chart.violations], [1])
        self.assertEqual(chart.in_control_count, 2)

    def test_np_c_u_charts(self):
        np_chart = spc.attribute_chart("np", [2, 12, 1], [100, 100, 100])
        self.assertEqual([item["index"] for item in np_chart.violations], [1])
        c_chart = spc.attribute_chart("c", [4, 5, 3, 20, 4])
        self.assertAlmostEqual(c_chart.limits.center, 7.2)
        self.assertAlmostEqual(c_chart.limits.ucl, 7.2 + 3 * math.sqrt(7.2), places=9)
        self.assertEqual([item["index"] for item in c_chart.violations], [3])
        u_chart = spc.attribute_chart("u", [3, 25, 2], [10, 10, 5])
        # 单位缺陷数 0.3, 2.5, 0.4；u_bar = 30 / 25；第二点超出 3σ 上限
        self.assertAlmostEqual(u_chart.limits.center, 30 / 25, places=12)
        self.assertEqual([item["index"] for item in u_chart.violations], [1])
        self.assertTrue(u_chart.notes, "样本量不一致时应提示控制限逐点变化")

    def test_invalid_inputs_are_rejected(self):
        with self.assertRaises(spc.SpcError):
            spc.attribute_chart("x", [1, 2])
        with self.assertRaises(spc.SpcError):
            spc.attribute_chart("p", [1, 2], [10])
        with self.assertRaises(spc.SpcError):
            spc.attribute_chart("c", [1, 2], [0, 10])


if __name__ == "__main__":
    unittest.main()
