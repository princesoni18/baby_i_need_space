import re
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Contact, Message, ScheduledMessage, Draft
from app.services.whatsapp import send_whatsapp_message
from app.services.vectorstore import index_messages
from app.services.style import is_junk, rebuild_profile, get_profile

router = APIRouter(prefix="/api")


class ContactIn(BaseModel):
    phone_number: str
    name: Optional[str] = None
    auto_reply_enabled: bool = False


class ContactPatch(BaseModel):
    name: Optional[str] = None
    auto_reply_enabled: Optional[bool] = None


class ScheduleIn(BaseModel):
    contact_id: int
    content: str
    scheduled_at: datetime  # ISO string; timezone-aware values are converted to UTC


class HistoryIn(BaseModel):
    text: str
    my_name: str  # the sender name in the export that is "you" (their messages become incoming)


def _contact_out(c: Contact):
    return {
        "id": c.id,
        "name": c.name,
        "phone_number": c.phone_number,
        "auto_reply_enabled": bool(c.auto_reply_enabled),
        "message_count": len(c.messages),
    }


def _utc_naive(dt: datetime) -> datetime:
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


@router.get("/contacts")
def list_contacts(db: Session = Depends(get_db)):
    return [_contact_out(c) for c in db.query(Contact).order_by(Contact.id.desc()).all()]


@router.post("/contacts")
def add_contact(body: ContactIn, db: Session = Depends(get_db)):
    phone = re.sub(r"\D", "", body.phone_number)
    if not phone:
        raise HTTPException(400, "Phone number required (digits with country code)")
    if db.query(Contact).filter(Contact.phone_number == phone).first():
        raise HTTPException(409, "Contact already exists")
    c = Contact(phone_number=phone, name=body.name or phone, auto_reply_enabled=body.auto_reply_enabled)
    db.add(c)
    db.commit()
    db.refresh(c)
    return _contact_out(c)


@router.patch("/contacts/{contact_id}")
def update_contact(contact_id: int, body: ContactPatch, db: Session = Depends(get_db)):
    c = db.get(Contact, contact_id)
    if not c:
        raise HTTPException(404, "Contact not found")
    if body.name is not None:
        c.name = body.name
    if body.auto_reply_enabled is not None:
        c.auto_reply_enabled = body.auto_reply_enabled
    db.commit()
    return _contact_out(c)


@router.get("/contacts/{contact_id}/messages")
def contact_messages(contact_id: int, db: Session = Depends(get_db)):
    msgs = (
        db.query(Message)
        .filter(Message.contact_id == contact_id)
        .order_by(Message.timestamp.desc())
        .limit(100)
        .all()[::-1]
    )
    return [
        {"id": m.id, "content": m.content, "direction": m.direction, "timestamp": m.timestamp.isoformat()}
        for m in msgs
    ]


# WhatsApp export lines, e.g. "12/03/2024, 10:45 - Name: hi" or "[12/03/24, 10:45:12 AM] Name: hi"
_LINE = re.compile(
    r"^\[?(\d{1,2}[/.\-]\d{1,2}[/.\-]\d{2,4}),?\s+(\d{1,2}:\d{2}(?::\d{2})?(?:\s?[APap][Mm])?)\]?\s*[-–]?\s*([^:]+?):\s(.*)$"
)


_STAMP = re.compile(r"^\[?\d{1,2}[/.\-]\d{1,2}[/.\-]\d{2,4},?\s+\d{1,2}:\d{2}")


def _parse_ts(date_s: str, time_s: str) -> datetime:
    d = re.split(r"[/.\-]", date_s)
    a, b, y = int(d[0]), int(d[1]), int(d[2])
    if y < 100:
        y += 2000
    day, month = (a, b) if a <= 31 and b <= 12 else (b, a)
    t = time_s.strip().upper().replace(" ", "")
    for fmt in ("%I:%M:%S%p", "%I:%M%p", "%H:%M:%S", "%H:%M"):
        try:
            tt = datetime.strptime(t, fmt)
            return datetime(y, month, day, tt.hour, tt.minute, tt.second)
        except ValueError:
            continue
    return datetime(y, month, day)


