import os
from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv()

client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

MENTEE_SYSTEM_PROMPT = """You are role-playing as a mentee in a practice mentoring conversation. \
The person talking to you is your mentor, giving you feedback on a proposal you worked hard on. \
Play the mentee realistically: you care about doing well, you're a little insecure about whether \
your work landed, and you can be slightly defensive at first but are ultimately receptive to good \
feedback. Keep replies short and natural, like real chat messages. Stay fully in character as the \
mentee — never break character, never give meta commentary, never act like an AI assistant."""


def build_contents(history, user_message):
    """Turn stored history + the new message into Gemini's multi-turn format.
    The mentor (user) maps to 'user'; the mentee (assistant) maps to 'model'."""
    contents = []
    for m in history:
        role = "user" if m["role"] == "user" else "model"
        contents.append({"role": role, "parts": [{"text": m["content"]}]})
    contents.append({"role": "user", "parts": [{"text": user_message}]})
    return contents


def conversation_agent_stream(history, user_message):
    """The Conversation Agent: plays the mentee, replying to the mentor."""
    contents = build_contents(history, user_message)
    return client.models.generate_content_stream(
        model="gemini-2.5-flash",
        contents=contents,
        config=types.GenerateContentConfig(system_instruction=MENTEE_SYSTEM_PROMPT),
    )