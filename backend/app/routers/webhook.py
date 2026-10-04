import hashlib
import hmac
import json
from fastapi import APIRouter, Request, Query, HTTPException, Depends
from sqlalchemy.orm import Session
from app.config import settings
from app.database import get_db
from app.models import Contact, Message, Draft
from app.services.rag import generate_rag_reply
from app.services.whatsapp import send_whatsapp_message
from app.services.vectorstore import index_messages

router = APIRouter()

@router.get("/webhook")
async def verify_webhook(
    hub_mode: str = Query(None, alias="hub.mode"),
    hub_challenge: int = Query(None, alias="hub.challenge"),
    hub_verify_token: str = Query(None, alias="hub.verify_token")
):
    if hub_mode == "subscribe" and hub_verify_token == settings.WHATSAPP_VERIFY_TOKEN:
        return hub_challenge
    raise HTTPException(status_code=403, detail="Verification failed")

@router.post("/webhook")
async def webhook_event(request: Request, db: Session = Depends(get_db)):
    raw = await request.body()
    if settings.WHATSAPP_APP_SECRET:
        expected = "sha256=" + hmac.new(settings.WHATSAPP_APP_SECRET.encode(), raw, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, request.headers.get("X-Hub-Signature-256", "")):
            raise HTTPException(status_code=403, detail="Bad signature")
    data = json.loads(raw or b"{}")
    
    try:
        # Simplified parser for WhatsApp Meta Webhook
        for entry in data.get('entry', []):
            for change in entry.get('changes', []):
                value = change.get('value', {})
                if 'messages' in value:
                    for msg in value['messages']:
                        from_number = msg.get('from')
                        text_body = msg.get('text', {}).get('body')
                        
                        if text_body:
                            # 1. Store incoming message
                            contact = db.query(Contact).filter(Contact.phone_number == from_number).first()
                            if not contact:
                                contact = Contact(phone_number=from_number, name=from_number) # basic contact fallback
                                db.add(contact)
                                db.commit()
                                db.refresh(contact)
                                
                            db_message = Message(
                                contact_id=contact.id,
                                content=text_body,
                                direction='incoming'
                            )
                            db.add(db_message)
                            db.commit()
                            
                            # 2. Generate Reply using RAG (retrieve first, then index, so the message
                            # doesn't retrieve itself)
                            reply = generate_rag_reply(db, contact, text_body)
                            index_messages(contact.id, [db_message])
                            
                            # 3. If Auto-Reply, Send and Store
                            if contact.auto_reply_enabled:
                                send_whatsapp_message(from_number, reply)
                                out_msg = Message(
                                    contact_id=contact.id,
                                    content=reply,
                                    direction='outgoing',
                                    source='ai'
                                )
                                db.add(out_msg)
                                db.commit()
                                index_messages(contact.id, [out_msg])
                            else:
                                # Review mode: save the AI draft for approval in the dashboard
                                db.add(Draft(contact_id=contact.id, incoming=text_body, draft=reply))
                                db.commit()
    except Exception as e:
        print(f"Error processing webhook: {e}")
        
    return {"status": "ok"}
