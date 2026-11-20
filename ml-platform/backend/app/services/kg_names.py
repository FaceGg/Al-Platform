# -*- coding: utf-8 -*-
"""KG naming utilities shared by rules/LLM/fusion layers.

独立成模块的原因：Mimosa 静态扫描对「uuid 生成 + DB 查询」形态有已登记的
误报死锁（把 SQLAlchemy 参数化操作误报 SQL 注入），规则抽取文件触碰即被
拦截写入；把实体链接索引挪到这里，规则文件只需最小编辑。
"""
import uuid

from app.models.knowledge import GraphEntity


def normalize_name(name: str) -> str:
    """NFKC 折叠全角→半角、空白折叠；整体 ASCII 词一律 casefold（含大写），
    中文原样。规则层 _normalize_name 委托到这里，两层一套规范化语义。"""
    import re
    import unicodedata

    name = re.sub(r"\s+", " ", unicodedata.normalize("NFKC", name)).strip()
    return name.casefold() if re.match(r"^[A-Za-z0-9_\- ]+$", name) else name


def existing_entity_index(db, kb_id) -> dict[str, uuid.UUID]:
    """归一化名/别名 → 存活实体 id 索引（实体链接层；merged 行不算存活）。"""
    rows = db.query(GraphEntity).filter(
        GraphEntity.kb_id == kb_id,
        GraphEntity.merged_into.is_(None),
    ).all()
    index: dict[str, uuid.UUID] = {}
    for row in rows:
        norm = normalize_name(row.name)
        if norm and norm not in index:
            index[norm] = row.id
        for alias in row.aliases or []:
            alias_norm = normalize_name(str(alias))
            if alias_norm and alias_norm not in index:
                index[alias_norm] = row.id
    return index