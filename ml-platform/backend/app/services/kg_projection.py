# -*- coding: utf-8 -*-
"""Neo4j graph-storage projection (five-stage pipeline, stage 4).

定位：PostgreSQL 是事务主源，Neo4j 是图查询/应用层的投影镜像。抽取/融合本就
是成批重建，全量重投影幂等（MERGE by entityId），避免双写一致性黑洞。

可用性契约：neo4j 驱动未安装、NEO4J_URI 未配置或连接失败 → available()=False，
图查询端点自动走 PG 兜底（功能不缺、只慢）；投影/查询失败永不阻断主链路。
"""
import logging
import threading
import uuid

from app.config import settings

logger = logging.getLogger(__name__)

_LOCK = threading.Lock()
_SINGLETON: "KgProjection | None" = None

_MAX_BATCH = 1000


class KgProjectionUnavailable(Exception):
    pass


def get_projection() -> "KgProjection":
    global _SINGLETON
    with _LOCK:
        if _SINGLETON is None:
            _SINGLETON = KgProjection()
        return _SINGLETON


def reset_projection() -> None:
    """测试注入 fake 驱动用。"""
    global _SINGLETON
    with _LOCK:
        _SINGLETON = None


class KgProjection:
    """Neo4j 投影器：driver 惰性建连；全部操作参数化 Cypher（无字符串拼接）。"""

    def __init__(self, driver_factory=None):
        self._driver_factory = driver_factory
        self._driver = None
        self._checked = False

    # ------------------------------------------------------------ 连接管理

    def _get_driver(self):
        if self._driver is not None:
            return self._driver
        if self._driver_factory is None and not settings.neo4j_uri:
            raise KgProjectionUnavailable("NEO4J_URI not configured")
        try:
            if self._driver_factory is not None:
                self._driver = self._driver_factory()
            else:
                from neo4j import GraphDatabase  # 延迟导入：驱动缺失不炸其它功能

                self._driver = GraphDatabase.driver(
                    settings.neo4j_uri,
                    auth=(settings.neo4j_user,
                          (settings.neo4j_password.get_secret_value()
                           if settings.neo4j_password else "")),
                    connection_timeout=3,
                    max_connection_pool_size=10,
                )
                self._driver.verify_connectivity()
                self._ensure_schema()
                return self._driver
        except KgProjectionUnavailable:
            raise
        except Exception as error:  # noqa: BLE001 - 网络失败按不可用降级
            self._driver = None
            raise KgProjectionUnavailable(f"neo4j connect failed: {error}") from error
        return self._driver

    NODE_LABEL = "KGEntity"
    REL_TYPE = "KG_REL"

    # 投影写入/查询都按 (kbId, id) 定位节点。没有索引时每条关系的两次 MATCH
    # 都是全标签扫描：399 实体 / 6,230 关系的库全量重建要 30 秒（2026-11-24
    # 实测，抽取本身 1 秒）——同步的快速抽取请求因此超过前端 30 秒超时，
    # 深度抽取任务收尾也被拖慢。首次连上时幂等建好，存量部署自动生效。
    _SCHEMA_STATEMENTS = (
        "CREATE CONSTRAINT kg_entity_id IF NOT EXISTS "
        f"FOR (e:{NODE_LABEL}) REQUIRE e.id IS UNIQUE",
        f"CREATE INDEX kg_entity_kb IF NOT EXISTS FOR (e:{NODE_LABEL}) ON (e.kbId)",
    )

    def _ensure_schema(self) -> None:
        with self._driver.session(database="neo4j") as session:
            for statement in self._SCHEMA_STATEMENTS:
                try:
                    session.run(statement).consume()
                except Exception as error:  # noqa: BLE001 - 建索引失败只是变慢，不阻断
                    logger.warning("neo4j schema statement failed: %s", error)

    def available(self) -> bool:
        if self._driver_factory is None and not settings.neo4j_uri:
            return False
        try:
            self._get_driver()
            return True
        except KgProjectionUnavailable:
            return False

    def _run(self, query: str, **params):
        driver = self._get_driver()
        with driver.session(database="neo4j") as session:
            return list(session.run(query, **params))

    # ------------------------------------------------------------ 投影写入

    def upsert_entity(self, entity) -> None:
        """entity: GraphEntity ORM 行。"""
        self._run(
            f"""
            MERGE (e:{self.NODE_LABEL} {{kbId: $kb, id: $id}})
            SET e.name = $name, e.type = $type,
                e.aliases = $aliases, e.method = $method,
                e.freq = $freq, e.merged = $merged
            """,
            kb=str(entity.kb_id), id=str(entity.id), name=entity.name,
            type=entity.entity_type, aliases=list(entity.aliases or []),
            method=(entity.properties or {}).get("method") or "manual",
            freq=int((entity.properties or {}).get("freq") or 0),
            merged=False,
        )

    def upsert_relation(self, relation) -> None:
        self._run(
            f"""
            MATCH (a:{self.NODE_LABEL} {{kbId: $kb, id: $sid}})
            MATCH (b:{self.NODE_LABEL} {{kbId: $kb, id: $tid}})
            MERGE (a)-[r:{self.REL_TYPE} {{key: $rkey}}]->(b)
            SET r.type = $rtype, r.weight = $weight, r.evidence = $evidence
            """,
            kb=str(relation.kb_id), sid=str(relation.source_id),
            tid=str(relation.target_id),
            rkey=_relation_key(relation.source_id, relation.target_id,
                               relation.relation_type),
            rtype=relation.relation_type,
            weight=int((relation.properties or {}).get("weight") or 0),
            evidence=str((relation.properties or {}).get("evidence") or ""),
        )

    def delete_entity(self, entity_id) -> None:
        self._run(
            f"MATCH (e:{self.NODE_LABEL} {{id: $id}}) DETACH DELETE e",
            id=str(entity_id),
        )

    def delete_relation(self, relation) -> None:
        self._run(
            f"""
            MATCH (:{self.NODE_LABEL} {{id: $sid}})
            -[r:{self.REL_TYPE} {{key: $rkey}}]->
            (:{self.NODE_LABEL} {{id: $tid}})
            DELETE r
            """,
            sid=str(relation.source_id), tid=str(relation.target_id),
            rkey=_relation_key(relation.source_id, relation.target_id,
                               relation.relation_type),
        )

    # ------------------------------------------------------------ 全量重建

    def resync_kb(self, db, kb_id) -> dict:
        """全量重投影一个库（幂等）：清子图 → 批量 UNWIND 重灌。"""
        from app.models.knowledge import GraphEntity, GraphRelation

        kb_key = str(kb_id)
        self._run(
            f"MATCH (e:{self.NODE_LABEL} {{kbId: $kb}}) DETACH DELETE e",
            kb=kb_key,
        )
        entities = (
            db.query(GraphEntity)
            .filter(GraphEntity.kb_id == kb_id, GraphEntity.merged_into.is_(None))
            .all()
        )
        relations = db.query(GraphRelation).filter(GraphRelation.kb_id == kb_id).all()
        live_ids = {str(e.id) for e in entities}
        entity_params = [
            {
                "kb": kb_key, "id": str(e.id), "name": e.name,
                "type": e.entity_type, "aliases": list(e.aliases or []),
                "method": (e.properties or {}).get("method") or "manual",
                "freq": int((e.properties or {}).get("freq") or 0),
            }
            for e in entities
        ]
        relation_params = []
        for rel in relations:
            sid, tid = str(rel.source_id), str(rel.target_id)
            if sid not in live_ids or tid not in live_ids:
                continue
            relation_params.append({
                "kb": kb_key, "sid": sid, "tid": tid,
                "rkey": _relation_key(rel.source_id, rel.target_id, rel.relation_type),
                "rtype": rel.relation_type,
                "weight": int((rel.properties or {}).get("weight") or 0),
                "evidence": str((rel.properties or {}).get("evidence") or ""),
            })
        for start in range(0, len(entity_params), _MAX_BATCH):
            self._run(
                f"""
                UNWIND $rows AS row
                MERGE (e:{self.NODE_LABEL} {{kbId: row.kb, id: row.id}})
                SET e.name = row.name, e.type = row.type,
                    e.aliases = row.aliases, e.method = row.method, e.freq = row.freq
                """,
                rows=entity_params[start:start + _MAX_BATCH],
            )
        for start in range(0, len(relation_params), _MAX_BATCH):
            self._run(
                f"""
                UNWIND $rows AS row
                MATCH (a:{self.NODE_LABEL} {{kbId: row.kb, id: row.sid}})
                MATCH (b:{self.NODE_LABEL} {{kbId: row.kb, id: row.tid}})
                MERGE (a)-[r:{self.REL_TYPE} {{key: row.rkey}}]->(b)
                SET r.type = row.rtype, r.weight = row.weight, r.evidence = row.evidence
                """,
                rows=relation_params[start:start + _MAX_BATCH],
            )
        return {"entities": len(entity_params), "relations": len(relation_params)}

    def status(self, db, kb_id) -> dict:
        entities = self._run(
            f"MATCH (e:{self.NODE_LABEL} {{kbId: $kb}}) RETURN count(e) AS n",
            kb=str(kb_id),
        )
        relations = self._run(
            f"MATCH (:{self.NODE_LABEL} {{kbId: $kb}})-[r]->() RETURN count(r) AS n",
            kb=str(kb_id),
        )
        return {
            "available": True,
            "entities": entities[0]["n"] if entities else 0,
            "relations": relations[0]["n"] if relations else 0,
        }

    # ------------------------------------------------------------ 图查询

    def neighbors(self, kb_id, entity_id: str, hops: int = 1, limit: int = 60) -> dict:
        # 变长关系类型匹配在 Cypher 里写法受限，按跳数展开两条固定查询
        if hops <= 1:
            query = f"""
                MATCH (e:{self.NODE_LABEL} {{kbId: $kb, id: $id}})-[r]-(n)
                RETURN n.id AS id, n.name AS name, n.type AS type,
                       type(r) AS rel, r.weight AS weight, r.evidence AS evidence
                LIMIT $limit
            """
        else:
            query = f"""
                MATCH (e:{self.NODE_LABEL} {{kbId: $kb, id: $id}})
                -[r1]-(m:{self.NODE_LABEL} {{kbId: $kb}})
                -[r2]-(n:{self.NODE_LABEL} {{kbId: $kb}})
                WHERE n.id <> $id
                RETURN DISTINCT n.id AS id, n.name AS name, n.type AS type,
                       r2.type AS rel, r2.weight AS weight, '' AS evidence
                LIMIT $limit
            """
        rows = self._run(query, kb=str(kb_id), id=str(entity_id), limit=int(limit))
        return {
            "entities": [
                {"id": r["id"], "name": r["name"], "type": r["type"]}
                for r in rows if r["id"]
            ],
            "relations": [
                {"type": r["rel"], "weight": r["weight"], "evidence": r["evidence"]}
                for r in rows
            ],
        }

    def shortest_path(self, kb_id, source_id: str, target_id: str, max_hops: int = 6) -> dict:
        rows = self._run(
            f"""
            MATCH (a:{self.NODE_LABEL} {{kbId: $kb, id: $a}}),
                  (b:{self.NODE_LABEL} {{kbId: $kb, id: $b}})
            MATCH p = shortestPath((a)-[*..{int(max_hops)}]-(b))
            RETURN [n IN nodes(p) | {{id: n.id, name: n.name, type: n.type}}] AS nodes,
                   [r IN relationships(p) | {{type: r.type, weight: r.weight}}] AS relations
            """,
            kb=str(kb_id), a=str(source_id), b=str(target_id),
        )
        if not rows:
            return {"nodes": [], "relations": []}
        return {"nodes": rows[0]["nodes"], "relations": rows[0]["relations"]}

    def related_topk(self, kb_id, entity_id: str, k: int = 10) -> list[dict]:
        rows = self._run(
            f"""
            MATCH (e:{self.NODE_LABEL} {{kbId: $kb, id: $id}})-[r]-(n)
            RETURN n.id AS id, n.name AS name, n.type AS type,
                   r.type AS rel, r.weight AS weight
            ORDER BY coalesce(r.weight, 0) DESC
            LIMIT $k
            """,
            kb=str(kb_id), id=str(entity_id), k=int(k),
        )
        return [
            {"id": r["id"], "name": r["name"], "type": r["type"],
             "relation": r["rel"], "weight": r["weight"]}
            for r in rows if r["id"]
        ]


