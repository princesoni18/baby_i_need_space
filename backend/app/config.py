from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    # --- Required ---
    DATABASE_URL: str = "sqlite:///./app.db"
    WHATSAPP_TOKEN: str
    WHATSAPP_PHONE_NUMBER_ID: str
    WHATSAPP_VERIFY_TOKEN: str

    # --- Optional: security ---
    WHATSAPP_APP_SECRET: str = ""  # if set, webhook POSTs must carry a valid X-Hub-Signature-256

    # --- LLM providers (set at least one of GROQ_API_KEY / GEMINI_API_KEY) ---
    GROQ_API_KEY: str = ""
    GROQ_MODEL: str = "openai/gpt-oss-120b"
    GEMINI_API_KEY: str = ""
    MODEL_NAME: str = "gemini-2.5-flash"
    FALLBACK_MODEL: str = "gemini-2.5-flash-lite"

    # --- Optional: semantic memory (RAG) ---
    PINECONE_API_KEY: str = ""
    PINECONE_INDEX_NAME: str = ""

    # --- Personality ---
    OWNER_NAME: str = "Me"  # your first name; the AI replies as this person
    AI_TONE: str = "casual"
    AI_LANGUAGE: str = "Hinglish"

    class Config:
        env_file = ".env"
        extra = "ignore"  # tolerate unknown / old variables in .env

settings = Settings()