@router.post("/contacts/{contact_id}/history")
def upload_history(contact_id: int, body: HistoryIn, db: Session = Depends(get_db)):
    c = db.get(Contact, contact_id)
    if not c:
        raise HTTPException(404, "Contact not found")
    me = body.my_name.strip().lower()
    parsed = []
    for raw in body.text.splitlines():
        line = raw.strip("‎‏﻿ ")
        m = _LINE.match(line)
        if m:
            date_s, time_s, sender, text = m.groups()
            parsed.append([_parse_ts(date_s, time_s), sender.strip(), text])
        elif _STAMP.match(line):
            continue  # timestamped system line (call, join, encryption notice): not part of any message
        elif parsed and line:
            parsed[-1][2] += "\n" + line  # continuation of a multi-line message
    added = 0
    rows = []
    for ts, sender, text in parsed:
        if is_junk(text) or "message was deleted" in text:
            continue
        row = Message(
            contact_id=c.id,
            content=text,
            direction="outgoing" if sender.lower() == me else "incoming",
            timestamp=ts,
        )
        db.add(row)
        rows.append(row)
        added += 1
    db.commit()
    indexed = index_messages(c.id, rows)
    try:
        rebuild_profile(db)
    except Exception as e:
        print(f"Style profile rebuild failed: {e}")
    if added == 0:
        raise HTTPException(400, "No messages recognised. Upload a WhatsApp 'Export chat' .txt file.")
    return {"imported": added, "indexed": indexed}


@router.get("/scheduled")
def list_scheduled(db: Session = Depends(get_db)):
    rows = db.query(ScheduledMessage).order_by(ScheduledMessage.scheduled_at.desc()).all()
    return [
        {
            "id": s.id,
            "contact_id": s.contact_id,
            "contact_name": s.contact.name if s.contact else None,
            "content": s.content,
            "scheduled_at": s.scheduled_at.isoformat() + "Z",
            "status": s.status,
        }
        for s in rows
    ]


@router.post("/scheduled")
def schedule_message(body: ScheduleIn, db: Session = Depends(get_db)):
    if not db.get(Contact, body.contact_id):
        raise HTTPException(404, "Contact not found")
    s = ScheduledMessage(contact_id=body.contact_id, content=body.content, scheduled_at=_utc_naive(body.scheduled_at))
    db.add(s)
    db.commit()
    return {"id": s.id}


@router.delete("/scheduled/{sid}")
def cancel_scheduled(sid: int, db: Session = Depends(get_db)):
    s = db.get(ScheduledMessage, sid)
    if not s:
        raise HTTPException(404, "Not found")
    if s.status == "pending":
        s.status = "cancelled"
        db.commit()
    return {"status": s.status}


def send_due_messages():
    """Called by the scheduler: send every pending message whose time has come."""
    from app.database import SessionLocal

    db = SessionLocal()
    try:
        due = (
            db.query(ScheduledMessage)
            .filter(ScheduledMessage.status == "pending", ScheduledMessage.scheduled_at <= datetime.utcnow())
            .all()
        )
        for s in due:
            try:
                send_whatsapp_message(s.contact.phone_number, s.content)
                s.status = "sent"
                sent = Message(contact_id=s.contact_id, content=s.content, direction="outgoing")
                db.add(sent)
                db.flush()
                index_messages(s.contact_id, [sent])
            except Exception as e:
                print(f"Scheduled send {s.id} failed: {e}")
                s.status = "failed"
            db.commit()
    finally:
        db.close()


@router.get("/style")
def style(db: Session = Depends(get_db)):
    p = get_profile(db)
    if not p:
        return {"summary": None}
    return {"summary": p.summary, "sample_size": p.sample_size, "updated_at": p.updated_at.isoformat() + "Z"}


@router.post("/style/rebuild")
def style_rebuild(db: Session = Depends(get_db)):
    p = rebuild_profile(db)
    if not p:
        raise HTTPException(400, "Need at least 10 of your own messages. Upload a chat first.")
    return {"summary": p.summary, "sample_size": p.sample_size}


class DraftSend(BaseModel):
    text: Optional[str] = None  # edited text; defaults to the AI draft


@router.get("/drafts")
def list_drafts(db: Session = Depends(get_db)):
    rows = db.query(Draft).filter(Draft.status == "pending").order_by(Draft.id.desc()).all()
    return [
        {"id": d.id, "contact_id": d.contact_id, "contact_name": d.contact.name, "incoming": d.incoming,
         "draft": d.draft, "created_at": d.created_at.isoformat() + "Z"}
        for d in rows
    ]


@router.post("/drafts/{did}/send")
def send_draft(did: int, body: DraftSend, db: Session = Depends(get_db)):
    d = db.get(Draft, did)
    if not d or d.status != "pending":
        raise HTTPException(404, "Draft not found")
    text = (body.text or d.draft).strip()
    send_whatsapp_message(d.contact.phone_number, text)
    msg = Message(contact_id=d.contact_id, content=text, direction="outgoing", source="ai" if text == d.draft.strip() else "human")
    db.add(msg)
    d.status = "sent"
    db.commit()
    index_messages(d.contact_id, [msg])
    return {"status": "sent"}


@router.delete("/drafts/{did}")
def dismiss_draft(did: int, db: Session = Depends(get_db)):
    d = db.get(Draft, did)
    if d and d.status == "pending":
        d.status = "dismissed"
        db.commit()
    return {"status": "dismissed"}
