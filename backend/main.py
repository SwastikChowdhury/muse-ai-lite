from fastapi import FastAPI, WebSocket, WebSocketDisconnect

app = FastAPI(title="muse-ai-lite")

# Health check endpoint
@app.get("/health")
def health():
    return {"status": "ok"}

# WebSocket endpoint for streaming responses
@app.websocket("/ws")
async def websocket_echo(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            message = await websocket.receive_text()
            await websocket.send_text(message)
    except WebSocketDisconnect:
        pass

