import os
from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from prometheus_fastapi_instrumentator import Instrumentator
from groq import Groq

from db import save_message, get_history, save_whisper, get_whispers
from models import Message
from orchestrator import handle_turn
from metrics import active_ws, safety_escalations, model_rollbacks
from safety import check_safety
from privacy import redact_pii
from model_registry import REGISTRY, rollback
from memory import clear_memories

load_dotenv()

app = FastAPI(title="muse-ai-lite")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

Instrumentator().instrument(app).expose(app)

groq_client = Groq(api_key=os.environ["GROQ_API_KEY"])

USER_ID = "demo-user"
CONVERSATION_ID = "demo-conversation"


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/admin/models")
def list_models():
    return REGISTRY


@app.post("/admin/rollback/{agent}")
def rollback_model(agent: str):
    result = rollback(agent)
    if "error" not in result:
        model_rollbacks.labels(agent=agent).inc()
    return result


@app.delete("/admin/clear-data")
async def clear_data():
    """Data rights: wipe this user's conversation, whispers, and vector memories."""
    from db import messages_collection, whispers_collection
    deleted_msgs = await messages_collection.delete_many(
        {"user_id": USER_ID, "conversation_id": CONVERSATION_ID})
    deleted_whispers = await whispers_collection.delete_many(
        {"user_id": USER_ID, "conversation_id": CONVERSATION_ID})
    deleted_memories = clear_memories(USER_ID)
    return {
        "messages_deleted": deleted_msgs.deleted_count,
        "whispers_deleted": deleted_whispers.deleted_count,
        "memories_deleted": deleted_memories,
    }


@app.post("/transcribe")
async def transcribe(audio: UploadFile = File(...)):
    audio_bytes = await audio.read()
    transcription = groq_client.audio.transcriptions.create(
        file=("audio.webm", audio_bytes),
        model="whisper-large-v3",
    )
    return {"text": transcription.text}


@app.websocket("/ws")
async def websocket_chat(websocket: WebSocket):
    await websocket.accept()
    active_ws.inc()

    history = await get_history(USER_ID, CONVERSATION_ID)
    whispers = await get_whispers(USER_ID, CONVERSATION_ID)
    await websocket.send_json({
        "type": "history",
        "messages": [{"role": m["role"], "content": m["content"]} for m in history],
        "whispers": [w["content"] for w in whispers],
    })

    try:
        while True:
            user_text = await websocket.receive_text()

            # Privacy: PII is stripped at intake — before the DB, the LLM, or the vector store
            user_text = redact_pii(user_text)

            prior = await get_history(USER_ID, CONVERSATION_ID)

            await save_message(Message(
                user_id=USER_ID, conversation_id=CONVERSATION_ID,
                role="user", content=user_text,
            ))

            # Safety: crisis messages never reach an agent
            escalation = check_safety(user_text)
            if escalation:
                safety_escalations.inc()
                await websocket.send_json({"type": "token", "content": escalation})
                await websocket.send_json({"type": "done"})
                await save_message(Message(
                    user_id=USER_ID, conversation_id=CONVERSATION_ID,
                    role="assistant", content=escalation,
                ))
                continue

            full_reply, whisper = await handle_turn(websocket, prior, user_text, USER_ID)

            await save_message(Message(
                user_id=USER_ID, conversation_id=CONVERSATION_ID,
                role="assistant", content=full_reply,
            ))

            if whisper:
                await save_whisper(Message(
                    user_id=USER_ID, conversation_id=CONVERSATION_ID,
                    role="whisper", content=whisper,
                ))
    except WebSocketDisconnect:
        pass
    finally:
        active_ws.dec()


_static_dir = os.path.join(os.path.dirname(__file__), "static")
if os.path.isdir(_static_dir):
    app.mount("/", StaticFiles(directory=_static_dir, html=True), name="frontend")