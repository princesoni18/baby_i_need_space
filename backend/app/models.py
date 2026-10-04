from sqlalchemy import Column, Integer, String, Text, DateTime, Boolean, ForeignKey, Float
from sqlalchemy.orm import relationship
from app.database import Base
from datetime import datetime

class Contact(Base):
    __tablename__ = "contacts"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True)
    phone_number = Column(String, unique=True, index=True)
    auto_reply_enabled = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    messages = relationship("Message", back_populates="contact")
    memories = relationship("Memory", back_populates="contact")
    scheduled_messages = relationship("ScheduledMessage", back_populates="contact")

class Message(Base):
    __tablename__ = "messages"
    
    id = Column(Integer, primary_key=True, index=True)
    contact_id = Column(Integer, ForeignKey("contacts.id"))
    content = Column(Text)
    direction = Column(String)  # 'incoming' or 'outgoing'
    source = Column(String, default="human")  # 'human' = written by the owner, 'ai' = written by the AI
    timestamp = Column(DateTime, default=datetime.utcnow)
    
    # pgvector column for semantic search (commented out for local testing without postgres)
    # embedding = Column(Vector(768))
    
    contact = relationship("Contact", back_populates="messages")

class Memory(Base):
    __tablename__ = "memories"
    
    id = Column(Integer, primary_key=True, index=True)
    contact_id = Column(Integer, ForeignKey("contacts.id"))
    content = Column(Text)
    confidence = Column(Float)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    contact = relationship("Contact", back_populates="memories")

class ScheduledMessage(Base):
    __tablename__ = "scheduled_messages"
    
    id = Column(Integer, primary_key=True, index=True)
    contact_id = Column(Integer, ForeignKey("contacts.id"))
    content = Column(Text)
    scheduled_at = Column(DateTime)
    status = Column(String, default="pending")  # pending, sent, cancelled
    
    contact = relationship("Contact", back_populates="scheduled_messages")

class AIPersonality(Base):
    __tablename__ = "ai_personality"
    
    id = Column(Integer, primary_key=True, index=True)
    tone = Column(String, default="casual")
    language = Column(String, default="Hinglish")
    emoji_usage = Column(String, default="medium")
    humor = Column(String, default="high")
    rules = Column(Text)  # JSON string of "do not say" rules


class StyleProfile(Base):
    __tablename__ = "style_profile"

    id = Column(Integer, primary_key=True, index=True)
    summary = Column(Text)  # LLM-written guide to how the owner texts
    stats = Column(Text)  # JSON: length, emoji, casing, slang stats
    sample_size = Column(Integer, default=0)
    updated_at = Column(DateTime, default=datetime.utcnow)


class Draft(Base):
    __tablename__ = "drafts"

    id = Column(Integer, primary_key=True, index=True)
    contact_id = Column(Integer, ForeignKey("contacts.id"))
    incoming = Column(Text)
    draft = Column(Text)
    status = Column(String, default="pending")  # pending, sent, dismissed
    created_at = Column(DateTime, default=datetime.utcnow)

    contact = relationship("Contact")
