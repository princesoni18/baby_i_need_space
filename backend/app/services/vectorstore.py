"""Pinecone-backed semantic memory for chat messages.

The index uses Pinecone's integrated embedding (text field "text"), so we send raw text.
Each contact gets its own namespace, "chat-<contact_id>", so nothing else in the index is touched.
"""
from typing import Iterable

from pinecone import Pinecone

from app.config import settings

_index = None


def _get_index():
    global _index
    if _index is None:
        pc = Pinecone(api_key=settings.PINECONE_API_KEY)
        _index = pc.Index(host=pc.describe_index(settings.PINECONE_INDEX_NAME).host)
    return _index


def _ns(contact_id: int) -> str:
    return f"chat-{contact_id}"


def index_messages(contact_id: int, messages: Iterable) -> int:
    """Upsert Message rows into Pinecone. Never raises: RAG is best effort."""
    records = [
        {"_id": f"m{m.id}", "text": m.content[:4000], "direction": m.direction}
        for m in messages
        if m.content and m.content.strip()
    ]
    try:
        ix = _get_index()
        for i in range(0, len(records), 90):
            ix.upsert_records(namespace=_ns(contact_id), records=records[i : i + 90])
        return len(records)
    except Exception as e:
        print(f"Pinecone index error: {e}")
        return 0


def search_similar(contact_id: int, text: str, top_k: int = 15, other_contacts: Iterable[int] = (), keep: int = 6) -> list[tuple[int, float]]:
    """(message id, relevance score) pairs, best first, over this contact's chat and the owner's other chats.

    Step 1 is plain vector search (top_k candidates). Step 2 reranks those candidates with a cross-encoder
    (bge-reranker-v2-m3), which actually reads query and candidate together, so scores separate relevant
    from merely word-similar messages. Scores are comparable across chats because the query is the same."""
    out = []
    for cid in dict.fromkeys([contact_id, *other_contacts]):
        try:
            res = _get_index().search(
                namespace=_ns(cid),
                top_k=top_k,
                inputs={"text": text},
                rerank={"model": "bge-reranker-v2-m3", "top_n": keep, "rank_fields": ["text"]},
            )
            hits = res.result.hits if hasattr(res, "result") else res["result"]["hits"]
            for h in hits:
                hid = h.id if hasattr(h, "id") else h["_id"]
                score = h.score if hasattr(h, "score") else h["_score"]
                out.append((int(str(hid).lstrip("m")), float(score)))
        except Exception as e:
            print(f"Pinecone search error ({_ns(cid)}): {e}")
    return sorted(out, key=lambda x: -x[1])


def delete_messages(contact_id: int, ids: list[int]):
    try:
        for i in range(0, len(ids), 900):
            _get_index().delete(ids=[f"m{x}" for x in ids[i : i + 900]], namespace=_ns(contact_id))
    except Exception as e:
        print(f"Pinecone delete error: {e}")
