"""
Per-turn multi-agent orchestration — the "brain" that sequences the two agents.

Sits between the transport layer (main.py) and the raw agent calls (agents.py).
Given one mentor message, `handle_turn` coordinates the whole turn:

  1. Retrieve relevant past-session memories for this user (vector search).
  2. Stream the mentee reply to the client (conversation agent), with retries.
  3. Signal the reply is done, then run the whisper/coach agent, with retries.
  4. Verify the whisper's memory citations are real (anti-hallucination), strip
     the [Mn] markers, and send the cleaned note to the client.
  5. Persist this mentor message to memory for future turns.

Why the agents run in this order (sequential, not parallel): the whisper agent
critiques the *latest exchange*, so it needs the mentee's reply as input.
Streaming the mentee reply first also gets visible output to the user fastest,
while the (slower, blocking) coaching note is computed afterward.

Resilience model: Gemini Flash models are rate-limited and occasionally
overloaded, so both agent calls are wrapped in bounded retry loops that
degrade gracefully (a friendly message) instead of crashing the socket. Every
attempt and outcome is recorded to Prometheus.

Side effects: streams JSON frames over the websocket, writes to vector memory,
and increments several metrics. It does NOT touch MongoDB — main.py persists
the returned values.
"""

import asyncio
import re
import time

from agents import conversation_agent_stream, whisper_agent
from memory import add_memory, get_relevant_memories
from metrics import gemini_calls, agent_latency, whisper_grounding
from llm_metrics import record_usage

# Shown to the user when the conversation model is rate-limited (HTTP 429 /
# RESOURCE_EXHAUSTED). Phrased for an end user, not a developer.
QUOTA_MSG = (
    "Sorry — I'm having trouble responding right now. "
    "The AI service hit its rate limit. Please try again shortly."
)

# Captures the numeric index of memory citations like "[M2]" the whisper agent
# may emit. Used both to validate and to strip them.
CITATION_RE = re.compile(r"\[M(\d+)\]")


def verify_grounding(whisper: str, memories: list[str]) -> tuple[str, str]:
    """Validate the whisper's [Mn] memory citations and strip them for display.

    This is the anti-hallucination check for memory recall: the whisper agent is
    only allowed to cite a past pattern that was actually provided to it. Here we
    confirm every [Mn] index points to a real entry in `memories` (1-indexed to
    match the [M1], [M2]... numbering built in agents.whisper_agent).

    The [Mn] markers are always stripped from the returned text — they're an
    internal grounding signal, not something the mentor should see.

    Returns (cleaned_text, status) where status feeds the whisper_grounding
    metric and is one of:
      - "grounded":   citations present and all valid
      - "ungrounded": citations present but at least one is invalid/hallucinated
                      (or cited when no memories existed at all)
      - "no_memory":  no citations, treated as the agent coaching only on the
                      current exchange (the expected, non-error case)
    """
    citations = CITATION_RE.findall(whisper)
    if not memories:
        # The agent cited something despite having no memories to draw on — a
        # clear hallucination. Scrub the bogus markers before returning.
        if citations:
            return CITATION_RE.sub("", whisper).strip(), "ungrounded"
        return whisper, "no_memory"
    if not citations:
        return whisper, "no_memory"
    # Every citation index must fall within the provided memory list.
    valid = all(1 <= int(c) <= len(memories) for c in citations)
    if valid:
        return CITATION_RE.sub("", whisper).strip(), "grounded"
    return CITATION_RE.sub("", whisper).strip(), "ungrounded"


