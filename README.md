# WhatsApp AI Companion

An AI that replies to your WhatsApp messages the way **you** would. It learns your texting style from your own exported chats, remembers past conversations, and either sends replies automatically or leaves drafts for you to approve. It also has a small dashboard to schedule messages and manage contacts.

> **Heads up:** this is a personal project, not a hardened product. The dashboard has **no login**, so run it on your own machine or behind your own access control (see [Security](#security)).

## What it does

- **Replies in your voice.** A style profile (length, spelling shortcuts, slang, language mix) is learned from your sent messages and fed to the model with real examples of how you answered friends.
- **Remembers old chats (RAG).** Your chat history is stored in a Pinecone index. For each incoming message it finds similar past moments, re-ranks them with a cross-encoder, and drops anything not actually relevant.
- **Per-contact control.** Turn AI auto-reply on or off per contact. With it off, the AI writes a draft you can edit and send from the dashboard.
- **Scheduled messages.** Queue a message for a contact at a chosen time.
- **Chat history upload.** Import a WhatsApp "Export chat" `.txt` for any contact.
- **Multiple LLM providers.** Groq first, then Gemini, with automatic fallback when a free-tier quota runs out.

## Architecture

```
WhatsApp user ──> Meta Cloud API ──> POST /webhook (FastAPI)
                                        │
                                        ├─ store message (SQLite/Postgres)
                                        ├─ retrieve similar past messages (Pinecone + reranker)
                                        ├─ build prompt: style profile + real example pairs + recent chat
                                        ├─ generate reply (Groq / Gemini)
                                        └─ auto-send via Cloud API, or save a draft for the dashboard
Dashboard (React) <──> /api/* (contacts, drafts, schedule, uploads, style)
```

| Path | Purpose |
|---|---|
| `backend/app/routers/webhook.py` | Meta webhook: verification and incoming messages |
| `backend/app/routers/api.py` | Dashboard API: contacts, drafts, scheduling, chat import, style |
| `backend/app/services/rag.py` | Retrieval, relevance filtering and prompt building |
| `backend/app/services/style.py` | Learns your texting style from your messages |
| `backend/app/services/vectorstore.py` | Pinecone indexing and search |
| `backend/app/services/llm.py` | Groq and Gemini calls with fallback |
| `frontend/src/App.jsx` | Dashboard UI |

## Requirements

- **Python 3.11 or 3.12.** The pinned dependencies have no prebuilt wheels for 3.13+ on some platforms.
- [uv](https://docs.astral.sh/uv/) (or plain `pip`)
- Node.js 18+ (for the dashboard)
- A Meta developer account, plus accounts for the LLM / vector services below

## Setup

### 1. Get your API keys

| Service | What for | Where |
|---|---|---|
| **Meta WhatsApp Cloud API** | Sending and receiving messages | [developers.facebook.com](https://developers.facebook.com/apps) |
| **Groq** (recommended) | Main reply model, generous free tier | [console.groq.com/keys](https://console.groq.com/keys) |
| **Gemini** (optional fallback) | Backup model | [aistudio.google.com/apikey](https://aistudio.google.com/apikey) |
| **Pinecone** (optional) | Search over your old chats | [app.pinecone.io](https://app.pinecone.io) |

You need at least one of Groq or Gemini. Without Pinecone the bot still works, but cannot search your history.

**Pinecone index:** create an index with **integrated embedding** (for example the `llama-text-embed-v2` model with the text field mapped to `text`). The code upserts raw text and lets Pinecone embed it. Each contact gets its own namespace, `chat-<contact id>`.

### 2. Set up WhatsApp Cloud API

1. In the Meta developer dashboard, create an app, choose the **Business** type, and add the **WhatsApp** product.
2. Open **WhatsApp > API Setup**. You get a **test phone number** and a temporary **access token**.
3. Copy the **Phone number ID** (under "From"). This is `WHATSAPP_PHONE_NUMBER_ID`, not the phone number itself.
4. Under "To", add your own phone number as a recipient and confirm the code WhatsApp sends you. With a test number you can only message verified recipients.
5. The temporary token lasts about 24 hours. For longer use, create a System User in Business Settings and generate a permanent token.
6. Optional but recommended: copy the **App Secret** (App settings > Basic) into `WHATSAPP_APP_SECRET` so the server rejects calls Meta did not sign.

> **WhatsApp's 24-hour rule:** you can only send free-form text to someone who messaged you in the last 24 hours. Scheduled messages outside that window fail unless you use an approved message template (not implemented here).

### 3. Install the backend

```bash
cd backend
uv venv --python 3.11
uv pip install --python .venv -r requirements.txt
cp .env.example .env        # Windows: copy .env.example .env
```

Edit `.env` and fill in your keys. Every variable is explained in [`backend/.env.example`](backend/.env.example). The minimum is the three `WHATSAPP_*` values, one LLM key, and `OWNER_NAME`.

The default database is a local SQLite file, so no database setup is needed. To use Postgres instead, set `DATABASE_URL=postgresql://...` and add `psycopg2-binary` to the requirements. Tables are created automatically on startup.

### 4. Run the backend

```bash
cd backend
uv run --no-project --python .venv uvicorn app.main:app --port 8000
```

Check http://127.0.0.1:8000/ returns `{"status":"AI Companion Backend Running"}`. Interactive API docs are at `/docs`.

Without uv: activate the venv and run `uvicorn app.main:app --port 8000`.

### 5. Expose the webhook and connect Meta

Meta can only call a public HTTPS URL, so use a tunnel while developing:

```bash
ngrok http 8000        # or: cloudflared tunnel --url http://localhost:8000
```

Then in the Meta dashboard open **WhatsApp > Configuration > Webhook**:

1. **Callback URL:** `https://<your-tunnel>/webhook`
2. **Verify token:** exactly the value of `WHATSAPP_VERIFY_TOKEN` in your `.env`
3. Click **Verify and save**, then subscribe to the **`messages`** field.

Meta's verification request must reach the running backend, so start it first.

### 6. Run the dashboard

```bash
cd frontend
npm install
npm run dev
```

Open http://127.0.0.1:5173. If your backend is not on `127.0.0.1:8000`, copy `frontend/.env.example` to `frontend/.env` and set `VITE_API_URL`.

### 7. Teach it your style (build your dataset)

The replies are only as good as the chats you give it.

1. In WhatsApp, open a chat, tap **More > Export chat > Without media**, and save the `.txt`.
2. In the dashboard, add or open the contact (use the number with country code, digits only).
3. Enter **your name exactly as it appears in the export** (the name WhatsApp shows for your messages), then choose the `.txt`.
4. The import stores the messages, indexes them in Pinecone, and rebuilds your style profile. "How the AI thinks you text" on the dashboard shows what it learned.

Tips for better results:
- Import several chats with **different people**; your voice shows up across all of them.
- The more of **your own** messages, the better. Under about 10 and no style profile is built.
- Keep personal chats out of version control (see [Security](#security)).

### 8. Try it

Text your WhatsApp test number from your phone.

- Contact with **auto-reply On**: the AI answers directly.
- Contact with **auto-reply Off**: a draft appears under "Draft replies to review". Edit and press Send, or dismiss.

Start with auto-reply Off for new contacts and turn it On only where the drafts keep coming out right.

## Configuration reference

See [`backend/.env.example`](backend/.env.example) for every variable with comments. Highlights:

| Variable | Notes |
|---|---|
| `OWNER_NAME` | Your first name. The AI replies as this person. |
| `GROQ_API_KEY` / `GROQ_MODEL` | Main model. Default `openai/gpt-oss-120b`. |
| `GEMINI_API_KEY` / `MODEL_NAME` / `FALLBACK_MODEL` | Fallback models, used when Groq fails or is rate limited. |
| `PINECONE_API_KEY` / `PINECONE_INDEX_NAME` | Enables search over old chats. |
| `WHATSAPP_APP_SECRET` | Enables webhook signature checking. |

Tuning knobs in code: `MIN_RELEVANCE` and `MAX_RELEVANT` in `backend/app/services/rag.py` control how strict retrieval is.

## Security

- **No authentication.** The dashboard API (`/api/*`) is open and CORS allows all origins. Anyone who can reach the port can read your chats and send messages as you. Keep it on localhost, or put it behind a VPN or an authenticating reverse proxy before exposing it.
- **A tunnel exposes everything on port 8000, including `/api/*`**, not just `/webhook`. Put a proxy in front that only forwards `/webhook`, or add authentication, before sharing the tunnel URL. Set `WHATSAPP_APP_SECRET` so forged webhook calls are rejected.
- **Never commit** `.env`, `*.db`, or chat exports. The included `.gitignore` covers them.
- **Rotate keys** that were ever pasted anywhere public (chat, screenshots, issues).
- Your messages and replies are sent to the LLM and vector providers you configure. Check their data policies before using private chats.

## Troubleshooting

| Problem | Fix |
|---|---|
| Meta says webhook verification failed | Backend not running, tunnel URL changed, or verify token differs from `.env`. |
| Messages arrive but nothing is sent back | Check the backend log. Common causes: expired `WHATSAPP_TOKEN`, wrong `WHATSAPP_PHONE_NUMBER_ID`, recipient not added in API Setup, or outside the 24-hour window. |
| `pydantic-core` fails to build | You are on Python 3.13+. Use `uv venv --python 3.11`. |
| Replies are generic or ignore the message | Upload more real chats, and check the log for `RAG: nothing relevant`. |
| `429` / quota errors in the log | Free-tier limit hit. The bot falls back to the next model automatically. Add a second provider key. |
| Dashboard shows "Backend not reachable" | Backend not running, or `VITE_API_URL` is wrong. |

## Limitations

- Text messages only (images, voice notes and stickers are ignored).
- No message templates, so scheduled messages only work inside WhatsApp's 24-hour window.
- Single user: one owner, one style profile.
- The backend has no auto-reload in the commands above; restart it after changing code, or add `--reload` while developing.
