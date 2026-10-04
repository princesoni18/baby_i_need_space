"""Learns how the account owner texts, from every outgoing message across all uploaded chats."""
import json
import random
import re
import statistics
from collections import Counter
from datetime import datetime

from sqlalchemy.orm import Session

from app.models import Message, StyleProfile
from app.services.llm import generate_reply

_EMOJI = re.compile("[\U0001F300-\U0001FAFF☀-➿]")
_JUNK = re.compile(r"<[^>]*omitted>|https?://|^null$", re.I)


def is_junk(text: str) -> bool:
    return not text or not text.strip() or bool(_JUNK.search(text))


def owner_messages(db: Session) -> list[str]:
    rows = (
        db.query(Message.content)
        .filter(Message.direction == "outgoing", Message.source != "ai")
        .order_by(Message.id)
        .all()
    )
    return [r[0].strip() for r in rows if not is_junk(r[0])]


def compute_stats(msgs: list[str]) -> dict:
    words = [len(m.split()) for m in msgs]
    tokens = Counter(w for m in msgs for w in re.findall(r"[a-zA-Z']+", m.lower()))
    return {
        "median_words": statistics.median(words),
        "p90_words": sorted(words)[int(len(words) * 0.9)],
        "emoji_share": round(sum(bool(_EMOJI.search(m)) for m in msgs) / len(msgs), 2),
        "all_lowercase_share": round(sum(m == m.lower() for m in msgs) / len(msgs), 2),
        "ends_with_period_share": round(sum(m.rstrip().endswith(".") for m in msgs) / len(msgs), 2),
        "question_share": round(sum("?" in m for m in msgs) / len(msgs), 2),
        "top_words": [w for w, _ in tokens.most_common(45)],
    }


def rebuild_profile(db: Session) -> StyleProfile | None:
    msgs = owner_messages(db)
    if len(msgs) < 10:
        return None
    stats = compute_stats(msgs)
    sample = random.Random(1).sample(msgs, min(150, len(msgs)))
    prompt = (
        "Below are real WhatsApp messages written by one person (one per line), plus stats about them.\n"
        "Write a style guide, max 150 words, that lets someone else write new messages indistinguishable "
        "from this person's. Cover: language mix and script (e.g. romanized Hinglish), typical length, "
        "spelling shortcuts and slang they actually use (quote real examples), casing, punctuation, emoji, "
        "how they open and close, tone. Describe only what the data shows.\n\n"
        f"STATS: {json.dumps(stats)}\n\nMESSAGES:\n" + "\n".join(sample)
    )
    summary = generate_reply(prompt, temperature=0.3, max_tokens=700).strip()
    p = db.query(StyleProfile).first() or StyleProfile()
    p.summary, p.stats, p.sample_size, p.updated_at = summary, json.dumps(stats), len(msgs), datetime.utcnow()
    db.add(p)
    db.commit()
    return p


def get_profile(db: Session) -> StyleProfile | None:
    return db.query(StyleProfile).first()


def style_examples(db: Session, n: int = 25) -> list[str]:
    """Random real short messages from the owner, as few-shot style samples."""
    msgs = [m for m in owner_messages(db) if len(m.split()) <= 25]
    return random.sample(msgs, min(n, len(msgs)))


def real_pairs(db: Session, n: int = 8) -> list[tuple[str, str]]:
    """Random real (friend message, owner's reply) pairs from imported chats, for few-shot examples
    that work even when retrieval finds nothing relevant."""
    rows = db.query(Message).order_by(Message.id).all()
    pairs = []
    for a, b in zip(rows, rows[1:]):
        if (
            a.direction == "incoming" and b.direction == "outgoing" and a.contact_id == b.contact_id
            and b.source != "ai" and not is_junk(a.content) and not is_junk(b.content)
            and len(a.content.split()) <= 15 and len(b.content.split()) <= 15
        ):
            pairs.append((a.content.strip(), b.content.strip()))
    return random.sample(pairs, min(n, len(pairs)))