def _relation_key(source_id, target_id, relation_type: str) -> str:
    pair = sorted([str(source_id), str(target_id)])
    return f"{pair[0]}->{pair[1]}:{relation_type}"


# ------------------------------------------------------------ PG 兜底查询


def _live_entity(db, kb_id, entity_id):
    from app.models.knowledge import GraphEntity

    return (
        db.query(GraphEntity)
        .filter(GraphEntity.kb_id == kb_id, GraphEntity.id == entity_id,
                GraphEntity.merged_into.is_(None))
        .first()
    )


def neighbors_pg(db, kb_id, entity_id, hops: int = 1, limit: int = 60) -> dict:
    """PG 兜底：按跳数逐层扩边（source/target 均有索引），无 Neo4j 也能查。"""
    from app.models.knowledge import GraphEntity, GraphRelation

    root = _live_entity(db, kb_id, entity_id)
    if root is None:
        return {"entities": [], "relations": []}
    visited = {root.id: root}
    frontier = [root.id]
    triples: list[dict] = []
    for _ in range(max(1, int(hops))):
        next_frontier: list = []
        edges = (
            db.query(GraphRelation)
            .filter(
                GraphRelation.kb_id == kb_id,
                (GraphRelation.source_id.in_(frontier))
                | (GraphRelation.target_id.in_(frontier)),
            )
            .limit(limit * 4)
            .all()
        )
        for rel in edges:
            other_id = rel.target_id if rel.source_id in frontier else rel.source_id
            if other_id not in visited:
                other = db.get(GraphEntity, other_id)
                if other is None or other.merged_into is not None:
                    continue
                visited[other_id] = other
                next_frontier.append(other_id)
            triples.append({
                "source": visited.get(rel.source_id),
                "target": visited.get(rel.target_id),
                "type": rel.relation_type,
                "weight": (rel.properties or {}).get("weight") or 0,
            })
            if len(triples) >= limit:
                break
        if not next_frontier or len(triples) >= limit:
            break
        frontier = next_frontier
    return {
        "entities": [
            {"id": str(e.id), "name": e.name, "type": e.entity_type}
            for e in visited.values()
        ],
        "relations": triples[:limit],
    }


