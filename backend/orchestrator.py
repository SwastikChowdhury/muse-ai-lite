import asyncio

from agents import conversation_agent_stream, whisper_agent
from memory import add_memory, get_relevant_memories


async def handle_turn(websocket, history, user_message, user_id):
    """Coordinate the agents for one turn."""

    # Memory Agent (retrieve) — relevant patterns from past sessions
    past_patterns = get_relevant_memories(user_id, user_message)

    # 1. Conversation Agent — the mentee replies, streamed to the chat panel
    full_reply = ""
    stream = conversation_agent_stream(history, user_message)
    for chunk in stream:
        if chunk.text:
            full_reply += chunk.text
            await websocket.send_json({"type": "token", "content": chunk.text})
    await websocket.send_json({"type": "done"})

    # 2. Muse Whisper Agent — resilient to transient API errors (e.g. 503 overload)
    whisper = None
    for attempt in range(3):
        try:
            whisper = whisper_agent(history, user_message, full_reply, past_patterns)
            break
        except Exception as e:
            print(f"Whisper attempt {attempt + 1} failed: {e}")
            await asyncio.sleep(1.5)

    if whisper:
        await websocket.send_json({"type": "whisper", "content": whisper})
    else:
        await websocket.send_json({
            "type": "whisper",
            "content": "Muse is momentarily busy (the model is under load) — try another exchange.",
        })

    # 3. Memory Agent (write) — remember this mentor message
    add_memory(user_id, user_message)

    return full_reply