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

    # Chunk by paragraphs; extracted office/pdf content is repacked to a
    # retrieval-friendly granularity, plain text keeps its own blank lines.
    paragraphs = [p.strip() for p in file_text.split("\n\n") if p.strip()]
    if doc_type in ("pdf", "docx", "xlsx", "xlsm"):
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
    for i, (para, emb_str) in enumerate(zip(paragraphs, embedding_strs)):
        chunk = Chunk(
            doc_id=doc.id,
            content=para,
            chunk_index=i,
            embedding=emb_str,
        )
        db.add(chunk)

    db.commit()
    db.refresh(doc)
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
        }
        for d in docs
    ]


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

    # Step 3: Build prompt
    prompt = f"Based on the following materials, answer the question:\n{context}\n\nQuestion: {query}"

    # Step 4: Call LLM API through the gateway
    config = resolve_llm_profile(db, purpose="knowledge_rag")

    headers = {"Content-Type": "application/json"}
    if config.api_key:
        headers["Authorization"] = f"Bearer {config.api_key}"

    import requests
    try:
        resp = requests.post(
            config.api_url,
            headers=headers,
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
        sources_data = [{"content": r["content"], "score": r["score"]} for r in search_results]

    # Step 3: Build LLM messages with context + conversation history
    system_msg = {
        "role": "system",
        "content": f"You are a helpful assistant. Use the following context to answer the user's question. If the context doesn't contain relevant information, say so.\n\nContext:\n{context}" if context else "You are a helpful assistant.",
    }

    llm_messages = [system_msg] + messages

    # Step 4: Save user message
    user_msg = ChatMessage(
        session_id=session.id,
        role="user",
        content=last_user_msg,
        sources=[],
    )
    db.add(user_msg)

    # Step 5: Call LLM API through the gateway
    config = resolve_llm_profile(db, purpose="knowledge_chat")

    headers = {"Content-Type": "application/json"}
    if config.api_key:
        headers["Authorization"] = f"Bearer {config.api_key}"

    import requests
    try:
        resp = requests.post(
            config.api_url,
            headers=headers,
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
    entity = GraphEntity(kb_id=kb.id, name=name, entity_type=entity_type, properties=properties)
    db.add(entity)
    db.commit()
    db.refresh(entity)
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
    return {"message": "Entity deleted"}


@router.get("/bases/{kb_id}/graph/relations")
def list_relations(
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
    relations = db.query(GraphRelation).filter(GraphRelation.kb_id == kb.id).all()
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
    return {"message": "Relation deleted"}


@router.post("/bases/{kb_id}/graph/extract")
def extract_kb_graph_endpoint(
    kb_id: str,
    doc_ids: Optional[list[str]] = Body(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Rebuild the auto knowledge-graph layer from document content.

    Deterministic rules + statistics (jieba noun phrases, co-occurrence,
    is_a/part_of patterns). Entities/relations created by the user manually
    are never modified or deleted; only rows tagged properties.source="auto"
    are replaced. Without doc_ids every document of the KB is used.
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
    vstore = get_vector_store()
    query_emb = _compute_tfidf_embedding([query], single_text=query)
    query_vec = np.array(json.loads(query_emb), dtype=np.float32)
    results = vstore.search(query_vec, top_k=top_k)
    
    context_chunks = []
    sources = []
    for r in results:
        chunk = db.query(Chunk).filter(Chunk.id == uuid.UUID(r["id"])).first()
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

    entities = db.query(GraphEntity).filter(GraphEntity.kb_id == kb.id).all()
    relations = db.query(GraphRelation).filter(GraphRelation.kb_id == kb.id).all()

    nodes = [
        {
            "id": str(e.id),
            "name": e.name,
            "entity_type": e.entity_type,
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


