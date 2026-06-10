from agents import conversation_agent_stream


async def handle_turn(websocket, history, user_message):
    """Coordinate the agents for one turn.

    For now this routes only to the Conversation Agent. The Whisper Agent and
    Memory Agent will hook in right here in the next steps.
    """
    full_reply = ""
    stream = conversation_agent_stream(history, user_message)
    for chunk in stream:
        if chunk.text:
            full_reply += chunk.text
            await websocket.send_json({"type": "token", "content": chunk.text})
    await websocket.send_json({"type": "done"})
    return full_reply