def shortest_path_pg(db, kb_id, source_id, target_id, max_hops: int = 6) -> dict:
    """PG 兜底 BFS 最短路径（无向），返回节点/关系序列。"""
    from app.models.knowledge import GraphEntity, GraphRelation

    source = _live_entity(db, kb_id, source_id)
    target = _live_entity(db, kb_id, target_id)
    if source is None or target is None:
        return {"nodes": [], "relations": []}
    parents: dict = {source.id: None}
    parent_rel: dict = {}
    frontier = [source.id]
    for _ in range(max(1, int(max_hops))):
        next_frontier: list = []
        edges = (
            db.query(GraphRelation)
            .filter(
                GraphRelation.kb_id == kb_id,
                (GraphRelation.source_id.in_(frontier))
                | (GraphRelation.target_id.in_(frontier)),
            )
            .limit(5000)
            .all()
        )
        for rel in edges:
            other_id = rel.target_id if rel.source_id in frontier else rel.source_id
            if other_id in parents:
                continue
            parents[other_id] = rel.source_id if rel.source_id in frontier else rel.target_id
            parent_rel[other_id] = rel
            if other_id == target.id:
                # 回溯路径
                node_ids = [target.id]
                rels = []
                cursor = target.id
                while parents[cursor] is not None:
                    rels.append(parent_rel[cursor])
                    cursor = parents[cursor]
                    node_ids.append(cursor)
                node_ids.reverse()
                rels.reverse()
                nodes = []
                for nid in node_ids:
                    entity = db.get(GraphEntity, nid)
                    nodes.append({"id": str(nid), "name": entity.name,
                                  "type": entity.entity_type})
                return {
                    "nodes": nodes,
                    "relations": [
                        {"source": str(r.source_id), "target": str(r.target_id),
                         "type": r.relation_type,
                         "weight": (r.properties or {}).get("weight") or 0}
                        for r in rels
                    ],
                }
            next_frontier.append(other_id)
        if not next_frontier:
            break
        frontier = next_frontier
    return {"nodes": [], "relations": []}


