import os
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

load_dotenv()

client = AsyncIOMotorClient(os.environ["MONGODB_URI"])
db = client["muse"]
messages_collection = db["messages"]
whispers_collection = db["whispers"]



async def save_message(message) -> None:
    await messages_collection.insert_one(message.model_dump())


async def get_history(user_id: str, conversation_id: str) -> list[dict]:
    cursor = messages_collection.find(
        {"user_id": user_id, "conversation_id": conversation_id}
    ).sort("created_at", 1)
    return await cursor.to_list(length=1000)

async def save_whisper(message) -> None:
    await whispers_collection.insert_one(message.model_dump())


async def get_whispers(user_id: str, conversation_id: str) -> list[dict]:
    cursor = whispers_collection.find(
        {"user_id": user_id, "conversation_id": conversation_id}
    ).sort("created_at", 1)
    return await cursor.to_list(length=1000)