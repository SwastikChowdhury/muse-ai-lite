import os
from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from google import genai

load_dotenv()

# Initialize FastAPI app and Gemini client
app = FastAPI(title="muse-ai-lite")

# Initialize Gemini client
genai_client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

# Health check endpoint
@app.get("/health")
def health():
    return {"status": "ok"}

# WebSocket endpoint for streaming responses
@app.websocket("/ws")
async def websocket_chat(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            message = await websocket.receive_text()
            
            # Stream Gemini's reply back over the socket
            stream = genai_client.models.generate_content_stream(
                model="gemini-2.5-flash",
                contents=message,
            )
            
            for chunk in stream:
                if chunk.text:
                    await websocket.send_text(chunk.text)
    except WebSocketDisconnect:
        pass