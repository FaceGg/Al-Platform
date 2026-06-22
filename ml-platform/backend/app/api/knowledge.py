"""
Knowledge Base, Knowledge Graph, and RAG API endpoints.
"""
import uuid
import json
import os
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Body, Query
from sqlalchemy.orm import Session
from sqlalchemy import text
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer

from app.database import get_db
from app.models.knowledge import KnowledgeBase, Document, Chunk, GraphEntity, GraphRelation, ChatSession, ChatMessage
from app.models.user import User
from app.api.auth import get_current_user
from app.config import settings

from app.engine.vector_store import get_vector_store

router = APIRouter(prefix="/api/knowledge", tags=["knowledge"])


# -------------------------------------------------------------------------------
#  Utility: TF-IDF embedding helpers
# -------------------------------------------------------------------------------

def _compute_tfidf_embedding(texts, single_text=None):
    """Compute TF-IDF vectors for a list of texts, optionally vectorize a single query."""
    if not texts:
        if single_text is not None:
            vec = TfidfVectorizer()
            vec.fit([single_text])
            emb = vec.transform([single_text]).toarray()[0]
            return json.dumps(emb.tolist())
        return []
    if single_text is not None and not texts:
        vec = TfidfVectorizer()
        vec.fit([single_text])
        emb = vec.transform([single_text]).toarray()[0]
        return json.dumps(emb.tolist())
    vec = TfidfVectorizer()
    vec.fit(texts)
    if single_text is not None:
        emb = vec.transform([single_text]).toarray()[0]
        return json.dumps(emb.tolist())
    embeddings = vec.transform(texts).toarray()
    return [json.dumps(e.tolist()) for e in embeddings]


def _l2_normalize(vec):
    """L2-normalize a numpy vector in-place."""
    norm = np.linalg.norm(vec)
    if norm > 0:
        return vec / norm
    return vec


def _compute_similarity(query_vec, doc_vecs, metric="cosine"):
    """Compute similarity between query vector and document vectors.

    Args:
        query_vec: JSON-encoded query vector string.
        doc_vecs: List of JSON-encoded document vector strings.
        metric: One of 'cosine', 'euclidean', 'dot'.

    Returns:
        numpy array of similarity scores (higher = more similar).
    """
    q = np.array(json.loads(query_vec), dtype=np.float64)
    docs = np.array([json.loads(d) for d in doc_vecs], dtype=np.float64)

    if docs.shape[0] == 0:
        return np.array([])

    if metric == "cosine":
        # L2 normalize for stable cosine similarity
        q_norm = _l2_normalize(q.copy())
        docs_norm = np.array([_l2_normalize(d.copy()) for d in docs])
        similarities = docs_norm.dot(q_norm)
        similarities = np.nan_to_num(similarities, nan=0.0)
        return similarities
    elif metric == "euclidean":
        # Euclidean distance -> higher is better => negative distance
        diffs = docs - q
        distances = np.sqrt(np.sum(diffs * diffs, axis=1))
        return -distances
    elif metric == "dot":
        # Dot product
        return docs.dot(q)
    else:
        # Default to cosine
        q_norm = _l2_normalize(q.copy())
        docs_norm = np.array([_l2_normalize(d.copy()) for d in docs])
        similarities = docs_norm.dot(q_norm)
        similarities = np.nan_to_num(similarities, nan=0.0)
        return similarities


# -------------------------------------------------------------------------------
#  Knowledge Base CRUD
# -------------------------------------------------------------------------------

@router.get("/bases")
def list_bases(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    bases = db.query(KnowledgeBase).filter(KnowledgeBase.owner_id == current_user.id).all()
    return [
        {
            "id": str(b.id),
            "name": b.name,
            "description": b.description,
            "owner_id": str(b.owner_id),
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
    db.delete(kb)
    db.commit()
    return {"message": "Knowledge base deleted"}


# -------------------------------------------------------------------------------
#  Document Management
# -------------------------------------------------------------------------------

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
        file_text = file_bytes.decode("utf-8", errors="replace")
        doc_type = ext.lstrip(".") if ext else "text"
    else:
        filename = "text_input.txt"
        file_text = content
        doc_type = "text"

    if not file_text.strip():
        raise HTTPException(400, "No content provided")

    # Chunk by paragraphs
    paragraphs = [p.strip() for p in file_text.split("\n\n") if p.strip()]
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
    Uses numpy batch computation with L2 normalization.
    When use_vector_store=True, delegates to in-memory VectorStore for faster retrieval.
    """
    kb = db.query(KnowledgeBase).filter(
        KnowledgeBase.id == uuid.UUID(kb_id),
        KnowledgeBase.owner_id == current_user.id,
    ).first()
    if not kb:
        raise HTTPException(404, "Knowledge base not found")

    # Try VectorStore first if enabled
    if use_vector_store:
        vstore = get_vector_store()
        stats = vstore.get_stats()
        if stats["total_vectors"] > 0:
            query_vec = np.array(json.loads(_compute_tfidf_embedding([query], single_text=query)), dtype=np.float32)
            vs_results = vstore.search(query_vec, top_k=top_k)
            if vs_results:
                results = []
                for r in vs_results:
                    chunk_id = r["id"]
                    chunk = db.query(Chunk).filter(Chunk.id == uuid.UUID(chunk_id)).first()
                    results.append({
                        "chunk_id": chunk_id,
                        "doc_id": str(chunk.doc_id) if chunk else "",
                        "content": r["metadata"].get("content", ""),
                        "score": round(r["score"], 4),
                        "source": "vector_store",
                    })
                return results

    chunks = db.query(Chunk).join(Document).filter(
        Document.kb_id == kb.id,
        Chunk.embedding != "",
    ).all()

    if not chunks:
        return []

    chunk_texts = [c.content for c in chunks]
    chunk_embs = [c.embedding for c in chunks]

    # Vectorize query using same corpus
    query_emb = _compute_tfidf_embedding(chunk_texts, single_text=query)

    # Compute similarities with chosen metric
    scores = _compute_similarity(query_emb, chunk_embs, metric=metric)

    # Get top_k indices (higher score = more similar)
    top_indices = np.argsort(scores)[::-1][:top_k]

    results = []
    for idx in top_indices:
        if scores[idx] is not None:
            results.append({
                "chunk_id": str(chunks[idx].id),
                "doc_id": str(chunks[idx].doc_id),
                "content": chunk_texts[idx],
                "score": round(float(scores[idx]), 4),
                "source": "tfidf",
            })
    return results


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
    llm_api_url: str = Body(default=None),
    top_k: int = Body(default=5),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
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

    # Step 4: Call LLM API
    api_url = llm_api_url or settings.llm_api_url
    api_key = settings.llm_api_key
    model = settings.llm_model

    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    import requests
    try:
        resp = requests.post(
            api_url,
            headers=headers,
            json={
                "model": model,
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

    messages = request.get("messages", [])
    session_id_str = request.get("session_id")
    llm_api_url_override = request.get("llm_api_url")
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

    # Step 5: Call LLM API
    api_url = llm_api_url_override or settings.llm_api_url
    api_key = settings.llm_api_key
    model = settings.llm_model

    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    import requests
    try:
        resp = requests.post(
            api_url,
            headers=headers,
            json={
                "model": model,
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
