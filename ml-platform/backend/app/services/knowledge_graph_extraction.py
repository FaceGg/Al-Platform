"""Rule + statistics based knowledge-graph extraction for knowledge bases.

Deterministic, no LLM dependency (a future optional LLM pass would tag itself
via properties.method). The auto layer is fully rebuilt on each run:
entities/relations flagged properties.source="auto" are replaced, while
user-created (manual) graph rows are never touched.
"""
import re
import time
import unicodedata
from collections import Counter, defaultdict

from app.config import settings
from app.models.knowledge import GraphEntity, GraphRelation
from app.services.knowledge_retrieval import extract_pos_pairs

# Ambiguous high-frequency words that drown out real domain concepts.
STOPWORDS = {
    "我们", "你们", "他们", "这个", "那个", "一个", "一种", "一些", "以上", "以下",
    "可以", "应该", "需要", "使用", "进行", "出现", "发生", "导致", "造成", "问题",
    "情况", "方法", "方式", "结果", "原因", "时候", "方面", "内容", "数据", "系统",
    "the", "and", "for", "with", "this", "that", "from", "are", "was", "were",
}

SENTENCE_SPLIT = re.compile(r"[。！？；;！?]+|\n+")
ASCII_NAME = re.compile(r"^[a-z0-9_\- ]+$")

# Sentence patterns that imply a typed relation between two known entities.
RELATION_PATTERNS = [
    (re.compile(r"是一种|属于一种|是一类"), "is_a"),
    (re.compile(r"组成|组成部分|由.{1,12}组成|包含|包括"), "part_of"),
]

# Distinct jieba POS tags carried over as entity types; the rest map to concept.
POS_ENTITY_TYPE = {"nr": "person", "ns": "location", "nt": "organization", "eng": "term"}


def _normalize_name(name: str) -> str:
    # NFKC folds full-width forms to half-width; whitespace collapsed; ASCII
    # names are casefolded so "Steel"/"steel" merge while Han text is intact.
    name = re.sub(r"\s+", " ", unicodedata.normalize("NFKC", name)).strip()
    return name.casefold() if ASCII_NAME.match(name) else name


def _split_sentences(text: str) -> list[str]:
    return [s.strip() for s in SENTENCE_SPLIT.split(text or "") if s.strip()]


def extract_kb_graph(db, kb, doc_contents: list[tuple[str, str]]) -> dict:
    """Rebuild the auto graph layer of ``kb`` from the given documents.

    Args:
        doc_contents: list of (doc_id, content) pairs to extract from; the
            caller decides the subset (default: every document of the KB).
            The auto layer is rebuilt from exactly these documents.

    Returns an ExtractionReport dict; never raises on empty input.
    """
    started = time.monotonic()
    max_entities = getattr(settings, "knowledge_graph_max_entities", 500)
    max_relations = getattr(settings, "knowledge_graph_max_relations", 2000)
    min_freq = getattr(settings, "knowledge_graph_min_entity_freq", 2)
    time_budget = getattr(settings, "knowledge_graph_time_budget_seconds", 30)

    def _expired():
        return time.monotonic() - started > time_budget

    # Pass 1: per-sentence entity candidates with frequency and provenance.
    freq: Counter = Counter()
    doc_freq: defaultdict = defaultdict(set)
    entity_pos: defaultdict = defaultdict(Counter)
    sentence_entities: list[set[str]] = []
    for doc_id, content in doc_contents:
        for sentence in _split_sentences(content):
            names: set[str] = set()
            for phrase, flag in extract_pos_pairs(sentence):
                name = _normalize_name(phrase)
                if name in STOPWORDS or len(name) < 2 or name.isdigit():
                    continue
                names.add(name)
                entity_pos[name][flag] += 1
            for name in names:
                freq[name] += 1
                doc_freq[name].add(doc_id)
            if names:
                sentence_entities.append(names)
            if _expired():
                break

    # Pass 2: rank, threshold, cap.
    ranked = [(name, n) for name, n in freq.most_common() if n >= min_freq]
    truncated = len(ranked) > max_entities or _expired()
    kept_names = {name for name, _ in ranked[:max_entities]}
    if not kept_names:
        _clear_auto_layer(db, kb.id)
        db.commit()
        return _report(0, 0, len(freq), started, truncated)

    # Pass 3: relations - typed pattern hits, then plain co-occurrence.
    relation_counter: Counter = Counter()
    for sentence in (s for _, content in doc_contents for s in _split_sentences(content)):
        haystack = sentence.casefold()
        present = sorted(name for name in kept_names if name in haystack)
        if len(present) < 2:
            continue
        relation_type = next(
            (rtype for pattern, rtype in RELATION_PATTERNS if pattern.search(sentence)),
            None,
        )
        for i, source in enumerate(present):
            for target in present[i + 1:]:
                if source != target:
                    relation_counter[(source, target, relation_type or "co_occurs_with")] += 1
        if _expired():
            truncated = True
            break

    # Persist: replace the auto layer, keep manual rows untouched.
    _clear_auto_layer(db, kb.id)
    entity_ids: dict[str, GraphEntity] = {}
    for name, count in ranked[:max_entities]:
        pos_counter = entity_pos.get(name)
        entity_type = "concept"
        if pos_counter:
            top_flag, _ = pos_counter.most_common(1)[0]
            entity_type = POS_ENTITY_TYPE.get(top_flag, "concept")
        entity = GraphEntity(
            kb_id=kb.id, name=name, entity_type=entity_type,
            properties={
                "source": "auto", "method": "rules", "freq": count,
                "doc_ids": sorted(doc_freq.get(name, set())),
            },
        )
        db.add(entity)
        entity_ids[name] = entity
    db.flush()

    relations_created = 0
    for (source, target, relation_type), weight in relation_counter.most_common():
        if relations_created >= max_relations:
            truncated = True
            break
        db.add(GraphRelation(
            kb_id=kb.id, source_id=entity_ids[source].id, target_id=entity_ids[target].id,
            relation_type=relation_type,
            properties={"source": "auto", "method": "rules", "weight": weight},
        ))
        relations_created += 1
    db.commit()

    return _report(len(entity_ids), relations_created, len(freq), started, truncated)


def _report(entities: int, relations: int, candidates: int, started: float, truncated: bool) -> dict:
    return {
        "entities_created": entities,
        "relations_created": relations,
        "entities_merged": candidates,
        "duration_ms": int((time.monotonic() - started) * 1000),
        "truncated": truncated,
    }


def _clear_auto_layer(db, kb_id) -> int:
    """Delete this KB's auto entities and their relations; manual rows survive."""
    auto_entities = db.query(GraphEntity).filter(
        GraphEntity.kb_id == kb_id,
        GraphEntity.properties["source"].as_string() == "auto",
    ).all()
    if not auto_entities:
        return 0
    auto_ids = [e.id for e in auto_entities]
    db.query(GraphRelation).filter(
        GraphRelation.kb_id == kb_id,
        GraphRelation.source_id.in_(auto_ids) | GraphRelation.target_id.in_(auto_ids),
    ).delete(synchronize_session=False)
    for entity in auto_entities:
        db.delete(entity)
    return len(auto_entities)