def related_topk_pg(db, kb_id, entity_id, k: int = 10) -> list[dict]:
    from app.models.knowledge import GraphEntity, GraphRelation

    if _live_entity(db, kb_id, entity_id) is None:
        return []
    rels = (
        db.query(GraphRelation)
        .filter(
            GraphRelation.kb_id == kb_id,
            (GraphRelation.source_id == entity_id) | (GraphRelation.target_id == entity_id),
        )
        .all()
    )
    scored = []
    for rel in rels:
        other_id = rel.target_id if rel.source_id == entity_id else rel.source_id
        other = db.get(GraphEntity, other_id)
        if other is None or other.merged_into is not None:
            continue
        scored.append({
            "id": str(other.id), "name": other.name, "type": other.entity_type,
            "relation": rel.relation_type,
            "weight": int((rel.properties or {}).get("weight") or 0),
        })
    scored.sort(key=lambda item: -item["weight"])
    return scored[:k]


# ------------------------------------------------------------ 图问答上下文

_TRIPLES_CACHE: dict[tuple, str] = {}
_TRIPLES_CACHE_MAX = 32


def graph_triples_context(db, kb, question: str, *,
                          max_entities: int = 5, max_triples: int = 30) -> str:
    """从问题中命中实体名/别名 → 收集 1 跳三元组 → 拼提示词上下文块。

    kb 可传 KnowledgeBase 对象或 uuid（端点里两形态都有）；命中为空返回空串
    （对话链路按「无图谱上下文」处理）。实体名单按 (kb_id, 实体数) 缓存。
    """
    kb_id = getattr(kb, "id", kb)
    if not isinstance(kb_id, uuid.UUID):
        kb_id = uuid.UUID(str(kb_id))
    from app.models.knowledge import GraphEntity, GraphRelation
    from app.services.kg_names import normalize_name

    count = (
        db.query(GraphEntity)
        .filter(GraphEntity.kb_id == kb_id, GraphEntity.merged_into.is_(None))
        .count()
    )
    cache_key = (str(kb_id), count)
    name_map = _TRIPLES_CACHE.get(cache_key)
    if name_map is None:
        entities = (
            db.query(GraphEntity)
            .filter(GraphEntity.kb_id == kb_id, GraphEntity.merged_into.is_(None))
            .all()
        )
        name_map: dict[str, dict] = {}
        for entity in entities:
            entry = {"id": str(entity.id), "entity": entity,
                     "names": [normalize_name(entity.name)]}
            for alias in entity.aliases or []:
                entry["names"].append(normalize_name(str(alias)))
            name_map[str(entity.id)] = entry
        if len(_TRIPLES_CACHE) > _TRIPLES_CACHE_MAX:
            _TRIPLES_CACHE.clear()
        _TRIPLES_CACHE[cache_key] = name_map

    normalized_question = normalize_name(question or "")
    hits: list[dict] = []
    for entry in name_map.values():
        for candidate in entry["names"]:
            if candidate and candidate in normalized_question:
                hits.append(entry)
                break
        if len(hits) >= max_entities:
            break
    if not hits:
        return ""

    lines: list[str] = []
    seen: set = set()
    for entry in hits:
        entity = entry["entity"]
        rels = (
            db.query(GraphRelation)
            .filter(
                GraphRelation.kb_id == kb.id,
                (GraphRelation.source_id == entity.id)
                | (GraphRelation.target_id == entity.id),
            )
            .all()
        )
        for rel in rels[: max_triples - len(lines)]:
            source = db.get(GraphEntity, rel.source_id)
            target = db.get(GraphEntity, rel.target_id)
            if source is None or target is None:
                continue
            key = (rel.source_id, rel.target_id, rel.relation_type)
            if key in seen:
                continue
            seen.add(key)
            evidence = str((rel.properties or {}).get("evidence") or "")
            suffix = f"（原文：{evidence}）" if evidence else ""
            lines.append(f"{source.name} -[{rel.relation_type}]-> {target.name}{suffix}")
            if len(lines) >= max_triples:
                break
        if len(lines) >= max_triples:
            break
    if not lines:
        return ""
    return "【知识图谱三元组开始】\n" + "\n".join(lines) + "\n【知识图谱三元组结束】"

