import os
from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from groq import Groq

from db import save_message, get_history, save_whisper, get_whispers
from models import Message
from orchestrator import handle_turn

load_dotenv()

app = FastAPI(title="muse-ai-lite")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

groq_client = Groq(api_key=os.environ["GROQ_API_KEY"])

USER_ID = "demo-user"
CONVERSATION_ID = "demo-conversation"


@app.get("/health")
def health():
    return {"status": "ok"}


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
            prior = await get_history(USER_ID, CONVERSATION_ID)  # context before this turn

            await save_message(Message(
                user_id=USER_ID, conversation_id=CONVERSATION_ID,
                role="user", content=user_text,
            ))

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