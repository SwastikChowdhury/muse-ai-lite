import asyncio

from agents import conversation_agent_stream, whisper_agent
from memory import add_memory, get_relevant_memories

QUOTA_MSG = (
    "Sorry — I'm having trouble responding right now. "
    "The AI service hit its daily free-tier limit (20 requests/day). "
    "Wait until the quota resets, or enable billing at ai.google.dev."
)

async def _stream_mentee_reply(websocket, history, user_message) -> str:
    """Stream Alex's reply; retry on transient errors, fall back on quota exhaustion."""
    for attempt in range(3):
        full_reply = ""
        try:
            stream = conversation_agent_stream(history, user_message)
            for chunk in stream:
                if chunk.text:
                    full_reply += chunk.text
                    await websocket.send_json({"type": "token", "content": chunk.text})
            if full_reply:
                return full_reply
        except Exception as e:
            err = str(e)
            print(f"Conversation attempt {attempt + 1} failed: {e}")
            if "429" in err or "RESOURCE_EXHAUSTED" in err:
                await websocket.send_json({"type": "token", "content": QUOTA_MSG})
                return QUOTA_MSG
            await asyncio.sleep(1.5 * (attempt + 1))

    fallback = "Sorry — I'm having trouble responding right now. Please try again in a moment."
    await websocket.send_json({"type": "token", "content": fallback})
    return fallback


async def handle_turn(websocket, history, user_message, user_id):
    """Coordinate the agents for one turn."""

    # Memory Agent (retrieve) — relevant patterns from past sessions
    past_patterns = get_relevant_memories(user_id, user_message)

    # 1. Conversation Agent — the mentee replies, streamed to the chat panel
    full_reply = await _stream_mentee_reply(websocket, history, user_message)
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

    return full_reply, whisper