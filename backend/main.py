"""
FastAPI entrypoint and transport layer for muse-ai-lite.

Owns the HTTP/WebSocket surface and the per-turn lifecycle, but deliberately
holds almost no business logic. Each concern lives in its own module and is
composed here:

  - orchestrator.handle_turn  -> runs the two Gemini agents and streams output
  - safety.check_safety       -> crisis filter applied BEFORE any agent runs
  - privacy.redact_pii        -> strips PII at intake, before DB/LLM/vector store
  - db.*                      -> MongoDB persistence for messages and whispers
  - memory.clear_memories     -> vector-store memory wipe (data-rights endpoint)
  - model_registry / metrics  -> live model selection and Prometheus counters

Request flow for a chat turn (see `websocket_chat`):
  client text -> redact PII -> persist user msg -> safety gate
              -> orchestrator streams mentee reply + whisper -> persist replies.

The module also exposes Prometheus metrics (via Instrumentator) and, in
production, serves the built frontend from ./static when that directory exists.
"""

import os
from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from prometheus_fastapi_instrumentator import Instrumentator
from groq import Groq

from db import save_message, get_history, save_whisper, get_whispers, save_flagged
from models import Message, FlaggedMessage
from orchestrator import handle_turn
from metrics import active_ws, safety_escalations, model_rollbacks, moderation_flags, record_dominant_emotion
from safety import check_safety
from privacy import redact_pii
from model_registry import REGISTRY, rollback
from memory import clear_memories

load_dotenv()

app = FastAPI(title="muse-ai-lite")

# CORS is fully open because this is a single-user demo with no auth; the
# frontend dev server and the API run on different origins/ports. Lock this
# down before any multi-tenant or production deployment.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Auto-instrument every route and expose Prometheus metrics at GET /metrics.
Instrumentator().instrument(app).expose(app)

# Groq is used only for speech-to-text (Whisper). The conversational/coaching
# agents run on Gemini and are wired up in agents.py, not here.
groq_client = Groq(api_key=os.environ["GROQ_API_KEY"])

# This build is intentionally single-tenant: every request maps to one fixed
# user/conversation. These constants are the seam where real auth + routing
# would be introduced later.
USER_ID = "demo-user"
CONVERSATION_ID = "demo-conversation"


@app.get("/health")
def health():
    """Liveness probe for Docker/CI/load balancers.

    Response: 200 with {"status": "ok"}. No auth, no side effects.
    """
    return {"status": "ok"}


@app.get("/admin/models")
def list_models():
    """Return the live model registry (current/previous model per agent).

    Response: the REGISTRY dict, used by ops to see what each agent is running.
    Unauthenticated — acceptable only because this is a local demo.
    """
    return REGISTRY


@app.post("/admin/rollback/{agent}")
def rollback_model(agent: str):
    """Swap an agent back to its previous model at runtime (no redeploy).

    Path param `agent`: registry key, e.g. "conversation" or "whisper".
    Response: the new model state, or {"error": ...} if no previous model
    exists. The rollback metric is only incremented on a successful swap so
    failed attempts don't pollute the counter.
    """
    result = rollback(agent)
    if "error" not in result:
        model_rollbacks.labels(agent=agent).inc()
    return result


@app.delete("/admin/clear-data")
async def clear_data():
    """Data-rights endpoint: wipe this user's conversation, whispers, and memories.

    Deletes across all three stores so no trace of the user remains:
    MongoDB messages, MongoDB whispers, and the Chroma vector memories.

    Response: per-store deletion counts. Side effects: irreversible deletes in
    both MongoDB collections and the vector store.
    """
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
    """Speech-to-text for the mic button: audio upload -> transcript text.

    Request: multipart form with field `audio` (browser sends a WebM blob).
    Response: {"text": <transcript>}.
    Side effect: a network call to Groq's Whisper model. The frontend feeds
    the returned text back into the normal /ws chat flow, so transcription
    itself performs no persistence and runs no agents.
    """
    audio_bytes = await audio.read()
    transcription = groq_client.audio.transcriptions.create(
        file=("audio.webm", audio_bytes),
        model="whisper-large-v3",
    )
    return {"text": transcription.text}


