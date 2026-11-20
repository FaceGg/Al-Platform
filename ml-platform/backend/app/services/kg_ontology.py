# -*- coding: utf-8 -*-
"""Knowledge-graph ontology: entity/relation type vocabulary per knowledge base.

LLM 抽取与融合仲裁的类型约束都来自这里。默认是一套工业领域本体（点焊语料
友好），每个知识库可通过 ``KnowledgeBase.kg_ontology`` 覆盖；空值/损坏值
一律回退默认，保证抽取永不因本体配置失败而失败。
"""
from typing import Any

DEFAULT_ONTOLOGY: dict[str, list[str]] = {
    "entity_types": [
        "工艺", "缺陷", "设备", "材料", "指标", "标准", "部件", "组织", "人员", "概念",
    ],
    "relation_types": [
        "用于工艺", "导致缺陷", "属于设备", "包含部件", "依据标准",
        "参数为", "前置工序", "后置工序", "相关",
    ],
}

# 本体里兜底类型：LLM 输出映射不到词表时落到这两个（保证关系仍然可建）
FALLBACK_ENTITY_TYPE = "概念"
FALLBACK_RELATION_TYPE = "相关"

MAX_ENTITY_TYPES = 32
MAX_RELATION_TYPES = 32
MAX_TYPE_LEN = 32


def resolve_ontology(kb) -> dict[str, list[str]]:
    """Validated per-KB ontology; falls back to the default on any problem."""
    raw = getattr(kb, "kg_ontology", None)
    if not isinstance(raw, dict):
        return {"entity_types": list(DEFAULT_ONTOLOGY["entity_types"]),
                "relation_types": list(DEFAULT_ONTOLOGY["relation_types"])}
    merged = {
        "entity_types": list(DEFAULT_ONTOLOGY["entity_types"]),
        "relation_types": list(DEFAULT_ONTOLOGY["relation_types"]),
    }
    for key in ("entity_types", "relation_types"):
        items = raw.get(key)
        if isinstance(items, list) and items:
            merged[key] = _clean_types(items)
    return merged


def normalize_ontology(payload: Any) -> dict[str, list[str]]:
    """Validate a user-submitted ontology payload; raises ValueError on junk."""
    if not isinstance(payload, dict):
        raise ValueError("kg_ontology must be an object with entity_types/relation_types")
    merged: dict[str, list[str]] = {}
    for key in ("entity_types", "relation_types"):
        items = payload.get(key)
        if not isinstance(items, list) or not items:
            raise ValueError(f"{key} must be a non-empty list")
        cleaned = _clean_types(items)
        if not cleaned:
            raise ValueError(f"{key} has no usable entries")
        merged[key] = cleaned
    return merged


def _clean_types(items: list[Any]) -> list[str]:
    cleaned: list[str] = []
    for item in items:
        if not isinstance(item, str):
            continue
        value = item.strip()
        if not value or len(value) > MAX_TYPE_LEN:
            continue
        if value not in cleaned:
            cleaned.append(value)
        if len(cleaned) >= MAX_ENTITY_TYPES:
            break
    return cleaned


def coerce_entity_type(entity_type: str, ontology: dict[str, list[str]]) -> str:
    value = (entity_type or "").strip()
    if value in ontology["entity_types"]:
        return value
    return FALLBACK_ENTITY_TYPE


def coerce_relation_type(relation_type: str, ontology: dict[str, list[str]]) -> str:
    value = (relation_type or "").strip()
    if value in ontology["relation_types"]:
        return value
    return FALLBACK_RELATION_TYPE
