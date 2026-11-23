"""
Knowledge Base, Knowledge Graph, and RAG API endpoints.
"""
import logging
import uuid
import io
import json
import os
import re
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Body, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, text
import numpy as np

from app.database import get_db
from app.models.knowledge import KnowledgeBase, Document, Chunk, GraphEntity, GraphRelation, ChatSession, ChatMessage
from app.models.user import User

logger = logging.getLogger(__name__)
from app.api.auth import get_current_user
from app.config import settings
from app.services.llm_gateway import resolve_profile as resolve_llm_profile

from app.engine.vector_store import get_vector_store
from app.services.knowledge_retrieval import (
    _compute_similarity,
    _compute_tfidf_embedding,
    retrieve_chunks,
)

router = APIRouter(prefix="/api/knowledge", tags=["knowledge"])


def normalize_chat_messages(request: dict) -> dict:
    """Keep local message IDs and source metadata out of provider requests."""
    messages = request.get("messages")
    if messages is None:
        history = request.get("history") or []
        messages = [
            {"role": item.get("role"), "content": item.get("content")}
            for item in history
            if isinstance(item, dict)
        ]
        legacy_message = request.get("message")
        if legacy_message:
            messages.append({"role": "user", "content": legacy_message})

    normalized = []
    for item in messages or []:
        if not isinstance(item, dict):
            continue
        role = item.get("role")
        content = item.get("content")
        if role in {"system", "user", "assistant"} and isinstance(content, str) and content:
            normalized.append({"role": role, "content": content})

    return {
        "messages": normalized,
        "session_id": request.get("session_id") or request.get("chat_id"),
    }


# -------------------------------------------------------------------------------
#  Utility: TF-IDF embedding helpers now live in app.services.knowledge_retrieval
#  (shared with the standalone chat API, the published chat API, and graph
#  extraction). The private names are re-exported above for compatibility.
# -------------------------------------------------------------------------------


# -------------------------------------------------------------------------------
#  Knowledge Base CRUD
# -------------------------------------------------------------------------------