@app.websocket("/ws")
async def websocket_chat(websocket: WebSocket):
    """Primary chat transport: one long-lived socket per browser session.

    Lifecycle:
      1. Accept the socket and increment the active-connection gauge.
      2. Replay persisted history + whispers so a reconnecting client is
         immediately rehydrated (the frontend renders these on connect).
      3. Loop: receive a mentor message, redact PII, persist it, apply the
         safety gate, then delegate to the orchestrator which streams the
         mentee reply and the coaching whisper back over this same socket.

    Protocol (server -> client JSON frames):
      {type: "history", messages, whispers}  -- once, on connect
      {type: "token",   content}             -- incremental mentee reply chunks
      {type: "done"}                         -- mentee reply complete
      {type: "whisper", content, label}      -- coaching note for this turn

    The gauge is decremented in `finally` so it stays accurate whether the
    client disconnects cleanly or the loop errors out.
    """
    await websocket.accept()
    active_ws.inc()

    history = await get_history(USER_ID, CONVERSATION_ID)
    whispers = await get_whispers(USER_ID, CONVERSATION_ID)
    # Send the full prior transcript up front so the UI can rehydrate on
    # (re)connect rather than starting blank.
    await websocket.send_json({
        "type": "history",
        "messages": [{"role": m["role"], "content": m["content"]} for m in history],
        "whispers": [{"content": w["content"], "label": w.get("label") or "Insight"} for w in whispers],
    })

    try:
        while True:
            user_text = await websocket.receive_text()

            # Privacy: PII is stripped at intake — before the DB, the LLM, or the vector store
            user_text = redact_pii(user_text)

            # Fetch history BEFORE persisting the new message so `prior` is the
            # conversation as it stood prior to this turn (the agents need the
            # context, not the just-sent message duplicated into it).
            prior = await get_history(USER_ID, CONVERSATION_ID)

            # Safety + moderation gate. Returns (escalation | None, mod_result).
            # Run before persisting so the moderation verdict can be stamped onto
            # the stored message. The mod_result is always present and always
            # carries the recorded emotion distribution.
            escalation, mod_result = check_safety(user_text)

            # The flagged/flag_type/emotions fields are persisted to Mongo for
            # observation but are never sent to the frontend (see history payload
            # below). Emotions are recorded on every message for trend tracking.
            await save_message(Message(
                user_id=USER_ID, conversation_id=CONVERSATION_ID,
                role="user", content=user_text,
                flagged=mod_result["flagged"], flag_type=mod_result.get("flag_type"),
                emotions=mod_result.get("emotions"),
            ))
            record_dominant_emotion("mentor", mod_result.get("emotions"))

            # Mirror flagged mentor input into the observation-only collection.
            if mod_result["flagged"]:
                moderation_flags.labels(role="mentor", flag_type=mod_result["flag_type"]).inc()
                await save_flagged(FlaggedMessage(
                    user_id=USER_ID, conversation_id=CONVERSATION_ID,
                    role="mentor", content=user_text,
                    flag_type=mod_result["flag_type"],
                    suicide_score=mod_result.get("suicide_score"),
                    crisis_score=mod_result.get("crisis_score"),
                    toxic_scores=mod_result.get("toxic_scores"),
                    emotions=mod_result.get("emotions"),
                ))

            if escalation:
                # Short-circuit: emit the crisis resource response as if it were
                # a normal streamed reply, persist it, and skip the agents
                # entirely so no LLM ever processes a crisis message.
                safety_escalations.inc()
                await websocket.send_json({"type": "token", "content": escalation})
                await websocket.send_json({"type": "done"})
                await save_message(Message(
                    user_id=USER_ID, conversation_id=CONVERSATION_ID,
                    role="assistant", content=escalation,
                ))
                continue

            # Orchestrator streams tokens/whisper over the socket as a side
            # effect; it also returns the assembled values so we can persist
            # them here. Transport owns persistence, the orchestrator owns the
            # agents. The mentee mod_result lets us stamp the assistant message.
            full_reply, whisper_label, whisper, mentee_mod = await handle_turn(websocket, prior, user_text, USER_ID, CONVERSATION_ID)

            await save_message(Message(
                user_id=USER_ID, conversation_id=CONVERSATION_ID,
                role="assistant", content=full_reply,
                flagged=mentee_mod["flagged"], flag_type=mentee_mod.get("flag_type"),
                emotions=mentee_mod.get("emotions"),
            ))

            # Only persist a whisper when the orchestrator actually produced
            # one. A None means the whisper agent failed/was skipped, in which
            # case we don't want to store the transient "Muse is busy" filler.
            # The label (tone/category) is stored too so the side-panel can
            # rehydrate each note with its original tag on reconnect.
            if whisper:
                await save_whisper(Message(
                    user_id=USER_ID, conversation_id=CONVERSATION_ID,
                    role="whisper", content=whisper, label=whisper_label,
                ))
    except WebSocketDisconnect:
        # Normal client teardown (tab closed, navigation). Nothing to clean up
        # beyond the gauge decrement below.
        pass
    finally:
        active_ws.dec()


# In production the Vite build is copied to ./static and served by this same
# app, so the API and SPA share one origin. In local dev the frontend runs on
# its own Vite server, ./static won't exist, and this mount is skipped.
_static_dir = os.path.join(os.path.dirname(__file__), "static")
if os.path.isdir(_static_dir):
    app.mount("/", StaticFiles(directory=_static_dir, html=True), name="frontend")