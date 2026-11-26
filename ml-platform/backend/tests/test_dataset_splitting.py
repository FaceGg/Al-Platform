"""S2a 划分管理（B2-G1）：三策略出角色、同种子重放指纹一致、角色过滤、不可变 API 面。

验收口径（技术方案 §6.7）：同一种子重放划分一致（指纹一致）；
development/blind 互斥且并集=全集；训练接线按 development 行过滤、blind 永不进。
"""
import unittest
import uuid

import numpy as np
import pandas as pd

from app.services.dataset_splitting import (
    SplitError,
    assign_roles,
    filter_frame_by_roles,
    fingerprint_split,
)


def _frame(rows: int = 200, groups: int = 8) -> pd.DataFrame:
    rng = np.random.RandomState(7)
    return pd.DataFrame({
        "feature_a": rng.normal(size=rows),
        "target": (rng.random(rows) > 0.7).astype(int),
        "group_col": [f"g{i % groups}" for i in range(rows)],
        "time_col": pd.date_range("2026-01-01", periods=rows, freq="h").astype(str),
        "sample_key": [f"sk-{i}" for i in range(rows)],
    })


class TestAssignRoles(unittest.TestCase):
    def test_random_stratified_respects_class_minimums(self):
        frame = _frame()
        roles = assign_roles(
            frame, strategy="random_stratified",
            params={"test_size": 0.2, "seed": 42},
            target_column="target", sample_key_column="sample_key",
        )
        blind = [r for r in roles if r[1] == "blind"]
        dev = [r for r in roles if r[1] == "development"]
        self.assertEqual(len(roles), len(frame))
        self.assertEqual(len(blind) + len(dev), len(frame))
        # 分层：少数类（1）在盲测中也要有代表
        blind_keys = {r[2] for r in blind}
        blind_targets = set(frame.loc[frame["sample_key"].isin(blind_keys), "target"])
        self.assertEqual(blind_targets, {0, 1})

    def test_same_seed_replays_same_split_and_fingerprint(self):
        params = {"test_size": 0.2, "seed": 42, "target_column": "target",
                  "sample_key_column": "sample_key"}
        roles_a = assign_roles(_frame(), strategy="random_stratified", params=params)
        roles_b = assign_roles(_frame(), strategy="random_stratified", params=params)
        self.assertEqual(roles_a, roles_b)
        fp_a = fingerprint_split(dataset_version_id="v-1", strategy="random_stratified",
                                 params=params, roles=roles_a)
        fp_b = fingerprint_split(dataset_version_id="v-1", strategy="random_stratified",
                                 params=params, roles=roles_b)
        self.assertEqual(fp_a, fp_b)

    def test_group_strategy_keeps_groups_whole(self):
        frame = _frame()
        roles = assign_roles(
            frame, strategy="group",
            params={"test_size": 0.2, "seed": 42, "group_column": "group_col"},
        )
        blind_rows = [r[0] for r in roles if r[1] == "blind"]
        blind_groups = set(frame.iloc[blind_rows]["group_col"])
        dev_rows = [r[0] for r in roles if r[1] == "development"]
        dev_groups = set(frame.iloc[dev_rows]["group_col"])
        self.assertFalse(blind_groups & dev_groups, "组必须整组分配，不跨角色")

    def test_temporal_holds_out_the_tail(self):
        frame = _frame()
        roles = assign_roles(
            frame, strategy="temporal",
            params={"test_size": 0.2, "seed": 42, "time_column": "time_col"},
        )
        blind_rows = sorted(r[0] for r in roles if r[1] == "blind")
        expected_tail = set(range(len(frame) - 40, len(frame)))
        self.assertEqual(set(blind_rows), expected_tail, "时间留出=最新尾部")

    def test_invalid_inputs_raise(self):
        with self.assertRaises(SplitError):
            assign_roles(_frame(), strategy="unknown", params={})
        with self.assertRaises(SplitError):
            assign_roles(_frame(), strategy="group", params={})
        with self.assertRaises(SplitError):
            assign_roles(_frame().iloc[0:0], strategy="random_stratified", params={})


class TestRoleFiltering(unittest.TestCase):
    def test_filter_development_and_blind_partition_the_frame(self):
        frame = _frame(50)
        roles = assign_roles(
            frame, strategy="random_stratified",
            params={"test_size": 0.2, "seed": 42, "sample_key_column": "sample_key"},
        )
        role_map = {"development": [], "blind": []}
        for row_index, role, _key in roles:
            role_map[role].append(row_index)
        dev = filter_frame_by_roles(frame, role_map, "development")
        blind = filter_frame_by_roles(frame, role_map, "blind")
        self.assertEqual(len(dev) + len(blind), len(frame))
        seen = set()
        for part in (dev, blind):
            for key in part["sample_key"]:
                self.assertNotIn(key, seen, "角色间样本互斥")
                seen.add(key)

    def test_empty_role_raises(self):
        frame = _frame(10)
        with self.assertRaises(SplitError):
            filter_frame_by_roles(frame, {"development": list(range(10)), "blind": []}, "blind")


if __name__ == "__main__":
    unittest.main()
