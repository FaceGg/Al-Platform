"""Dataset split management (补齐路线第二批 S2a, B2-G1/E04).

三策略出角色：random_stratified（镜像 sklearn train_test_split 语义）、
group（按组列整组分配）、temporal（按时间列排序尾部留出）。同种子重放
得到相同划分（指纹一致）；成员创建后不可变（无更新端点）。
兼容红线：本服务只在显式使用时参与训练；引擎默认路径零变化。
"""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime
from typing import Sequence

import numpy as np
import pandas as pd
from sqlalchemy.orm import Session

from app.models.dataset_splitting import (
    SPLIT_STRATEGIES,
    DatasetSplit,
    DatasetSplitMember,
)

# 默认盲测占比（与引擎默认 holdout 20% 同量级；可按 params.test_size 覆盖）
DEFAULT_BLIND_SIZE = 0.2
_DEFAULT_SEED = 42
_CHUNK = 5000


class SplitError(Exception):
    def __init__(self, code: str, message: str | None = None):
        super().__init__(message or code)
        self.code = code
        self.message = message or code


def fingerprint_split(
    *,
    dataset_version_id,
    strategy: str,
    params: dict,
    roles: Sequence[tuple[int, str, str | None]],
) -> str:
    """划分指纹：版本+策略+参数+角色行数+样本键有序摘要（同种子重放一致）。"""
    keys = sorted(str(item[2]) for item in roles if item[2] is not None)
    payload = {
        "dataset_version_id": str(dataset_version_id),
        "strategy": strategy,
        "params": dict(params or {}),
        "counts": {
            "development": sum(1 for item in roles if item[1] == "development"),
            "blind": sum(1 for item in roles if item[1] == "blind"),
        },
        "sample_keys_sha256": hashlib.sha256(
            "\n".join(keys).encode("utf-8")
        ).hexdigest() if keys else None,
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str).encode(
            "utf-8"
        )
    ).hexdigest()


def assign_roles(
    frame: pd.DataFrame,
    *,
    strategy: str,
    params: dict,
    target_column: str | None = None,
    sample_key_column: str | None = None,
) -> list[tuple[int, str, str | None]]:
    """按策略给每行分配角色（development/blind），返回 [(row_index, role, sample_key)]。"""
    if strategy not in SPLIT_STRATEGIES:
        raise SplitError("SPLIT_STRATEGY_INVALID")
    total = len(frame)
    if total == 0:
        raise SplitError("SPLIT_EMPTY_FRAME")
    test_size = float(params.get("test_size") or DEFAULT_BLIND_SIZE)
    if not 0.0 < test_size < 1.0:
        raise SplitError("SPLIT_TEST_SIZE_INVALID")
    seed = int(params.get("seed") or _DEFAULT_SEED)
    blind_count = max(1, int(round(total * test_size)))

    rng = np.random.RandomState(seed)
    roles = np.array(["development"] * total, dtype=object)

    if strategy == "random_stratified":
        labels = None
        if target_column:
            target = frame[target_column]
            class_counts = target.value_counts()
            if target_column in frame.columns and (class_counts > 1).all() and class_counts.min() >= 2:
                labels = target.to_numpy()
        if labels is not None:
            # 分层留出：每类按比例抽盲测（最小类至少 1 行）
            blind_indices: list[int] = []
            for label in np.unique(labels):
                class_rows = np.flatnonzero(labels == label)
                take = max(1, int(round(len(class_rows) * test_size)))
                chosen = rng.choice(class_rows, size=take, replace=False)
                blind_indices.extend(chosen.tolist())
            roles[sorted(set(blind_indices))] = "blind"
        else:
            roles[rng.choice(total, size=blind_count, replace=False)] = "blind"
    elif strategy == "group":
        group_column = params.get("group_column")
        if not group_column or group_column not in frame.columns:
            raise SplitError("SPLIT_GROUP_COLUMN_REQUIRED")
        groups = list(pd.unique(frame[group_column]))
        rng.shuffle(groups)
        sizes = frame.groupby(group_column, sort=False).size()
        taken = 0
        for group in groups:
            roles[np.flatnonzero((frame[group_column] == group).to_numpy())] = "blind"
            taken += int(sizes.get(group, 0))
            if taken >= blind_count:
                break
    else:  # temporal
        time_column = params.get("time_column")
        if not time_column or time_column not in frame.columns:
            raise SplitError("SPLIT_TIME_COLUMN_REQUIRED")
        ordered = frame[time_column].sort_values(na_position="first").index
        blind_rows = list(ordered[-blind_count:])
        roles[blind_rows] = "blind"

    sample_keys: Sequence[str | None]
    if sample_key_column and sample_key_column in frame.columns:
        sample_keys = frame[sample_key_column].astype(str).tolist()
    else:
        sample_keys = [None] * total
    return [(index, str(roles[index]), sample_keys[index]) for index in range(total)]


def create_split(
    db: Session,
    *,
    project_id,
    dataset_version_id,
    name: str,
    strategy: str,
    params: dict | None,
    frame: pd.DataFrame,
    created_by_id=None,
) -> DatasetSplit:
    """创建划分（成员持久化、指纹计算）；E04：创建后不可变（无更新路径）。"""
    params = dict(params or {})
    roles = assign_roles(
        frame, strategy=strategy, params=params,
        target_column=params.get("target_column"),
        sample_key_column=params.get("sample_key_column"),
    )
    fingerprint = fingerprint_split(
        dataset_version_id=dataset_version_id, strategy=strategy,
        params=params, roles=roles,
    )
    split = DatasetSplit(
        project_id=project_id,
        dataset_version_id=dataset_version_id,
        name=(name or strategy)[:128],
        strategy=strategy,
        params=params,
        split_fingerprint=fingerprint,
        created_by_id=created_by_id,
    )
    db.add(split)
    db.flush()
    members = [
        DatasetSplitMember(
            split_id=split.id,
            row_index=row_index,
            sample_key=sample_key[:256] if sample_key else None,
            role=role,
        )
        for row_index, role, sample_key in roles
    ]
    for start in range(0, len(members), _CHUNK):
        db.bulk_save_objects(members[start:start + _CHUNK])
    db.flush()
    return split


def load_role_indices(db: Session, split_id) -> dict[str, list[int]]:
    """读划分的角色行号（训练接线与摘要用）。"""
    rows = (
        db.query(DatasetSplitMember.row_index, DatasetSplitMember.role)
        .filter(DatasetSplitMember.split_id == split_id)
        .all()
    )
    roles: dict[str, list[int]] = {"development": [], "blind": []}
    for row_index, role in rows:
        roles.setdefault(role, []).append(int(row_index))
    for role in roles:
        roles[role].sort()
    return roles


def filter_frame_by_roles(
    frame: pd.DataFrame, roles: dict[str, list[int]], role: str
) -> pd.DataFrame:
    """按角色行号过滤 frame（训练接线：development 进训练、blind 永不进）。"""
    indices = sorted(set(roles.get(role) or []))
    if not indices:
        raise SplitError("SPLIT_ROLE_EMPTY")
    return frame.iloc[indices].reset_index(drop=True)
