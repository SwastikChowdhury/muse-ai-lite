import asyncio
import re
import time

from agents import conversation_agent_stream, whisper_agent
from memory import add_memory, get_relevant_memories
from metrics import gemini_calls, agent_latency, whisper_grounding
from llm_metrics import record_usage

QUOTA_MSG = (
    "Sorry — I'm having trouble responding right now. "
    "The AI service hit its rate limit. Please try again shortly."
)

CITATION_RE = re.compile(r"\[M(\d+)\]")


def verify_grounding(whisper: str, memories: list[str]) -> tuple[str, str]:
    """Check the whisper's memory citations against what was actually retrieved.
    Returns (possibly cleaned whisper, status)."""
    citations = CITATION_RE.findall(whisper)
    if not memories:
        if citations:  # cited a memory when none were provided -> hallucinated
            return CITATION_RE.sub("", whisper).strip(), "ungrounded"
        return whisper, "no_memory"
    if not citations:
        return whisper, "no_memory"
    valid = all(1 <= int(c) <= len(memories) for c in citations)
    if valid:
        return CITATION_RE.sub("", whisper).strip(), "grounded"
    return CITATION_RE.sub("", whisper).strip(), "ungrounded"


async def _stream_mentee_reply(websocket, history, user_message) -> str:
    for attempt in range(3):
        full_reply = ""
        usage = None
        start = time.perf_counter()
        try:
            stream = conversation_agent_stream(history, user_message)
            for chunk in stream:
                if chunk.text:
                    full_reply += chunk.text
                    await websocket.send_json({"type": "token", "content": chunk.text})
                if getattr(chunk, "usage_metadata", None):
                    usage = chunk.usage_metadata
            if full_reply:
                gemini_calls.labels(agent="conversation", outcome="ok").inc()
                agent_latency.labels(agent="conversation").observe(time.perf_counter() - start)
                record_usage("conversation", usage)
                return full_reply
        except Exception as e:
            err = str(e)
            print(f"Conversation attempt {attempt + 1} failed: {e}")
            if "429" in err or "RESOURCE_EXHAUSTED" in err:
                gemini_calls.labels(agent="conversation", outcome="quota").inc()
                await websocket.send_json({"type": "token", "content": QUOTA_MSG})
                return QUOTA_MSG
            gemini_calls.labels(agent="conversation", outcome="error").inc()
            await asyncio.sleep(1.5 * (attempt + 1))

    fallback = "Sorry — I'm having trouble responding right now. Please try again in a moment."
    await websocket.send_json({"type": "token", "content": fallback})
    return fallback


async def handle_turn(websocket, history, user_message, user_id):
    """Coordinate the agents for one turn."""

    past_patterns = get_relevant_memories(user_id, user_message)

    full_reply = await _stream_mentee_reply(websocket, history, user_message)
    await websocket.send_json({"type": "done"})

    whisper = None
    start = time.perf_counter()
    for attempt in range(3):
        try:
            whisper = whisper_agent(history, user_message, full_reply, past_patterns)
            gemini_calls.labels(agent="whisper", outcome="ok").inc()
            break
        except Exception as e:
            err = str(e)
            print(f"Whisper attempt {attempt + 1} failed: {e}")
            if "429" in err or "RESOURCE_EXHAUSTED" in err:
                gemini_calls.labels(agent="whisper", outcome="quota").inc()
            else:
                gemini_calls.labels(agent="whisper", outcome="error").inc()
            await asyncio.sleep(1.5)
    agent_latency.labels(agent="whisper").observe(time.perf_counter() - start)

    if whisper:
        whisper, grounding_status = verify_grounding(whisper, past_patterns)
        whisper_grounding.labels(status=grounding_status).inc()
        await websocket.send_json({"type": "whisper", "content": whisper})
    else:
        await websocket.send_json({
            "type": "whisper",
            "content": "Muse is momentarily busy (the model is under load) — try another exchange.",
        })

    add_memory(user_id, user_message)

    return full_reply, whisper