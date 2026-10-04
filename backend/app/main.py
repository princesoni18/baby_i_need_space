from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.routers import webhook, api
from apscheduler.schedulers.background import BackgroundScheduler
from app.database import engine, Base

# Create tables
Base.metadata.create_all(bind=engine)

# Lightweight migration: older databases lack messages.source
from sqlalchemy import inspect, text
if "source" not in [c["name"] for c in inspect(engine).get_columns("messages")]:
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE messages ADD COLUMN source VARCHAR DEFAULT 'human'"))

app = FastAPI(title="WhatsApp AI Companion")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(webhook.router, tags=["Webhook"])
app.include_router(api.router, tags=["Dashboard"])

scheduler = BackgroundScheduler()
scheduler.add_job(api.send_due_messages, "interval", seconds=20)


@app.on_event("startup")
def start_scheduler():
    scheduler.start()


@app.on_event("shutdown")
def stop_scheduler():
    scheduler.shutdown(wait=False)

@app.get("/")
def read_root():
    return {"status": "AI Companion Backend Running"}
