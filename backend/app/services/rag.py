import json
import re
from sqlalchemy.orm import Session
from app.models import Message, Contact, AIPersonality, Memory
from app.services.llm import generate_chat
from app.services.vectorstore import search_similar
from app.services.style import get_profile, real_pairs, is_junk
from app.config import settings


MIN_RELEVANCE = 0.08  # reranker score; on real data relevant hits scored 0.1-1.0 and noise below 0.05
MAX_RELEVANT = 6


def retrieve_relevant_messages(db: Session, query_text: str, contact_id: int, limit: int = MAX_RELEVANT):
    """Relevant past messages, filtered in four steps:
    1. vector search + cross-encoder rerank (vectorstore.search_similar)
    2. drop anything scoring below MIN_RELEVANCE, so an unrelated chat adds nothing instead of noise
    3. drop media placeholders, links and anything the AI itself wrote earlier
    4. for each hit from a friend, attach the owner's real reply that followed it."""
    if not settings.PINECONE_API_KEY:
        return []
    scored = search_similar(contact_id, query_text, other_contacts=[c.id for c in db.query(Contact.id).all()])
    scored = [(i, sc) for i, sc in scored if sc >= MIN_RELEVANCE][:limit]
    if not scored:
        print(f"RAG: nothing relevant for {query_text[-60:]!r}")
        return []
    hits = {m.id: m for m in db.query(Message).filter(Message.id.in_([i for i, _ in scored])).all()}
    results, seen = [], set()
    for i, sc in scored:
        m = hits.get(i)
        if not m or is_junk(m.content) or m.source == "ai":
            continue
        group = [m]
        if m.direction == "incoming":
            reply = db.query(Message).filter(
                Message.contact_id == m.contact_id, Message.direction == "outgoing", Message.id > m.id
            ).order_by(Message.id).first()
            if reply and not is_junk(reply.content) and reply.source != "ai":
                group.append(reply)
        for g in group:
            if g.id not in seen:
                seen.add(g.id)
                results.append(g)
        print(f"RAG: kept {sc:.2f} {m.direction} {m.content[:50]!r}")
    return results


def get_recent_context(db: Session, contact_id: int, limit: int = 10):
    return db.query(Message).filter(Message.contact_id == contact_id)\
        .order_by(Message.timestamp.desc()).limit(limit).all()[::-1]


def _pair_lines(relevant: list[Message], extra: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """(friend line, owner reply) pairs: retrieved ones first, then random real ones, no duplicates."""
    pairs, seen = [], set()
    for m in sorted(relevant, key=lambda x: x.id):
        if m.direction == "incoming" and m.content not in seen:
            nxt = [r for r in relevant if r.direction == "outgoing" and r.contact_id == m.contact_id and r.id > m.id]
            if nxt:
                seen.add(m.content)
                pairs.append((m.content, min(nxt, key=lambda r: r.id).content))
    for a, b in extra:
        if a not in seen and len(pairs) < 10:
            seen.add(a)
            pairs.append((a, b))
    return pairs


def build_messages(db: Session, contact: Contact, recent: list[Message], relevant: list[Message],
                   memories: list[Memory], personality: AIPersonality, current_message: str) -> list[dict]:
    """A real chat: system prompt (who you are, how you text, real examples) plus the conversation as
    alternating friend (user) / owner (assistant) turns, ending with the friend's latest message."""
    profile = get_profile(db)
    stats = json.loads(profile.stats) if profile else {}
    owner = settings.OWNER_NAME
    words = ", ".join(stats.get("top_words", [])[:30])
    length = f"Your messages are usually {stats['median_words']:.0f} to {stats['p90_words']} words. " if stats else ""
    summary = profile.summary if profile else f"{personality.tone} tone, {personality.language}"

    system = (
        f"You are {owner}, texting your friend {contact.name} on WhatsApp. You are a real person chatting, "
        f"not an assistant.\n"
        f"Reply to what they just said, the way {owner} would, in one short WhatsApp message.\n\n"
        f"How {owner} texts:\n{summary}\n"
        f"{length}Words and spellings you use a lot: {words}\n"
        f"Copy that spelling and casing. Use emojis or full stops only if {owner} would.\n\n"
        "How to chat well:\n"
        "- React to what they actually said. If they ask a question, answer it. If they joke or insult, joke "
        "back. If they say something is happening, respond with a natural comment or a question about it.\n"
        "- Never answer with vague filler, never just repeat their words back, never ask a question you "
        "already asked.\n"
        f"- You are {owner}: if they say \"{owner}\", \"tu\", \"tum\" or \"aap\", they mean you. Speak in first person.\n"
        "- Output only the message text: no quotes, no name prefix, no explanation.\n"
        f"Rules: {personality.rules or 'None'}\n"
    )
    pairs = _pair_lines(relevant, real_pairs(db, 8))
    if pairs:
        system += (
            f"\nReal examples of how {owner} replied to friends "
            "(copy the voice and the way of answering, not the words):\n"
        )
        for q, a in pairs:
            system += f"Friend: {q}\n{owner}: {a}\n"
    if memories:
        system += "\nThings you know about this friend:\n" + "".join(f"- {m.content}\n" for m in memories)

    turns: list[dict] = []
    for m in recent[-10:]:
        role = "assistant" if m.direction == "outgoing" else "user"
        if turns and turns[-1]["role"] == role:
            turns[-1]["content"] += "\n" + m.content
        else:
            turns.append({"role": role, "content": m.content})
    # make sure the conversation ends with the friend's latest message
    if not turns or turns[-1]["role"] != "user" or current_message not in turns[-1]["content"]:
        if turns and turns[-1]["role"] == "user":
            turns[-1]["content"] += "\n" + current_message
        else:
            turns.append({"role": "user", "content": current_message})
    while turns and turns[0]["role"] != "user":
        turns.pop(0)
    return [{"role": "system", "content": system}] + turns


def clean_reply(text: str) -> str:
    text = text.strip().strip('"').strip()
    text = re.sub(r"^(Me|Owner|" + re.escape(settings.OWNER_NAME) + r")\s*:\s*", "", text, flags=re.I)
    return text.strip()


def generate_rag_reply(db: Session, contact: Contact, current_message: str):
    recent = get_recent_context(db, contact.id, limit=12)
    # Short messages like "hn bhai bolo" mean little alone: search with the last few lines as context
    before = [m.content for m in recent if m.content != current_message][-2:]
    relevant = retrieve_relevant_messages(db, " ".join(before + [current_message]), contact.id)

    personality = db.query(AIPersonality).first() or AIPersonality()
    memories = db.query(Memory).filter(Memory.contact_id == contact.id).all()

    messages = build_messages(db, contact, recent, relevant, memories, personality, current_message)
    return clean_reply(generate_chat(messages))
