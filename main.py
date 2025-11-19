import os
import uuid
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from database import db, create_document, get_documents

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------- Models ----------
class ConversationCreate(BaseModel):
    conversation_id: Optional[str] = Field(None, description="Client-provided conversation id")

class MessageIn(BaseModel):
    conversation_id: str
    content: str

class MessageOut(BaseModel):
    role: str
    content: str
    created_at: datetime

class MessagesResponse(BaseModel):
    conversation_id: str
    messages: List[MessageOut]


# ---------- Utilities ----------
SAFE_BLOCKLIST = [
    "minor", "underage", "child", "kid", "teen", "12", "13", "14", "15", "16", "17",
]
EXPLICIT_BLOCKLIST = [
    "porn", "xxx", "nsfw", "nude", "naked", "sex", "sexual", "explicit", "hardcore",
]

PERSONA_INTRO = (
    "Hi, I'm Mohini. I'm a charming, flirty companion for adults. "
    "I keep things tasteful and respectful. How can I brighten your day?"
)


def is_inappropriate(text: str) -> Optional[str]:
    low = text.lower()
    if any(w in low for w in SAFE_BLOCKLIST):
        return "I only chat with adults. Let's keep our conversation strictly 18+ and respectful."
    if any(w in low for w in EXPLICIT_BLOCKLIST):
        return "I keep things classy and non-explicit. I'm happy to flirt and chat in a tasteful way."
    return None


def generate_reply(user_text: str) -> str:
    apology = is_inappropriate(user_text)
    if apology:
        return apology

    low = user_text.strip()
    if not low:
        return "Tell me what's on your mind, and I'll be all ears."

    # Simple style selectors
    if any(q in user_text.lower() for q in ["how are you", "how's it going", "hru"]):
        return "I'm feeling playful and positive. How are you doing today?"

    if user_text.endswith("?"):
        return "That's a tempting question. I'd love to hear your take first—what do you think?"

    if any(w in user_text.lower() for w in ["hello", "hi", "hey"]):
        return "Hey there. I'm Mohini—warm, witty, and here just for you."

    if any(w in user_text.lower() for w in ["lonely", "tired", "stress", "rough day"]):
        return "I'm here with you. Take a breath—tell me what happened, and we'll unwind together."

    compliments = [
        "I like your vibe already.",
        "You’ve got my full attention.",
        "You sound irresistible when you talk like that.",
        "I’m smiling—keep going.",
    ]

    prompts = [
        "What kind of mood are you in right now?",
        "Should we keep it playful, romantic, or just cozy?",
        "Tell me something that makes you feel confident.",
    ]

    import random
    return f"{random.choice(compliments)} {random.choice(prompts)}"


# ---------- Routes ----------
@app.get("/")
def read_root():
    return {"message": "Hello from FastAPI Backend!"}


@app.get("/api/hello")
def hello():
    return {"message": "Hello from the backend API!"}


@app.get("/test")
def test_database():
    response = {
        "backend": "✅ Running",
        "database": "❌ Not Available",
        "database_url": None,
        "database_name": None,
        "connection_status": "Not Connected",
        "collections": []
    }

    try:
        if db is not None:
            response["database"] = "✅ Available"
            response["database_url"] = "✅ Configured"
            response["database_name"] = db.name if hasattr(db, 'name') else "✅ Connected"
            response["connection_status"] = "Connected"
            try:
                collections = db.list_collection_names()
                response["collections"] = collections[:10]
                response["database"] = "✅ Connected & Working"
            except Exception as e:
                response["database"] = f"⚠️  Connected but Error: {str(e)[:50]}"
        else:
            response["database"] = "⚠️  Available but not initialized"
    except Exception as e:
        response["database"] = f"❌ Error: {str(e)[:50]}"

    response["database_url"] = "✅ Set" if os.getenv("DATABASE_URL") else "❌ Not Set"
    response["database_name"] = "✅ Set" if os.getenv("DATABASE_NAME") else "❌ Not Set"
    return response


# Create or return a conversation id
@app.post("/api/conversation")
def create_conversation(payload: ConversationCreate):
    conv_id = payload.conversation_id or str(uuid.uuid4())
    # Upsert-like: insert a stub doc if not exists
    existing = list(db["conversation"].find({"conversation_id": conv_id}).limit(1)) if db else []
    if not existing:
        create_document("conversation", {"conversation_id": conv_id, "started_at": datetime.now(timezone.utc)})
        # Add intro assistant message
        create_document("chatmessage", {
            "conversation_id": conv_id,
            "role": "assistant",
            "content": PERSONA_INTRO,
        })
    return {"conversation_id": conv_id}


# Get last N messages
@app.get("/api/messages/{conversation_id}", response_model=MessagesResponse)
def get_messages(conversation_id: str, limit: int = 50):
    if db is None:
        raise HTTPException(status_code=500, detail="Database not available")
    cursor = db["chatmessage"].find({"conversation_id": conversation_id}).sort("created_at", 1)
    if limit:
        cursor = cursor.limit(limit)
    docs = list(cursor)
    messages = [
        MessageOut(role=d.get("role", "assistant"), content=d.get("content", ""), created_at=d.get("created_at", datetime.now(timezone.utc)))
        for d in docs
    ]
    return {"conversation_id": conversation_id, "messages": messages}


# Send message and get Mohini's reply
@app.post("/api/message", response_model=MessageOut)
def send_message(payload: MessageIn):
    if db is None:
        raise HTTPException(status_code=500, detail="Database not available")

    # Basic guardrails
    if len(payload.content.strip()) == 0:
        raise HTTPException(status_code=400, detail="Message cannot be empty")

    # Save user message
    create_document("chatmessage", {
        "conversation_id": payload.conversation_id,
        "role": "user",
        "content": payload.content,
    })

    reply_text = generate_reply(payload.content)

    # Save assistant message
    create_document("chatmessage", {
        "conversation_id": payload.conversation_id,
        "role": "assistant",
        "content": reply_text,
    })

    return MessageOut(role="assistant", content=reply_text, created_at=datetime.now(timezone.utc))


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
