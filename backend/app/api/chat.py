"""Chat transport: the authenticated /ws socket and the /transcribe endpoint.

This module owns the per-turn lifecycle but deliberately holds almost no
business logic — each concern lives in its own package and is composed here:

  - agents.orchestrator.handle_turn -> runs the two Gemini agents, streams output
  - safety.check_safety             -> crisis filter applied BEFORE any agent runs
  - safety.redact_pii               -> strips PII at intake, before DB/LLM/vector
  - db.mongo.*                      -> MongoDB persistence for messages/whispers
  - auth.verify_access_token        -> gates the socket on a valid access token

Request flow for a chat turn (see `websocket_chat`):
  client text -> redact PII -> persist user msg -> safety gate
              -> orchestrator streams mentee reply + whisper -> persist replies.
"""

import os

from fastapi import APIRouter, File, Query, UploadFile, WebSocket, WebSocketDisconnect
from groq import Groq

from app.agents.orchestrator import handle_turn
from app.auth.jwt import verify_access_token
from app.db.mongo import (
    conversation_id_for,
    get_history,
    get_whispers,
    save_flagged,
    save_message,
    save_whisper,
)
from app.observability.metrics import (
    active_ws,
    moderation_flags,
    record_dominant_emotion,
    safety_escalations,
)
from app.safety.privacy import redact_pii
from app.safety.safety import check_safety
from app.schemas.models import FlaggedMessage, Message

router = APIRouter(tags=["chat"])

# Groq is used only for speech-to-text (Whisper). The conversational/coaching
# agents run on Gemini and are wired up in agents.py, not here.
groq_client = Groq(api_key=os.environ["GROQ_API_KEY"])


@router.post("/transcribe")
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


@router.websocket("/ws")
async def websocket_chat(websocket: WebSocket, token: str = Query(...)):
    """Primary chat transport: one long-lived socket per browser session.

    Authenticated: the client passes its access token as a `token` query param
    (browsers can't set Authorization headers on a WebSocket handshake). The
    token is verified before the socket is accepted; an invalid/expired token
    closes the connection with code 4001. The user id from the token drives all
    persistence, and the conversation id is derived from it so history persists
    across reconnects.

    Lifecycle:
      1. Verify the token, then accept the socket and increment the gauge.
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
    user_id = verify_access_token(token)
    if not user_id:
        # Reject before accept() so an unauthenticated client never enters the
        # message loop. 4001 is an app-defined close code for "unauthorized".
        await websocket.close(code=4001)
        return
    conversation_id = conversation_id_for(user_id)

    await websocket.accept()
    active_ws.inc()

    history = await get_history(user_id, conversation_id)
    whispers = await get_whispers(user_id, conversation_id)
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
            prior = await get_history(user_id, conversation_id)

            # Safety + moderation gate. Returns (escalation | None, mod_result).
            # Run before persisting so the moderation verdict can be stamped onto
            # the stored message. The mod_result is always present and always
            # carries the recorded emotion distribution.
            escalation, mod_result = check_safety(user_text)

            # The flagged/flag_type/emotions fields are persisted to Mongo for
            # observation but are never sent to the frontend (see history payload
            # below). Emotions are recorded on every message for trend tracking.
            await save_message(Message(
                user_id=user_id, conversation_id=conversation_id,
                role="user", content=user_text,
                flagged=mod_result["flagged"], flag_type=mod_result.get("flag_type"),
                emotions=mod_result.get("emotions"),
            ))
            record_dominant_emotion("mentor", mod_result.get("emotions"))

            # Mirror flagged mentor input into the observation-only collection.
            if mod_result["flagged"]:
                moderation_flags.labels(role="mentor", flag_type=mod_result["flag_type"]).inc()
                await save_flagged(FlaggedMessage(
                    user_id=user_id, conversation_id=conversation_id,
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
                    user_id=user_id, conversation_id=conversation_id,
                    role="assistant", content=escalation,
                ))
                continue

            # Orchestrator streams tokens/whisper over the socket as a side
            # effect; it also returns the assembled values so we can persist
            # them here. Transport owns persistence, the orchestrator owns the
            # agents. The mentee mod_result lets us stamp the assistant message.
            full_reply, whisper_label, whisper, mentee_mod = await handle_turn(websocket, prior, user_text, user_id, conversation_id)

            await save_message(Message(
                user_id=user_id, conversation_id=conversation_id,
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
                    user_id=user_id, conversation_id=conversation_id,
                    role="whisper", content=whisper, label=whisper_label,
                ))
    except WebSocketDisconnect:
        # Normal client teardown (tab closed, navigation). Nothing to clean up
        # beyond the gauge decrement below.
        pass
    finally:
        active_ws.dec()
