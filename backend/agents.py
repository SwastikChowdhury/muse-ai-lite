import os
from dotenv import load_dotenv
from google import genai
from google.genai import types
from llm_metrics import record_usage

load_dotenv()
client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

MENTEE_SYSTEM_PROMPT = """You are role-playing as a mentee in a practice mentoring conversation. \
The person talking to you is your mentor, giving you feedback on a proposal you worked hard on. \
Play the mentee realistically: you care about doing well, you're a little insecure about whether \
your work landed, and you can be slightly defensive at first but are ultimately receptive to good \
feedback. Keep replies short and natural, like real chat messages. Stay fully in character as the \
mentee — never break character, never give meta commentary, never act like an AI assistant."""

WHISPER_SYSTEM_PROMPT = """You are Muse, a perceptive and warm communication coach. You privately \
observe a practice conversation between a mentor (the person you advise) and a mentee. You speak \
ONLY to the mentor, never to the mentee.

After each exchange, give the mentor exactly ONE short coaching note (1-2 sentences) that:
- reads the mentee's emotional tone and any subtext beneath their words,
- observes how the mentor's most recent message is landing,
- suggests a concrete next move, optionally with a brief example phrasing in quotes, and
- if past-session notes are provided and you notice a recurring habit, gently point it out.

Address the mentor as "you". Be specific and insightful, not generic. Output only the coaching \
note — no preamble, no labels."""


def build_contents(history, user_message):
    contents = []
    for m in history:
        role = "user" if m["role"] == "user" else "model"
        contents.append({"role": role, "parts": [{"text": m["content"]}]})
    contents.append({"role": "user", "parts": [{"text": user_message}]})
    return contents


# Better for the demo (needs billing):
#   "gemini-3.5-flash"            # $1.50 / $9.00  · near-Pro quality at Flash speed — best responses (Recommended)
#   "gemini-3-flash"              # $0.50 / $3.00  · cheaper middle ground
#   "gemini-2.5-flash"            # $0.30 / $2.50  · current
def conversation_agent_stream(history, user_message):
    contents = build_contents(history, user_message)
    return client.models.generate_content_stream(
        model="gemini-2.5-flash",
        contents=contents,
        config=types.GenerateContentConfig(system_instruction=MENTEE_SYSTEM_PROMPT),
    )


#   "gemini-2.5-flash-lite"     # $0.10 / $0.40  · current
#   "gemini-3.1-flash-lite"       # $0.25 / $1.50  · newer, very low latency (Recommended)
def whisper_agent(history, user_message, mentee_reply, past_patterns=None):
    lines = []
    for m in history:
        speaker = "Mentor" if m["role"] == "user" else "Mentee"
        lines.append(f"{speaker}: {m['content']}")
    lines.append(f"Mentor: {user_message}")
    lines.append(f"Mentee: {mentee_reply}")
    transcript = "\n".join(lines)

    memory_context = ""
    if past_patterns:
        joined = "\n".join(f"- {p}" for p in past_patterns)
        memory_context = f"\n\nNotes from this mentor's PAST sessions (look for recurring habits):\n{joined}"

    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=f"Conversation so far:\n\n{transcript}{memory_context}\n\n"
                 f"Give the mentor one short coaching note about the latest exchange.",
        config=types.GenerateContentConfig(system_instruction=WHISPER_SYSTEM_PROMPT),
    )
    
    record_usage("whisper", response.usage_metadata)
    
    return response.text.strip()