@router.get("/bases")
def list_bases(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    bases = db.query(KnowledgeBase).filter(KnowledgeBase.owner_id == current_user.id).all()
    document_counts = {}
    if bases:
        document_counts = dict(
            db.query(Document.kb_id, func.count(Document.id))
            .filter(Document.kb_id.in_([base.id for base in bases]))
            .group_by(Document.kb_id)
            .all()
        )
    return [
        {
            "id": str(b.id),
            "name": b.name,
            "description": b.description,
            "owner_id": str(b.owner_id),
            "document_count": document_counts.get(b.id, 0),
            "created_at": b.created_at.isoformat() if b.created_at else None,
        }
        for b in bases
    ]


@router.post("/bases")
def create_base(
    name: str = Body(...),
    description: str = Body(default=""),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    kb = KnowledgeBase(name=name, description=description, owner_id=current_user.id)
    db.add(kb)
    db.commit()
    db.refresh(kb)
    return {
        "id": str(kb.id),
        "name": kb.name,
        "description": kb.description,
        "created_at": kb.created_at.isoformat() if kb.created_at else None,
    }


@router.patch("/bases/{kb_id}")
def update_base(
    kb_id: str,
    name: str | None = Body(default=None),
    description: str | None = Body(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """更新知识库名称/描述（知识库管理表格行内编辑，用户需求 2026-11-19）。

    系统分区 KB 名称不可改（按名定位创建的定位键，409 拒绝）；普通 KB
    名称必填非空。"""
    kb = db.query(KnowledgeBase).filter(
        KnowledgeBase.id == uuid.UUID(kb_id),
        KnowledgeBase.owner_id == current_user.id,
    ).first()
    if not kb:
        raise HTTPException(404, "Knowledge base not found")
    if name is not None:
        new_name = name.strip()
        if not new_name:
            raise HTTPException(422, "Knowledge base name cannot be empty")
        if kb.name == "平台经验（系统分区）" and new_name != kb.name:
            raise HTTPException(
                409,
                "系统分区名称不可修改（系统按该名定位经验分区）",
            )
        kb.name = new_name
    if description is not None:
        kb.description = description.strip()
    db.commit()
    db.refresh(kb)
    return {
        "id": str(kb.id),
        "name": kb.name,
        "description": kb.description,
    }


@router.get("/bases/{kb_id}")
def get_base(
    kb_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    kb = db.query(KnowledgeBase).filter(
        KnowledgeBase.id == uuid.UUID(kb_id),
        KnowledgeBase.owner_id == current_user.id,
    ).first()
    if not kb:
        raise HTTPException(404, "Knowledge base not found")
    return {
        "id": str(kb.id),
        "name": kb.name,
        "description": kb.description,
        "owner_id": str(kb.owner_id),
        "created_at": kb.created_at.isoformat() if kb.created_at else None,
        "document_count": len(kb.documents),
    }


@router.delete("/bases/{kb_id}")
def delete_base(
    kb_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    kb = db.query(KnowledgeBase).filter(
        KnowledgeBase.id == uuid.UUID(kb_id),
        KnowledgeBase.owner_id == current_user.id,
    ).first()
    if not kb:
        raise HTTPException(404, "Knowledge base not found")
    from app.services.api_publication import sync_chat_publication
    sync_chat_publication(db, kb.id)
    db.delete(kb)
    db.commit()
    return {"message": "Knowledge base deleted"}


# -------------------------------------------------------------------------------
#  Document Management
# -------------------------------------------------------------------------------

def _extract_document_text(filename: str, file_bytes: bytes) -> str:
    """Extract plain text from an uploaded document by extension.

    Supports PDF (text layer), Word .docx, Excel .xlsx/.xlsm, and any
    UTF-8 text file. Legacy .doc is rejected with a clear message (needs a
    converter). Scanned PDFs without a text layer are rejected instead of
    silently ingesting an empty document.
    """
    ext = os.path.splitext(filename)[1].lower()

    if ext == ".pdf":
        import pymupdf

        doc = pymupdf.open(stream=file_bytes, filetype="pdf")
        try:
            pages = [page.get_text("text") for page in doc]
        finally:
            doc.close()
        text = "\n\n".join(p.strip() for p in pages if p.strip())
        if not text.strip():
            raise HTTPException(
                422,
                "PDF 没有文本层（扫描件或图片版）。请先 OCR 转出文本，或上传文字版 PDF",
            )
        return text

    if ext == ".docx":
        import docx

        document = docx.Document(io.BytesIO(file_bytes))
        parts = [p.text for p in document.paragraphs]
        for table in document.tables:
            for row in table.rows:
                parts.append(" | ".join(cell.text for cell in row.cells))
        text = "\n".join(p.strip() for p in parts if p.strip())
        if not text.strip():
            raise HTTPException(422, "Word 文档中没有可提取的文本")
        return text

    if ext in (".xlsx", ".xlsm"):
        import openpyxl

        workbook = openpyxl.load_workbook(
            io.BytesIO(file_bytes), read_only=True, data_only=True,
        )
        try:
            lines = []
            for sheet in workbook.worksheets:
                lines.append(f"[工作表 {sheet.title}]")
                for row in sheet.iter_rows(values_only=True):
                    cells = ["" if v is None else str(v) for v in row]
                    if any(c.strip() for c in cells):
                        lines.append(" | ".join(cells))
        finally:
            workbook.close()
        text = "\n".join(lines).strip()
        if not text.strip():
            raise HTTPException(422, "Excel 工作簿中没有可提取的文本")
        return text

    if ext == ".doc":
        raise HTTPException(
            422,
            "暂不支持旧版 .doc 二进制格式：请另存为 .docx 后上传，或直接粘贴文本",
        )

    return file_bytes.decode("utf-8", errors="replace")


def _pack_chunks(paragraphs: list[str], target: int = 600, max_len: int = 1500) -> list[str]:
    """Greedy-pack short paragraphs into ~target-char chunks for retrieval.

    Document extractions (PDF pages, Word lines) arrive as many tiny lines;
    one-chunk-per-line makes TF-IDF ranking noisy, one-chunk-per-document
    makes it useless. Merge upwards to target, hard-split anything over
    max_len on sentence ends.
    """
    chunks: list[str] = []
    buf = ""
    for para in paragraphs:
        para = para.strip()
        if not para:
            continue
        if len(para) > max_len:
            if buf:
                chunks.append(buf)
                buf = ""
            for piece in re.split(r"(?<=[。！？!?；;])", para):
                if piece.strip() and len(buf) + len(piece) > target and buf:
                    chunks.append(buf)
                    buf = ""
                buf = (buf + piece).strip()
            continue
        if buf and len(buf) + len(para) > target:
            chunks.append(buf)
            buf = ""
        buf = (buf + "\n" + para).strip()
    if buf:
        chunks.append(buf)
    return [c for c in chunks if len(c) >= 20] or [p for p in paragraphs if p.strip()]


@router.post("/bases/{kb_id}/documents")
async def upload_document(
    kb_id: str,
    file: Optional[UploadFile] = File(None),
    content: str = Form(default=""),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    kb = db.query(KnowledgeBase).filter(
        KnowledgeBase.id == uuid.UUID(kb_id),
        KnowledgeBase.owner_id == current_user.id,
    ).first()
    if not kb:
        raise HTTPException(404, "Knowledge base not found")

    # Determine filename and extract text
    if file and file.filename:
        filename = file.filename
        file_bytes = await file.read()
        ext = os.path.splitext(filename)[1].lower()
        file_text = _extract_document_text(filename, file_bytes)
        doc_type = ext.lstrip(".") if ext else "text"
    else:
        filename = "text_input.txt"
        file_text = content
        doc_type = "text"

    if not file_text.strip():
        raise HTTPException(400, "No content provided")

    # Chunk by paragraphs, then greedy-pack to retrieval-friendly granularity
    # for ALL text types（2026-11-19 用户实测：markdown 无双换行的整篇文档
    # split("\n\n") 得 1 块 41 万字符——TF-IDF 一个向量代表 41 万字，检索
    # 粒度完全失效）。此前仅 pdf/docx/xlsx 走打包；现在全部文本类型统一
    # 打包到 ~600 字符块（超长段按句硬切），语义不变。
    paragraphs = [p.strip() for p in file_text.split("\n\n") if p.strip()]
    paragraphs = _pack_chunks(paragraphs)
    if not paragraphs:
        paragraphs = [file_text.strip()]

    # Compute TF-IDF embeddings for all chunks
    embedding_strs = _compute_tfidf_embedding(paragraphs)

    # Save document
    doc = Document(
        kb_id=kb.id,
        filename=filename,
        content=file_text,
        doc_type=doc_type,
        chunk_count=len(paragraphs),
    )
    db.add(doc)
    db.flush()

    # Save chunks
    chunk_ids: list[str] = []
    chunk_texts: list[str] = []
    for i, (para, emb_str) in enumerate(zip(paragraphs, embedding_strs)):
        chunk = Chunk(
            doc_id=doc.id,
            content=para,
            chunk_index=i,
            embedding=emb_str,
        )
        db.add(chunk)
        chunk_ids.append(str(chunk.id))
        chunk_texts.append(para)

    db.commit()
    db.refresh(doc)

    # 上传即同步向量库（2026-11-19 用户问「上传自动分块了还要点全部向量化吗」
    # ——此前检索用的向量索引要靠手动按钮灌入，上传的新文档查不到）。失败
    # 留痕不阻断：按钮仍是兜底修复通道。
    try:
        import numpy as np

        vstore = get_vector_store()
        vectors = np.array([json.loads(e) for e in embedding_strs], dtype=np.float32)
        vstore.add(
            chunk_ids,
            vectors,
            [{"doc_id": str(doc.id), "kb_id": kb_id, "filename": filename, "chunk_index": i}
             for i in range(len(chunk_ids))],
        )
        vstore.save(os.path.join(os.path.dirname(__file__), "..", "..", "data", f"vs_{kb_id}.pkl"))
    except Exception:
        import logging

        logging.getLogger(__name__).warning(
            "kb %s doc %s: upload-time vector store sync failed; "
            "manual vectorize still works", kb_id, doc.id, exc_info=True,
        )
    return {
        "id": str(doc.id),
        "filename": doc.filename,
        "doc_type": doc.doc_type,
        "chunk_count": doc.chunk_count,
        "created_at": doc.created_at.isoformat() if doc.created_at else None,
    }


@router.get("/bases/{kb_id}/documents")
def list_documents(
    kb_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    kb = db.query(KnowledgeBase).filter(
        KnowledgeBase.id == uuid.UUID(kb_id),
        KnowledgeBase.owner_id == current_user.id,
    ).first()
    if not kb:
        raise HTTPException(404, "Knowledge base not found")
    docs = db.query(Document).filter(Document.kb_id == kb.id).all()
    return [
        {
            "id": str(d.id),
            "filename": d.filename,
            "doc_type": d.doc_type,
            "chunk_count": d.chunk_count,
            "created_at": d.created_at.isoformat() if d.created_at else None,
            # 预览用截断文本（完整正文可能数 MB，列表接口不带全量）
            "preview": (d.content or "")[:2000],
            "content_length": len(d.content or ""),
        }
        for d in docs
    ]


@router.get("/documents/{doc_id}/export")
def export_document(
    doc_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """导出文档内容为本地文件下载。

    平台存储的是提取文本（PDF/Word/Excel 原始二进制不落盘），因此文本类
    文档保持原格式导出，其余类型统一导出为同名 .txt（文件名注明）。
    """
    from urllib.parse import quote
    from fastapi.responses import Response

    try:
        doc_uuid = uuid.UUID(doc_id)
    except (TypeError, ValueError) as error:
        raise HTTPException(404, "Document not found") from error
    doc = db.get(Document, doc_uuid)
    if doc is None:
        raise HTTPException(404, "Document not found")
    kb = db.get(KnowledgeBase, doc.kb_id)
    if kb is None or kb.owner_id != current_user.id:
        raise HTTPException(404, "Document not found")

    stem = os.path.splitext(doc.filename or doc.id)[0] or str(doc.id)[:8]
    ext = os.path.splitext(doc.filename or "")[1].lower()
    if ext in (".txt", ".md", ".csv"):
        export_name = f"{stem}{ext}"
    else:
        export_name = f"{stem}（提取文本）.txt"
    content = doc.content or ""
    quoted = quote(export_name)
    return Response(
        content=content.encode("utf-8"),
        media_type="text/plain; charset=utf-8",
        headers={
            "Content-Disposition": (
                f"attachment; filename=\"export.txt\"; filename*=UTF-8''{quoted}"
            ),
            "Content-Length": str(len(content.encode("utf-8"))),
        },
    )


@router.delete("/documents/{doc_id}")
def delete_document(
    doc_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    doc = db.query(Document).filter(Document.id == uuid.UUID(doc_id)).first()
    if not doc:
        raise HTTPException(404, "Document not found")
    # Verify ownership through KB
    kb = db.query(KnowledgeBase).filter(
        KnowledgeBase.id == doc.kb_id,
        KnowledgeBase.owner_id == current_user.id,
    ).first()
    if not kb:
        raise HTTPException(403, "Forbidden")
    db.delete(doc)
    db.commit()
    return {"message": "Document deleted"}


# -------------------------------------------------------------------------------
#  Semantic Search (Vector DB with multiple similarity metrics)
# -------------------------------------------------------------------------------

@router.post("/bases/{kb_id}/search")
def search_knowledge(
    kb_id: str,
    query: str = Body(...),
    top_k: int = Body(default=5),
    metric: str = Body(default="cosine"),
    use_vector_store: bool = Body(default=True),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Search chunks using vector similarity.

    Supported metrics: cosine, euclidean, dot.
    Retrieval core lives in app.services.knowledge_retrieval so the chat APIs
    and graph extraction share the exact same ranking.
    """
    kb = db.query(KnowledgeBase).filter(
        KnowledgeBase.id == uuid.UUID(kb_id),
        KnowledgeBase.owner_id == current_user.id,
    ).first()
    if not kb:
        raise HTTPException(404, "Knowledge base not found")

    return retrieve_chunks(
        db, kb, query, top_k=top_k, metric=metric, use_vector_store=use_vector_store,
    )


# -------------------------------------------------------------------------------
#  Vectorize endpoint
# -------------------------------------------------------------------------------

@router.post("/bases/{kb_id}/vectorize")
def vectorize_kb(
    kb_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Embed all un-embedded documents in the knowledge base.

    Computes a document-level embedding using TF-IDF mean vector
    across all chunks and stores it on each Chunk.
    """
    kb = db.query(KnowledgeBase).filter(
        KnowledgeBase.id == uuid.UUID(kb_id),
        KnowledgeBase.owner_id == current_user.id,
    ).first()
    if not kb:
        raise HTTPException(404, "Knowledge base not found")

    # Find chunks without embeddings
    chunks = db.query(Chunk).join(Document).filter(
        Document.kb_id == kb.id,
    ).all()

    chunks_to_vectorize = [c for c in chunks if not c.embedding or c.embedding == ""]

    already_vectorized = len(chunks) - len(chunks_to_vectorize)
    if not chunks_to_vectorize:
        return {
            "message": "All chunks already vectorized",
            "vectorized": 0,
            "already_vectorized": already_vectorized,
        }

    # Collect all chunk texts for corpus-level TF-IDF
    all_texts = [c.content for c in chunks]
    unembedded_texts = [c.content for c in chunks_to_vectorize]

    # Compute TF-IDF for all chunks as a corpus, get embeddings for the unvectorized ones
    emb_strs = _compute_tfidf_embedding(all_texts)

    # Build a mapping: content -> embedding
    # Since _compute_tfidf_embedding returns aligned with input order
    all_emb_map = {all_texts[i]: emb_strs[i] for i in range(len(all_texts))}

    for chunk in chunks_to_vectorize:
        chunk.embedding = all_emb_map.get(chunk.content, chunk.embedding)

    db.commit()

    # Also write to VectorStore for high-performance retrieval
    vstore = get_vector_store()
    vstore_chunk_ids = [str(c.id) for c in chunks]
    vstore_vectors = np.array([json.loads(all_emb_map.get(c.content, "[]")) for c in chunks], dtype=np.float32)
    vstore_metadata = [{"content": c.content[:200], "doc_id": str(c.doc_id), "kb_id": kb_id} for c in chunks]
    vstore.add(vstore_chunk_ids, vstore_vectors, vstore_metadata)

    return {
        "message": f"Vectorized {len(chunks_to_vectorize)} chunks",
        "vectorized": len(chunks_to_vectorize),
        "already_vectorized": already_vectorized,
        "vector_store_stats": vstore.get_stats(),
    }


# -------------------------------------------------------------------------------
#  RAG Query (single-round)
# -------------------------------------------------------------------------------

@router.post("/bases/{kb_id}/rag")
def rag_query(
    kb_id: str,
    query: str = Body(...),
    # Deprecated request-level override (spec v0.9 §14.1 收口): kept only to
    # reject old callers with an explicit 422, never honored.
    llm_api_url: str = Body(default=None),
    top_k: int = Body(default=5),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if llm_api_url:
        raise HTTPException(
            422,
            detail={
                "code": "LLM_REQUEST_OVERRIDE_REMOVED",
                "message": "Request-level llm_api_url override was removed; "
                "configure profiles via /api/llm-profiles.",
            },
        )
    # Step 1: Retrieve relevant chunks
    search_results = search_knowledge(
        kb_id=kb_id,
        query=query,
        top_k=top_k,
        db=db,
        current_user=current_user,
    )
    if not search_results:
        return {"answer": "No relevant information found.", "sources": []}

    # Step 2: Build context
    context = "\n\n".join([r["content"] for r in search_results])

    # Step 3: Build prompt（图谱三元组上下文并入；无命中静默跳过）
    from app.services.kg_projection import graph_triples_context

    graph_block = graph_triples_context(db, kb, query)
    if graph_block:
        prompt = (
            f"Based on the following materials, answer the question:\n{context}\n\n"
            f"{graph_block}\n\nQuestion: {query}"
        )
    else:
        prompt = f"Based on the following materials, answer the question:\n{context}\n\nQuestion: {query}"

    # Step 4: Call LLM API through the gateway
    config = resolve_llm_profile(db, purpose="knowledge_rag")

    # A-15：出站调用走网关共享客户端（keepalive 复用），且先归还 DB 连接
    db.rollback()
    try:
        from app.services.llm_gateway import _HTTP_CLIENT

        resp = _HTTP_CLIENT.post(
            config.api_url,
            headers={
                "Content-Type": "application/json",
                **({"Authorization": f"Bearer {config.api_key}"} if config.api_key else {}),
            },
            json={
                "model": config.model_id,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.3,
            },
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        answer = data["choices"][0]["message"]["content"]
    except Exception as e:
        answer = f"[LLM API call failed: {e}]"

    sources = [{"content": r["content"], "score": r["score"]} for r in search_results]
    return {"answer": answer, "sources": sources}


# -------------------------------------------------------------------------------
#  Multi-turn Chat with Conversation History
# -------------------------------------------------------------------------------

@router.post("/bases/{kb_id}/chat")
def chat(
    kb_id: str,
    request: dict = Body(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Multi-turn chat endpoint with RAG and conversation history.

    request: {
        messages: [{role, content}, ...],
        session_id: str | null,
        llm_api_url: str | null,
        top_k: int (default 5),
    }
    Returns: {answer, sources, session_id}
    """
    kb = db.query(KnowledgeBase).filter(
        KnowledgeBase.id == uuid.UUID(kb_id),
        KnowledgeBase.owner_id == current_user.id,
    ).first()
    if not kb:
        raise HTTPException(404, "Knowledge base not found")

    normalized_request = normalize_chat_messages(request)
    messages = normalized_request["messages"]
    session_id_str = normalized_request["session_id"]
    if request.get("llm_api_url"):
        # Deprecated request-level override (spec v0.9 §14.1 收口): explicit 422.
        raise HTTPException(
            422,
            detail={
                "code": "LLM_REQUEST_OVERRIDE_REMOVED",
                "message": "Request-level llm_api_url override was removed; "
                "configure profiles via /api/llm-profiles.",
            },
        )
    top_k = request.get("top_k", 5)

    if not messages:
        raise HTTPException(400, "messages array is required")

    # Resolve or create session
    if session_id_str:
        session = db.query(ChatSession).filter(
            ChatSession.id == uuid.UUID(session_id_str),
            ChatSession.kb_id == kb.id,
            ChatSession.user_id == current_user.id,
        ).first()
        if not session:
            raise HTTPException(404, "Chat session not found")
    else:
        # Create new session with auto-generated title from first user message
        title = ""
        for m in messages:
            if m.get("role") == "user":
                title = m.get("content", "")[:30]
                break
        session = ChatSession(
            kb_id=kb.id,
            user_id=current_user.id,
            title=title,
        )
        db.add(session)
        db.flush()

    # Get last user message for retrieval
    last_user_msg = None
    for m in reversed(messages):
        if m.get("role") == "user":
            last_user_msg = m.get("content", "")
            break

    if not last_user_msg:
        raise HTTPException(400, "No user message found in messages")

    # Step 1: Retrieve relevant chunks
    search_results = search_knowledge(
        kb_id=kb_id,
        query=last_user_msg,
        top_k=top_k,
        db=db,
        current_user=current_user,
    )

    # Step 2: Build context from search results
    context = ""
    sources_data = []
    if search_results:
        context = "\n\n".join([r["content"] for r in search_results])
        # 来源带具体文档名（引用展示需要），无文件名时退回检索通道标识。
        sources_data = [
            {
                "content": r["content"],
                "score": r["score"],
                "filename": r.get("filename") or "",
                "source": r.get("source") or "",
            }
            for r in search_results
        ]

    # Step 3: Build LLM messages with context + conversation history
    system_msg = {
        "role": "system",
        "content": f"You are a helpful assistant. Use the following context to answer the user's question. If the context doesn't contain relevant information, say so.\n\nContext:\n{context}" if context else "You are a helpful assistant.",
    }

    llm_messages = [system_msg] + messages

    # 图谱上下文（阶段5·知识应用）：问题命中实体名/别名时，把相关三元组并进
    # system 提示词；无命中/图存储不可用时静默跳过。
    from app.services.kg_projection import graph_triples_context

    graph_block = graph_triples_context(db, kb, last_user_msg)
    if graph_block:
        llm_messages[0] = {
            "role": "system",
            "content": system_msg["content"] + "\n\n" + graph_block,
        }

    # Step 4: Save user message
    user_msg = ChatMessage(
        session_id=session.id,
        role="user",
        content=last_user_msg,
        sources=[],
    )
    db.add(user_msg)
    # 立即持久化会话与用户消息——后续 LLM 网关/审计路径可能回滚当前事务，
    # 不先提交会在保存助手消息时外键失败（chat_messages.session_id 悬空）。
    db.commit()

    # Step 5: Call LLM API through the gateway
    config = resolve_llm_profile(db, purpose="knowledge_chat")

    # A-15：出站调用走网关共享客户端；外呼前归还 DB 连接
    db.rollback()
    try:
        from app.services.llm_gateway import _HTTP_CLIENT

        resp = _HTTP_CLIENT.post(
            config.api_url,
            headers={
                "Content-Type": "application/json",
                **({"Authorization": f"Bearer {config.api_key}"} if config.api_key else {}),
            },
            json={
                "model": config.model_id,
                "messages": llm_messages,
                "temperature": 0.3,
            },
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        answer = data["choices"][0]["message"]["content"]
    except Exception as e:
        answer = f"[LLM API call failed: {e}]"

    # Step 6: Save assistant message
    assistant_msg = ChatMessage(
        session_id=session.id,
        role="assistant",
        content=answer,
        sources=sources_data,
    )
    db.add(assistant_msg)

    db.commit()

    return {
        "answer": answer,
        "sources": sources_data,
        "session_id": str(session.id),
    }


@router.get("/bases/{kb_id}/chats")
def list_chats(
    kb_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List chat sessions for a knowledge base."""
    kb = db.query(KnowledgeBase).filter(
        KnowledgeBase.id == uuid.UUID(kb_id),
        KnowledgeBase.owner_id == current_user.id,
    ).first()
    if not kb:
        raise HTTPException(404, "Knowledge base not found")

    sessions = db.query(ChatSession).filter(
        ChatSession.kb_id == kb.id,
        ChatSession.user_id == current_user.id,
    ).order_by(ChatSession.created_at.desc()).all()

    return [
        {
            "id": str(s.id),
            "title": s.title or "Untitled",
            "created_at": s.created_at.isoformat() if s.created_at else None,
            "message_count": len(s.messages),
        }
        for s in sessions
    ]


@router.post("/bases/{kb_id}/chats")
def create_chat(
    kb_id: str,
    request: dict = Body(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create a new empty chat session.

    request: {title: str (optional)}
    """
    kb = db.query(KnowledgeBase).filter(
        KnowledgeBase.id == uuid.UUID(kb_id),
        KnowledgeBase.owner_id == current_user.id,
    ).first()
    if not kb:
        raise HTTPException(404, "Knowledge base not found")

    title = request.get("title", "")
    session = ChatSession(
        kb_id=kb.id,
        user_id=current_user.id,
        title=title,
    )
    db.add(session)
    db.commit()
    db.refresh(session)

    return {
        "id": str(session.id),
        "title": session.title,
        "created_at": session.created_at.isoformat() if session.created_at else None,
    }


@router.get("/bases/{kb_id}/chats/{session_id}")
def get_chat_messages(
    kb_id: str,
    session_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get messages for a chat session."""
    kb = db.query(KnowledgeBase).filter(
        KnowledgeBase.id == uuid.UUID(kb_id),
        KnowledgeBase.owner_id == current_user.id,
    ).first()
    if not kb:
        raise HTTPException(404, "Knowledge base not found")

    session = db.query(ChatSession).filter(
        ChatSession.id == uuid.UUID(session_id),
        ChatSession.kb_id == kb.id,
        ChatSession.user_id == current_user.id,
    ).first()
    if not session:
        raise HTTPException(404, "Chat session not found")

    messages = db.query(ChatMessage).filter(
        ChatMessage.session_id == session.id,
    ).order_by(ChatMessage.created_at).all()

    return {
        "id": str(session.id),
        "title": session.title,
        "created_at": session.created_at.isoformat() if session.created_at else None,
        "messages": [
            {
                "id": str(m.id),
                "role": m.role,
                "content": m.content,
                "sources": m.sources or [],
                "created_at": m.created_at.isoformat() if m.created_at else None,
            }
            for m in messages
        ],
    }


@router.delete("/bases/{kb_id}/chats/{session_id}")
def delete_chat(
    kb_id: str,
    session_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Delete a chat session and all its messages."""
    kb = db.query(KnowledgeBase).filter(
        KnowledgeBase.id == uuid.UUID(kb_id),
        KnowledgeBase.owner_id == current_user.id,
    ).first()
    if not kb:
        raise HTTPException(404, "Knowledge base not found")

    session = db.query(ChatSession).filter(
        ChatSession.id == uuid.UUID(session_id),
        ChatSession.kb_id == kb.id,
        ChatSession.user_id == current_user.id,
    ).first()
    if not session:
        raise HTTPException(404, "Chat session not found")

    db.delete(session)
    db.commit()
    return {"message": "Chat session deleted"}


# -------------------------------------------------------------------------------
#  Knowledge Graph CRUD
# -------------------------------------------------------------------------------

@router.get("/bases/{kb_id}/graph/entities")
def list_entities(
    kb_id: str,
    limit: int | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    kb = db.query(KnowledgeBase).filter(
        KnowledgeBase.id == uuid.UUID(kb_id),
        KnowledgeBase.owner_id == current_user.id,
    ).first()
    if not kb:
        raise HTTPException(404, "Knowledge base not found")
    entities = db.query(GraphEntity).filter(GraphEntity.kb_id == kb.id).all()
    if limit is not None and len(entities) > limit:
        entities = entities[:limit]
    return [
        {
            "id": str(e.id),
            "name": e.name,
            "entity_type": e.entity_type,
            "properties": e.properties,
            "created_at": e.created_at.isoformat() if e.created_at else None,
        }
        for e in entities
    ]


@router.post("/bases/{kb_id}/graph/entities")
def create_entity(
    kb_id: str,
    name: str = Body(...),
    entity_type: str = Body(default="concept"),
    properties: dict = Body(default={}),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    kb = db.query(KnowledgeBase).filter(
        KnowledgeBase.id == uuid.UUID(kb_id),
        KnowledgeBase.owner_id == current_user.id,
    ).first()
    if not kb:
        raise HTTPException(404, "Knowledge base not found")
    # 实体链接（消歧基础层）：同库归一化同名/别名命中时不再新建节点（同名唯一
    # 索引会拒绝），改为把该名字并进既有实体的别名并返回既有实体。
    from app.services.kg_fusion import resolve_merged
    from app.services.kg_names import existing_entity_index, normalize_name

    existing_id = existing_entity_index(db, kb.id).get(normalize_name(name))
    if existing_id is not None:
        existing = resolve_merged(db, existing_id)
        if existing is not None:
            new_alias = normalize_name(name)
            if new_alias != existing.name and new_alias not in (existing.aliases or []):
                existing.aliases = list(existing.aliases or []) + [new_alias]
            props = dict(existing.properties or {})
            props["freq"] = int(props.get("freq") or 0) + 1
            existing.properties = props
            db.commit()
            return {
                "id": str(existing.id),
                "name": existing.name,
                "entity_type": existing.entity_type,
                "properties": existing.properties,
                "created_at": existing.created_at.isoformat() if existing.created_at else None,
                "linked": True,
            }
    entity = GraphEntity(kb_id=kb.id, name=name, entity_type=entity_type, properties=properties)
    db.add(entity)
    db.commit()
    db.refresh(entity)
    try:
        from app.services.kg_projection import get_projection

        get_projection().upsert_entity(entity)
    except Exception:  # noqa: BLE001 - 投影尽力而为，PG 是主源
        pass
    return {
        "id": str(entity.id),
        "name": entity.name,
        "entity_type": entity.entity_type,
        "properties": entity.properties,
        "created_at": entity.created_at.isoformat() if entity.created_at else None,
    }


@router.delete("/graph/entities/{entity_id}")
def delete_entity(
    entity_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    entity = db.query(GraphEntity).filter(GraphEntity.id == uuid.UUID(entity_id)).first()
    if not entity:
        raise HTTPException(404, "Entity not found")
    # Verify ownership through KB
    kb = db.query(KnowledgeBase).filter(
        KnowledgeBase.id == entity.kb_id,
        KnowledgeBase.owner_id == current_user.id,
    ).first()
    if not kb:
        raise HTTPException(403, "Forbidden")
    db.delete(entity)
    db.commit()
    try:
        from app.services.kg_projection import get_projection

        get_projection().delete_entity(entity_id)
    except Exception:  # noqa: BLE001 - 投影尽力而为，PG 是主源
        pass
    return {"message": "Entity deleted"}


@router.get("/bases/{kb_id}/graph/relations")
def list_relations(
    kb_id: str,
    limit: int | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    kb = db.query(KnowledgeBase).filter(
        KnowledgeBase.id == uuid.UUID(kb_id),
        KnowledgeBase.owner_id == current_user.id,
    ).first()
    if not kb:
        raise HTTPException(404, "Knowledge base not found")
    relations = db.query(GraphRelation).filter(GraphRelation.kb_id == kb.id).all()
    if limit is not None and len(relations) > limit:
        # 预览场景：按权重降序只返回最强的前 limit 条（方言无关的内存排序）
        relations = sorted(
            relations,
            key=lambda r: ((r.properties or {}).get("weight") or 0),
            reverse=True,
        )[:limit]
    return [
        {
            "id": str(r.id),
            "source_id": str(r.source_id),
            "target_id": str(r.target_id),
            "relation_type": r.relation_type,
            "properties": r.properties,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in relations
    ]


@router.post("/bases/{kb_id}/graph/relations")
def create_relation(
    kb_id: str,
    source_id: str = Body(...),
    target_id: str = Body(...),
    relation_type: str = Body(default="related_to"),
    properties: dict = Body(default={}),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    kb = db.query(KnowledgeBase).filter(
        KnowledgeBase.id == uuid.UUID(kb_id),
        KnowledgeBase.owner_id == current_user.id,
    ).first()
    if not kb:
        raise HTTPException(404, "Knowledge base not found")
    # Verify both entities exist and belong to this KB
    src = db.query(GraphEntity).filter(
        GraphEntity.id == uuid.UUID(source_id),
        GraphEntity.kb_id == kb.id,
    ).first()
    tgt = db.query(GraphEntity).filter(
        GraphEntity.id == uuid.UUID(target_id),
        GraphEntity.kb_id == kb.id,
    ).first()
    if not src or not tgt:
        raise HTTPException(400, "Source or target entity not found in this knowledge base")
    relation = GraphRelation(
        kb_id=kb.id,
        source_id=src.id,
        target_id=tgt.id,
        relation_type=relation_type,
        properties=properties,
    )
    db.add(relation)
    db.commit()
    db.refresh(relation)
    try:
        from app.services.kg_projection import get_projection

        projection = get_projection()
        projection.upsert_entity(src)
        projection.upsert_entity(tgt)
        projection.upsert_relation(relation)
    except Exception:  # noqa: BLE001 - 投影尽力而为，PG 是主源
        pass
    return {
        "id": str(relation.id),
        "source_id": str(relation.source_id),
        "target_id": str(relation.target_id),
        "relation_type": relation.relation_type,
        "properties": relation.properties,
        "created_at": relation.created_at.isoformat() if relation.created_at else None,
    }


@router.delete("/graph/relations/{rel_id}")
def delete_relation(
    rel_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    relation = db.query(GraphRelation).filter(GraphRelation.id == uuid.UUID(rel_id)).first()
    if not relation:
        raise HTTPException(404, "Relation not found")
    kb = db.query(KnowledgeBase).filter(
        KnowledgeBase.id == relation.kb_id,
        KnowledgeBase.owner_id == current_user.id,
    ).first()
    if not kb:
        raise HTTPException(403, "Forbidden")
    db.delete(relation)
    db.commit()
    try:
        from app.services.kg_projection import get_projection

        get_projection().delete_relation(relation)
    except Exception:  # noqa: BLE001 - 投影尽力而为，PG 是主源
        pass
    return {"message": "Relation deleted"}


@router.post("/bases/{kb_id}/graph/extract")
def extract_kb_graph_endpoint(
    kb_id: str,
    doc_ids: Optional[list[str]] = Body(default=None),
    mode: str = Body(default="rules"),
    max_chunks: Optional[int] = Body(default=None),
    force: Optional[bool] = Body(default=False),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Rebuild the auto knowledge-graph layer from document content.

    mode="rules"（默认，兼容）：确定性规则+统计（jieba 词性粗分、共现、
    is_a/part_of 模式），同步返回 report。
    mode="llm"：大模型深度抽取（按库本体约束类型、实体别名+属性+关系证据），
    创建异步任务立即返回 {mode, job_id}；进度走
    GET /bases/{kb_id}/graph/extract/jobs/{job_id}，取消走 POST .../cancel。
    手工行（无 properties.source 标记）永不修改；auto 层按 method 分别重建。
    """
    kb = db.query(KnowledgeBase).filter(
        KnowledgeBase.id == uuid.UUID(kb_id),
        KnowledgeBase.owner_id == current_user.id,
    ).first()
    if not kb:
        raise HTTPException(404, "Knowledge base not found")

    doc_query = db.query(Document).filter(Document.kb_id == kb.id)
    if doc_ids:
        try:
            wanted = {uuid.UUID(x) for x in doc_ids}
        except (TypeError, ValueError) as error:
            raise HTTPException(422, "doc_ids must be valid UUIDs") from error
        doc_query = doc_query.filter(Document.id.in_(wanted))
    documents = doc_query.all()
    if not documents:
        raise HTTPException(422, "No documents to extract from")

    if mode == "llm":
        from app.models.knowledge import KgExtractionJob
        from app.tasks.kg_tasks import dispatch_kg_extraction

        # 防重入：同库已有进行中的抽取任务时拒绝再派（避免多任务互抢 LLM
        # 出口、交错清写同层）；前端刷新后仍可能重复点击，服务端兜底
        active = db.query(KgExtractionJob).filter(
            KgExtractionJob.kb_id == kb.id,
            KgExtractionJob.status.in_(("pending", "running")),
        ).first()
        if active:
            raise HTTPException(
                409,
                f"An extraction job is already running for this knowledge base "
                f"(job {active.id}, {active.done_units}/{active.total_units} units done); "
                f"wait for it to finish or cancel it first",
            )
        has_chunks = (
            db.query(Chunk)
            .join(Document, Chunk.document)
            .filter(Document.kb_id == kb.id)
            .first()
            is not None
        )
        if not has_chunks:
            raise HTTPException(422, "No chunks available for LLM extraction")
        params: dict = {}
        if doc_ids:
            params["doc_ids"] = [str(x) for x in doc_ids]
        if max_chunks:
            params["max_chunks"] = int(max_chunks)
        if force:
            params["force"] = True
        job = KgExtractionJob(kb_id=kb.id, mode="llm", status="pending", params=params)
        db.add(job)
        db.commit()
        channel = dispatch_kg_extraction(str(job.id))
        return {"mode": "llm", "job_id": str(job.id), "channel": channel}

    # Oversized selections must be split by the caller instead of silently
    # degrading inside the time budget.
    total_chars = sum(len(d.content or "") for d in documents)
    max_chars = settings.knowledge_graph_max_extract_chars
    if total_chars > max_chars:
        raise HTTPException(
            422,
            f"Selected documents total {total_chars} chars, above the {max_chars}-char "
            f"extraction budget; re-run with a doc_ids subset instead",
        )

    from app.services.knowledge_graph_extraction import extract_kb_graph
    report = extract_kb_graph(
        db, kb,
        [(str(d.id), d.content or "") for d in documents],
    )
    # 规则通道与 LLM 通道同权：抽取后跑融合自动归并 + Neo4j 投影（尽力而为）
    try:
        from app.services.kg_fusion import auto_fuse_after_extraction
        from app.services.kg_projection import get_projection

        auto_fuse_after_extraction(db, kb, method="rules")
        try:
            get_projection().resync_kb(db, kb.id)
        except Exception:  # noqa: BLE001
            pass
    except Exception:  # noqa: BLE001
        pass
    return report


# -------------------------------------------------------------------------------
#  Range Search (threshold-based similarity search)
# -------------------------------------------------------------------------------

@router.post("/bases/{kb_id}/search/range")
def range_search(
    kb_id: str,
    query: str = Body(...),
    threshold: float = Body(default=0.3),
    metadata_filter: dict = Body(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Range search: return all vectors above similarity threshold."""
    kb = db.query(KnowledgeBase).filter(
        KnowledgeBase.id == uuid.UUID(kb_id),
        KnowledgeBase.owner_id == current_user.id,
    ).first()
    if not kb:
        raise HTTPException(404, "Knowledge base not found")
    vstore = get_vector_store()
    query_emb = _compute_tfidf_embedding([query], single_text=query)
    query_vec = np.array(json.loads(query_emb), dtype=np.float32)
    results = vstore.range_search(query_vec, threshold=threshold, metadata_filter=metadata_filter)
    enriched = []
    for r in results:
        chunk = db.query(Chunk).filter(Chunk.id == uuid.UUID(r["id"])).first()
        enriched.append({
            "chunk_id": r["id"],
            "content": chunk.content if chunk else r["metadata"].get("content", ""),
            "score": round(r["score"], 4),
        })
    return {"query": query, "threshold": threshold, "count": len(enriched), "results": enriched}


# -------------------------------------------------------------------------------
#  Vector Store Management endpoints
# -------------------------------------------------------------------------------

@router.post("/bases/{kb_id}/vectorize")
def vectorize_documents(
    kb_id: str,
    chunk_size: int = Body(default=500),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Vectorize all documents in knowledge base and store in vector store."""
    kb = db.query(KnowledgeBase).filter(
        KnowledgeBase.id == uuid.UUID(kb_id),
        KnowledgeBase.owner_id == current_user.id,
    ).first()
    if not kb:
        raise HTTPException(404, "Knowledge base not found")
    docs = db.query(Document).filter(Document.kb_id == kb.id).all()
    if not docs:
        return {"message": "No documents to vectorize", "count": 0}
    vstore = get_vector_store()
    total_chunks = 0
    for doc in docs:
        chunks = db.query(Chunk).filter(Chunk.doc_id == doc.id).all()
        if not chunks:
            texts = [doc.content[i:i+chunk_size] for i in range(0, len(doc.content), chunk_size)]
            ids_list = []
            texts_list = []
            meta_list = []
            for j, text in enumerate(texts):
                if not text.strip():
                    continue
                chunk = Chunk(doc_id=doc.id, content=text, chunk_index=j)
                db.add(chunk)
                db.flush()
                ids_list.append(str(chunk.id))
                texts_list.append(text)
                meta_list.append({"doc_id": str(doc.id), "kb_id": kb_id, "filename": doc.filename, "chunk_index": j})
                total_chunks += 1
            if texts_list:
                try:
                    embs = _compute_tfidf_embedding(texts_list)
                    vecs = np.array([np.array(json.loads(e), dtype=np.float32) for e in embs])
                    vstore.add(ids_list, vecs, meta_list)
                except Exception:
                    # 向量入库失败 = 检索静默退化，必须留痕
                    logger.warning(
                        "kb %s doc %s: batch embedding/vector add failed, %s chunks unindexed",
                        kb_id, doc.id, len(ids_list), exc_info=True,
                    )
        else:
            for chunk in chunks:
                if chunk.embedding and chunk.embedding.strip():
                    try:
                        vec = np.array(json.loads(chunk.embedding), dtype=np.float32)
                        vstore.add([str(chunk.id)], vec.reshape(1, -1), [{"doc_id": str(doc.id), "kb_id": kb_id, "filename": doc.filename, "chunk_index": chunk.chunk_index}])
                        total_chunks += 1
                    except Exception:
                        logger.warning(
                            "kb %s doc %s chunk %s: stored embedding unparsable, chunk unindexed",
                            kb_id, doc.id, chunk.id, exc_info=True,
                        )
    doc.chunk_count = total_chunks
    db.commit()
    # Auto-save vector store
    save_path = os.path.join(os.path.dirname(__file__), "..", "..", "data", f"vs_{kb_id}.pkl")
    try:
        vstore.save(save_path)
    except Exception:
        logger.warning("kb %s: vector store persist failed at %s", kb_id, save_path, exc_info=True)
    return {"message": f"Vectorized {total_chunks} chunks", "count": total_chunks}


@router.get("/bases/{kb_id}/vector-stats")
def vector_stats(kb_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Get vector store statistics for a knowledge base."""
    kb = db.query(KnowledgeBase).filter(
        KnowledgeBase.id == uuid.UUID(kb_id),
        KnowledgeBase.owner_id == current_user.id,
    ).first()
    if not kb:
        raise HTTPException(404, "Knowledge base not found")
    vstore = get_vector_store()
    stats = vstore.get_stats()
    # Count vectors for this KB
    kb_count = vstore.count(metadata_filter={"kb_id": kb_id})
    stats["kb_vectors"] = kb_count
    return stats


@router.get("/bases/{kb_id}/export-vectors")
def export_vectors(kb_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Export vector store for a knowledge base."""
    kb = db.query(KnowledgeBase).filter(
        KnowledgeBase.id == uuid.UUID(kb_id),
        KnowledgeBase.owner_id == current_user.id,
    ).first()
    if not kb:
        raise HTTPException(404, "Knowledge base not found")
    vstore = get_vector_store()
    path = os.path.join(os.path.dirname(__file__), "..", "..", "data", f"vs_{kb_id}_export.pkl")
    vstore.export_kb(kb_id, path)
    return {"message": "Vectors exported", "path": path, "kb_id": kb_id}


@router.post("/bases/{kb_id}/reload-vectors")
def reload_vectors(kb_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Reload vector store from saved file."""
    kb = db.query(KnowledgeBase).filter(
        KnowledgeBase.id == uuid.UUID(kb_id),
        KnowledgeBase.owner_id == current_user.id,
    ).first()
    if not kb:
        raise HTTPException(404, "Knowledge base not found")
    vstore = get_vector_store()
    path = os.path.join(os.path.dirname(__file__), "..", "..", "data", f"vs_{kb_id}.pkl")
    loaded = vstore.load(path)
    return {"loaded": loaded, "total_vectors": len(vstore.ids)}


@router.post("/bases/{kb_id}/reembed")
def reembed_kb(kb_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Recompute TF-IDF embeddings for every chunk with the current tokenizer.

    Required once after switching to jieba tokenization: previously stored
    vectors were computed with the legacy word splitting, so Chinese similarity
    is degraded until chunks are re-embedded. Refreshes the VectorStore copies
    in place (falls back to adding when a chunk was never vectorized there).
    """
    kb = db.query(KnowledgeBase).filter(
        KnowledgeBase.id == uuid.UUID(kb_id),
        KnowledgeBase.owner_id == current_user.id,
    ).first()
    if not kb:
        raise HTTPException(404, "Knowledge base not found")

    chunks = db.query(Chunk).join(Document).filter(
        Document.kb_id == kb.id,
    ).all()
    if not chunks:
        return {"reembedded": 0, "message": "Knowledge base has no chunks"}

    texts = [c.content for c in chunks]
    emb_strs = _compute_tfidf_embedding(texts)
    vstore = get_vector_store()
    updated = 0
    vstore_skipped = 0
    for chunk, emb_str in zip(chunks, emb_strs):
        chunk.embedding = emb_str
        updated += 1
        try:
            vec = np.array(json.loads(emb_str), dtype=np.float32)
        except (ValueError, TypeError):
            vstore_skipped += 1
            continue
        metadata = {"content": chunk.content[:200], "doc_id": str(chunk.doc_id), "kb_id": str(kb.id)}
        if vstore.dim is not None and vstore.dim != len(vec):
            # The store is process-global and TF-IDF dims are per-corpus:
            # never mix dimensions (retrieval falls back to the DB path).
            vstore_skipped += 1
            continue
        try:
            vstore.update(str(chunk.id), vector=vec, metadata=metadata)
        except ValueError:
            vstore.add([str(chunk.id)], vec.reshape(1, -1), [metadata])
    db.commit()
    return {
        "reembedded": updated,
        "total_chunks": len(chunks),
        "vector_store_skipped": vstore_skipped,
        "vector_store_stats": vstore.get_stats(),
    }


# -------------------------------------------------------------------------------
#  Enhanced RAG endpoint with source tracking
# -------------------------------------------------------------------------------

@router.post("/bases/{kb_id}/rag-enhanced")
def rag_enhanced(
    kb_id: str,
    query: str = Body(...),
    top_k: int = Body(default=5),
    include_sources: bool = Body(default=True),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Enhanced RAG: retrieve + augment with source tracking + optional LLM call."""
    kb = db.query(KnowledgeBase).filter(
        KnowledgeBase.id == uuid.UUID(kb_id),
        KnowledgeBase.owner_id == current_user.id,
    ).first()
    if not kb:
        raise HTTPException(404, "Knowledge base not found")
    # A-14：历史直接 vstore.search——语料/查询维度不一致时 np.dot 冒泡 500；
    # 改走统一检索路径（语料级缓存 vectorizer + DB 兜底）
    results = retrieve_chunks(
        db, kb, query, top_k=top_k, use_vector_store=True,
    )

    context_chunks = []
    sources = []
    for r in results:
        chunk = db.query(Chunk).filter(
            Chunk.id == uuid.UUID(r["chunk_id"]),
        ).first()
        if chunk:
            doc = db.query(Document).filter(Document.id == chunk.doc_id).first()
            context_chunks.append(chunk.content)
            if include_sources:
                sources.append({
                    "chunk_id": str(chunk.id),
                    "doc_id": str(doc.id) if doc else "",
                    "filename": doc.filename if doc else "unknown",
                    "score": round(r["score"], 4),
                    "content_snippet": chunk.content[:200],
                })
    
    context = "\n\n".join(context_chunks)
    
    # Try LLM call if configured (through the gateway)
    llm_answer = None
    gateway_config = resolve_llm_profile(db, purpose="knowledge_rag_enhanced")
    if gateway_config.api_key:
        try:
            import httpx
            async def _call_llm():
                async with httpx.AsyncClient(timeout=30) as client:
                    resp = await client.post(
                        gateway_config.api_url,
                        headers={"Authorization": f"Bearer {gateway_config.api_key}", "Content-Type": "application/json"},
                        json={
                            "model": gateway_config.model_id,
                            "messages": [
                                {"role": "system", "content": f"You are a helpful assistant. Answer based on this context:\n\n{context}"},
                                {"role": "user", "content": query}
                            ],
                            "temperature": 0.3,
                        }
                    )
                    return resp.json()
            import asyncio
            llm_resp = asyncio.run(_call_llm())
            llm_answer = llm_resp.get("choices", [{}])[0].get("message", {}).get("content", "")
        except Exception as e:
            llm_answer = f"[LLM call failed: {str(e)}]"
    
    return {
        "query": query,
        "context": context,
        "sources": sources,
        "llm_answer": llm_answer,
        "answer": llm_answer or "LLM not configured. Context retrieved successfully.",
        "context_chunks": len(context_chunks),
    }


@router.get("/bases/{kb_id}/graph")
def get_full_graph(
    kb_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return full graph data (nodes + edges) for frontend visualization."""
    kb = db.query(KnowledgeBase).filter(
        KnowledgeBase.id == uuid.UUID(kb_id),
        KnowledgeBase.owner_id == current_user.id,
    ).first()
    if not kb:
        raise HTTPException(404, "Knowledge base not found")

    entities = db.query(GraphEntity).filter(
        GraphEntity.kb_id == kb.id,
        # 融合合并后的实体不再出现在图中（别名已并入存活节点）
        GraphEntity.merged_into.is_(None),
    ).all()
    live_ids = {str(e.id) for e in entities}
    relations = db.query(GraphRelation).filter(GraphRelation.kb_id == kb.id).all()
    # 悬挂边过滤：端点已被合并（merged_into 非空）的边不再渲染——重指 normally
    # 由融合层完成，这里是防御（历史数据/中断任务可能残留端点指向 merged 行）
    relations = [
        r for r in relations
        if str(r.source_id) in live_ids and str(r.target_id) in live_ids
    ]

    nodes = [
        {
            "id": str(e.id),
            "name": e.name,
            "entity_type": e.entity_type,
            "aliases": e.aliases or [],
            "properties": e.properties,
        }
        for e in entities
    ]
    edges = [
        {
            "id": str(r.id),
            "source": str(r.source_id),
            "target": str(r.target_id),
            "relation_type": r.relation_type,
            "properties": r.properties,
        }
        for r in relations
    ]
    return {"nodes": nodes, "edges": edges}


# -------------------------------------------------------------------------------
#  KG pipeline: ontology / async extraction jobs / fusion / graph queries (stage 2-5)
# -------------------------------------------------------------------------------

def _owned_kb(db: Session, kb_id: str, current_user: User) -> KnowledgeBase:
    kb = db.query(KnowledgeBase).filter(
        KnowledgeBase.id == uuid.UUID(kb_id),
        KnowledgeBase.owner_id == current_user.id,
    ).first()
    if not kb:
        raise HTTPException(404, "Knowledge base not found")
    return kb


@router.get("/bases/{kb_id}/graph/ontology")
def get_ontology(
    kb_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    kb = _owned_kb(db, kb_id, current_user)
    from app.models.llm_profile import LLMProfile
    from app.services.kg_ontology import resolve_ontology

    profile = (
        db.query(LLMProfile).filter(LLMProfile.id == kb.kg_llm_profile_id).first()
        if kb.kg_llm_profile_id else None
    )
    return {
        "ontology": resolve_ontology(kb),
        "custom": bool(kb.kg_ontology),
        "kg_llm_profile_id": str(kb.kg_llm_profile_id) if kb.kg_llm_profile_id else None,
        "kg_llm_profile_name": profile.name if profile else None,
    }


@router.get("/bases/{kb_id}/graph/llm-profiles")
def list_llm_profiles_for_kg(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """启用中的 LLM 档案清单（本体设置弹窗的「抽取模型」下拉数据源）。"""
    from app.models.llm_profile import LLMProfile

    rows = db.query(LLMProfile).filter(
        LLMProfile.enabled.is_not(False),
    ).order_by(LLMProfile.is_default.desc(), LLMProfile.created_at.asc()).all()
    return [
        {"id": str(p.id), "name": p.name, "model_id": p.model_id}
        for p in rows
    ]


@router.put("/bases/{kb_id}/graph/ontology")
def put_ontology(
    kb_id: str,
    ontology: dict = Body(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    kb = _owned_kb(db, kb_id, current_user)
    from app.models.llm_profile import LLMProfile
    from app.services.kg_ontology import normalize_ontology

    try:
        kb.kg_ontology = normalize_ontology(ontology)
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    # 抽取专用档案：null/空 = 跟随平台默认档案；指定 id 时校验存在且启用
    profile_id = ontology.get("kg_llm_profile_id")
    if profile_id:
        try:
            pid = uuid.UUID(str(profile_id))
        except (TypeError, ValueError) as error:
            raise HTTPException(422, "kg_llm_profile_id must be a valid UUID") from error
        profile = db.query(LLMProfile).filter(
            LLMProfile.id == pid, LLMProfile.enabled.is_not(False),
        ).first()
        if not profile:
            raise HTTPException(422, "指定的抽取模型档案不存在或已停用")
        kb.kg_llm_profile_id = pid
    else:
        kb.kg_llm_profile_id = None
    db.commit()
    return {"ontology": kb.kg_ontology, "kg_llm_profile_id": profile_id or None}


@router.get("/bases/{kb_id}/graph/extract/jobs")
def list_kg_jobs(
    kb_id: str,
    limit: int = 5,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """该库最近的抽取任务（前端刷新页面后恢复进度跟踪用）。"""
    from app.models.knowledge import KgExtractionJob

    kb = _owned_kb(db, kb_id, current_user)
    jobs = (
        db.query(KgExtractionJob)
        .filter(KgExtractionJob.kb_id == kb.id)
        .order_by(KgExtractionJob.created_at.desc())
        .limit(max(1, min(limit, 20)))
        .all()
    )
    return [
        {
            "id": str(j.id),
            "status": j.status,
            "mode": j.mode,
            "total_units": j.total_units,
            "done_units": j.done_units,
            "entities_found": j.entities_found,
            "relations_found": j.relations_found,
            "error": j.error,
            "created_at": j.created_at.isoformat() if j.created_at else None,
        }
        for j in jobs
    ]


@router.get("/bases/{kb_id}/graph/extract/jobs/{job_id}")
def get_kg_job(
    kb_id: str,
    job_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from app.models.knowledge import KgExtractionJob

    kb = _owned_kb(db, kb_id, current_user)
    job = db.query(KgExtractionJob).filter(
        KgExtractionJob.id == uuid.UUID(job_id),
        KgExtractionJob.kb_id == kb.id,
    ).first()
    if not job:
        raise HTTPException(404, "Job not found")
    total = job.total_units or 0
    done = job.done_units or 0
    return {
        "id": str(job.id),
        "status": job.status,
        "mode": job.mode,
        "total_units": total,
        "done_units": done,
        "progress": round(done / total * 100, 1) if total else 0.0,
        "entities_found": job.entities_found,
        "relations_found": job.relations_found,
        "llm_calls": job.llm_calls,
        "llm_errors": job.llm_errors,
        "error": job.error,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "finished_at": job.finished_at.isoformat() if job.finished_at else None,
    }


@router.post("/bases/{kb_id}/graph/extract/jobs/{job_id}/cancel")
def cancel_kg_job(
    kb_id: str,
    job_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from app.models.knowledge import KgExtractionJob

    kb = _owned_kb(db, kb_id, current_user)
    job = db.query(KgExtractionJob).filter(
        KgExtractionJob.id == uuid.UUID(job_id),
        KgExtractionJob.kb_id == kb.id,
    ).first()
    if not job:
        raise HTTPException(404, "Job not found")
    if job.status in ("pending", "running"):
        job.cancel_requested = True
        db.commit()
    return {"status": job.status, "cancel_requested": True}


@router.get("/bases/{kb_id}/graph/fusion/suggestions")
def list_fusion_suggestions(
    kb_id: str,
    status: str = "pending",
    limit: int = 50,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from app.models.knowledge import KgMergeSuggestion

    kb = _owned_kb(db, kb_id, current_user)
    query = db.query(KgMergeSuggestion).filter(KgMergeSuggestion.kb_id == kb.id)
    if status != "all":
        query = query.filter(KgMergeSuggestion.status == status)
    suggestions = query.order_by(KgMergeSuggestion.created_at.desc()).limit(limit).all()
    by_id = {
        str(e.id): e
        for e in db.query(GraphEntity)
        .filter(GraphEntity.kb_id == kb.id).all()
    }

    def _name(entity_id):
        entity = by_id.get(str(entity_id)) if entity_id else None
        return {"id": str(entity_id), "name": entity.name,
                "type": entity.entity_type} if entity else None

    return [
        {
            "id": str(s.id),
            "type": s.type,
            "status": s.status,
            "method": s.method,
            "similarity": s.similarity,
            "canonical_name": s.canonical_name,
            "entity_a": _name(s.entity_a_id),
            "entity_b": _name(s.entity_b_id),
            "payload": s.payload,
            "apply_record": s.apply_record,
            "created_at": s.created_at.isoformat() if s.created_at else None,
        }
        for s in suggestions
    ]


@router.post("/bases/{kb_id}/graph/fusion/suggestions/{suggestion_id}/accept")
def accept_fusion_suggestion(
    kb_id: str,
    suggestion_id: str,
    resolved: Optional[dict] = Body(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from app.models.knowledge import KgMergeSuggestion
    from app.services.kg_fusion import accept_suggestion
    from app.services.kg_projection import get_projection

    kb = _owned_kb(db, kb_id, current_user)
    suggestion = db.query(KgMergeSuggestion).filter(
        KgMergeSuggestion.id == uuid.UUID(suggestion_id),
        KgMergeSuggestion.kb_id == kb.id,
    ).first()
    if not suggestion:
        raise HTTPException(404, "Suggestion not found")
    if suggestion.status != "pending":
        raise HTTPException(409, f"Suggestion already {suggestion.status}")
    if resolved:
        payload = dict(suggestion.payload or {})
        payload["resolved"] = resolved
        suggestion.payload = payload
    result = accept_suggestion(db, kb, suggestion, decided_by=current_user.id)
    try:
        get_projection().resync_kb(db, kb.id)
    except Exception:  # noqa: BLE001 - 投影失败不阻断审核
        pass
    return result


@router.post("/bases/{kb_id}/graph/fusion/suggestions/{suggestion_id}/reject")
def reject_fusion_suggestion(
    kb_id: str,
    suggestion_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from app.models.knowledge import KgMergeSuggestion
    from app.services.kg_fusion import reject_suggestion

    kb = _owned_kb(db, kb_id, current_user)
    suggestion = db.query(KgMergeSuggestion).filter(
        KgMergeSuggestion.id == uuid.UUID(suggestion_id),
        KgMergeSuggestion.kb_id == kb.id,
    ).first()
    if not suggestion:
        raise HTTPException(404, "Suggestion not found")
    if suggestion.status != "pending":
        raise HTTPException(409, f"Suggestion already {suggestion.status}")
    reject_suggestion(db, suggestion, decided_by=current_user.id)
    return {"status": "rejected"}


@router.post("/bases/{kb_id}/graph/fusion/merge")
def manual_merge_entities(
    kb_id: str,
    source_id: str = Body(...),
    target_id: str = Body(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """手动合并两个实体：source 并入 target（target 存活）。"""
    from app.services.kg_fusion import merge_entities
    from app.services.kg_projection import get_projection

    kb = _owned_kb(db, kb_id, current_user)
    source = db.query(GraphEntity).filter(
        GraphEntity.id == uuid.UUID(source_id), GraphEntity.kb_id == kb.id,
    ).first()
    target = db.query(GraphEntity).filter(
        GraphEntity.id == uuid.UUID(target_id), GraphEntity.kb_id == kb.id,
    ).first()
    if not source or not target:
        raise HTTPException(404, "Entity not found")
    suggestion = merge_entities(db, kb, target, source,
                                method="manual", reason="手动合并")
    try:
        get_projection().resync_kb(db, kb.id)
    except Exception:  # noqa: BLE001
        pass
    return {
        "suggestion_id": str(suggestion.id),
        "apply_record": suggestion.apply_record,
    }


@router.get("/bases/{kb_id}/graph/entities/{entity_id}")
def get_entity_detail(
    kb_id: str,
    entity_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from app.services.kg_fusion import resolve_merged
    from app.services.kg_projection import get_projection

    kb = _owned_kb(db, kb_id, current_user)
    entity = db.query(GraphEntity).filter(
        GraphEntity.id == uuid.UUID(entity_id), GraphEntity.kb_id == kb.id,
    ).first()
    if not entity:
        raise HTTPException(404, "Entity not found")
    entity = resolve_merged(db, entity.id) or entity
    related = []
    try:
        projection = get_projection()
        if projection.available():
            related = projection.related_topk(kb.id, str(entity.id), k=10)
        else:
            from app.services.kg_projection import related_topk_pg

            related = related_topk_pg(db, kb.id, entity.id, k=10)
    except Exception:  # noqa: BLE001
        pass
    props = entity.properties or {}
    return {
        "id": str(entity.id),
        "name": entity.name,
        "entity_type": entity.entity_type,
        "aliases": entity.aliases or [],
        "merged": entity.merged_into is not None,
        "properties": props,
        "attributes": props.get("attributes") or [],
        "doc_ids": props.get("doc_ids") or [],
        "method": props.get("method") or "manual",
        "related": related,
    }


@router.get("/bases/{kb_id}/graph/query/path")
def graph_query_path(
    kb_id: str,
    from_id: str = Query(...),
    to_id: str = Query(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    kb = _owned_kb(db, kb_id, current_user)
    try:
        from app.services.kg_projection import get_projection

        projection = get_projection()
        if projection.available():
            return projection.shortest_path(kb.id, from_id, to_id)
    except Exception:  # noqa: BLE001
        pass
    from app.services.kg_projection import shortest_path_pg

    return shortest_path_pg(db, kb.id, uuid.UUID(from_id), uuid.UUID(to_id))


@router.get("/bases/{kb_id}/graph/query/neighbors/{entity_id}")
def graph_query_neighbors(
    kb_id: str,
    entity_id: str,
    hops: int = 1,
    limit: int = 60,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    kb = _owned_kb(db, kb_id, current_user)
    try:
        from app.services.kg_projection import get_projection

        projection = get_projection()
        if projection.available():
            return projection.neighbors(kb.id, entity_id, hops=hops, limit=limit)
    except Exception:  # noqa: BLE001
        pass
    from app.services.kg_projection import neighbors_pg

    return neighbors_pg(db, kb.id, uuid.UUID(entity_id), hops=hops, limit=limit)


@router.post("/bases/{kb_id}/graph/resync")
def graph_resync(
    kb_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from app.services.kg_projection import get_projection

    kb = _owned_kb(db, kb_id, current_user)
    try:
        counts = get_projection().resync_kb(db, kb.id)
    except Exception as error:  # noqa: BLE001
        raise HTTPException(503, f"neo4j projection unavailable: {error}") from error
    return counts


@router.get("/bases/{kb_id}/graph/neo4j/status")
def graph_neo4j_status(
    kb_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from app.services.kg_projection import get_projection

    kb = _owned_kb(db, kb_id, current_user)
    projection = get_projection()
    if not projection.available():
        pg_entities = db.query(GraphEntity).filter(
            GraphEntity.kb_id == kb.id, GraphEntity.merged_into.is_(None),
        ).count()
        pg_relations = db.query(GraphRelation).filter(
            GraphRelation.kb_id == kb.id,
        ).count()
        return {
            "available": False,
            "pg": {"entities": pg_entities, "relations": pg_relations},
        }
    return projection.status(db, kb.id)

# -------------------------------------------------------------------------------
#  Hybrid Search endpoint
# -------------------------------------------------------------------------------

@router.post("/bases/{kb_id}/search/hybrid")
def hybrid_search(
    kb_id: str,
    query: str = Body(...),
    top_k: int = Body(default=5),
    metric: str = Body(default="cosine"),
    metadata_filter: dict = Body(default=None),
    keyword: str = Body(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Hybrid search: vector similarity + metadata filtering + keyword matching.

    Combines in-memory VectorStore ANN search with optional metadata filters
    (e.g., {"doc_id": "abc"}) and keyword boosting/demotion.
    """
    kb = db.query(KnowledgeBase).filter(
        KnowledgeBase.id == uuid.UUID(kb_id),
        KnowledgeBase.owner_id == current_user.id,
    ).first()
    if not kb:
        raise HTTPException(404, "Knowledge base not found")

    vstore = get_vector_store()
    query_emb = _compute_tfidf_embedding([query], single_text=query)
    query_vec = np.array(json.loads(query_emb), dtype=np.float32)

    results = vstore.search(
        query_vector=query_vec,
        top_k=top_k,
        metadata_filter=metadata_filter,
        keyword=keyword,
    )

    enriched = []
    for r in results:
        chunk = db.query(Chunk).filter(Chunk.id == uuid.UUID(r["id"])).first()
        enriched.append({
            "chunk_id": r["id"],
            "doc_id": str(chunk.doc_id) if chunk else "",
            "content": chunk.content if chunk else r["metadata"].get("content", ""),
            "score": round(r["score"], 4),
            "metadata": r["metadata"],
        })

    return {
        "query": query,
        "results": enriched,
        "top_k": top_k,
        "metadata_filter": metadata_filter,
        "keyword": keyword,
    }