async def _stream_mentee_reply(websocket, history, user_message) -> str:
    """Stream the mentee reply to the client, retrying on transient failures.

    Drives the conversation agent and forwards each chunk to the browser as a
    {"type": "token"} frame, accumulating the full text to return so the caller
    can persist it. Usage metadata only arrives on (usually the last) some
    chunks, so we capture it whenever present and record it once on success.

    Failure handling (up to 3 attempts):
      - Quota/rate-limit (429 / RESOURCE_EXHAUSTED): non-retryable in practice,
        so we send the user-facing QUOTA_MSG and bail immediately.
      - Other errors: count it and back off with increasing delay before
        retrying — 1.5s, 3s — to ride out brief model overload.
    If all attempts fail, a generic fallback string is streamed so the user
    always sees *something* and the turn can proceed to the whisper step.

    Returns the full reply text (or QUOTA_MSG/fallback). Side effects: websocket
    frames, latency/outcome metrics.
    """
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
            # A stream that completes but yields no text is treated as a failed
            # attempt (fall through to retry) rather than returning "".
            if full_reply:
                gemini_calls.labels(agent="conversation", outcome="ok").inc()
                agent_latency.labels(agent="conversation").observe(time.perf_counter() - start)
                record_usage("conversation", usage)
                return full_reply
        except Exception as e:
            err = str(e)
            print(f"Conversation attempt {attempt + 1} failed: {e}")
            # Retrying a quota error won't help (the limit is time-based), so
            # short-circuit with the friendly message instead of burning retries.
            if "429" in err or "RESOURCE_EXHAUSTED" in err:
                gemini_calls.labels(agent="conversation", outcome="quota").inc()
                await websocket.send_json({"type": "token", "content": QUOTA_MSG})
                return QUOTA_MSG
            gemini_calls.labels(agent="conversation", outcome="error").inc()
            # Linear backoff between retries; cheap insurance against momentary overload.
            await asyncio.sleep(1.5 * (attempt + 1))

    fallback = "Sorry — I'm having trouble responding right now. Please try again in a moment."
    await websocket.send_json({"type": "token", "content": fallback})
    return fallback


async def handle_turn(websocket, history, user_message, user_id):
    """Run one full coaching turn: mentee reply + grounded coach whisper.

    This is the orchestration entrypoint called by main.py per inbound message.
    Sequence and rationale are documented at the module level; in short, the
    mentee reply is streamed first (fast, visible), then the whisper is computed
    from that reply (it critiques the just-completed exchange).

    Inputs:
      websocket    -- client connection; streamed to as a side effect
      history      -- prior turns, BEFORE this message (supplied by main.py)
      user_message -- the mentor's latest message (already PII-redacted)
      user_id      -- whose memories to retrieve/extend

    Returns (full_reply, whisper_text): the assembled mentee reply and the
    cleaned coaching note (or None if the whisper agent ultimately failed).
    main.py uses these to persist the turn; a None whisper is intentionally not
    persisted so transient "model busy" filler never lands in history.

    Side effects: websocket frames, a vector-memory write, and metrics.
    """
    # Pull memories first so they can be injected into the whisper prompt. Done
    # up front (before streaming) so retrieval latency overlaps with nothing
    # critical and is ready by the time the whisper agent runs.
    past_patterns = get_relevant_memories(user_id, user_message)

    full_reply = await _stream_mentee_reply(websocket, history, user_message)
    # Tell the client the mentee reply is complete; the UI flips to a
    # "Muse is reflecting…" state while the whisper is generated.
    await websocket.send_json({"type": "done"})

    # Default to a None whisper so that if every retry fails we fall through to
    # the "busy" branch below and signal main.py not to persist anything.
    whisper_label, whisper_text = "Insight", None
    start = time.perf_counter()
    for attempt in range(3):
        try:
            whisper_label, whisper_text = whisper_agent(history, user_message, full_reply, past_patterns)
            gemini_calls.labels(agent="whisper", outcome="ok").inc()
            break
        except Exception as e:
            err = str(e)
            print(f"Whisper attempt {attempt + 1} failed: {e}")
            # Unlike the conversation agent we still retry on quota here (the
            # whisper is best-effort and not in the user's critical path), but we
            # label the outcome so quota vs. generic errors stay distinguishable.
            if "429" in err or "RESOURCE_EXHAUSTED" in err:
                gemini_calls.labels(agent="whisper", outcome="quota").inc()
            else:
                gemini_calls.labels(agent="whisper", outcome="error").inc()
            # Reset so a partial/failed attempt never leaks a stale value out of
            # the loop if the next attempt also throws.
            whisper_text = None
            await asyncio.sleep(1.5)
    agent_latency.labels(agent="whisper").observe(time.perf_counter() - start)

    if whisper_text:
        # Strip + validate citations before the note is shown or persisted.
        whisper_text, grounding_status = verify_grounding(whisper_text, past_patterns)
        whisper_grounding.labels(status=grounding_status).inc()
        await websocket.send_json({"type": "whisper", "content": whisper_text, "label": whisper_label})
    else:
        # All whisper attempts failed: show transient filler. whisper_text stays
        # None so main.py skips persistence and this message is never replayed.
        await websocket.send_json({
            "type": "whisper",
            "content": "Muse is momentarily busy (the model is under load) — try another exchange.",
            "label": "Insight",
        })

    # Record this mentor message as a memory for future turns. Done at the end so
    # it can't influence retrieval for the turn that created it.
    add_memory(user_id, user_message)

    return full_reply, whisper_text