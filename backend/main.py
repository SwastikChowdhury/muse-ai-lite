import os
from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from db import save_message, get_history
from models import Message
from orchestrator import handle_turn

load_dotenv()

app = FastAPI(title="muse-ai-lite")

USER_ID = "demo-user"
CONVERSATION_ID = "demo-conversation"


@app.get("/health")
def health():
    return {"status": "ok"}


@app.websocket("/ws")
async def websocket_chat(websocket: WebSocket):
    await websocket.accept()

    history = await get_history(USER_ID, CONVERSATION_ID)
    await websocket.send_json({
        "type": "history",
        "messages": [{"role": m["role"], "content": m["content"]} for m in history],
    })

    try:
        while True:
            user_text = await websocket.receive_text()

            prior = await get_history(USER_ID, CONVERSATION_ID)  # context before this turn

            await save_message(Message(
                user_id=USER_ID, conversation_id=CONVERSATION_ID,
                role="user", content=user_text,
            ))

            full_reply = await handle_turn(websocket, prior, user_text, USER_ID)

            await save_message(Message(
                user_id=USER_ID, conversation_id=CONVERSATION_ID,
                role="assistant", content=full_reply,
            ))
    except WebSocketDisconnect:
        pass