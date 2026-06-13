"""MongoDB connection and helpers using Motor (async driver)."""

import os
from typing import Optional

import motor.motor_asyncio
from dotenv import load_dotenv

load_dotenv()

MONGO_URI: str = os.getenv("MONGODB_URI", "mongodb://localhost:27017/resume-builder")

_client: Optional[motor.motor_asyncio.AsyncIOMotorClient] = None
_db = None


async def connect_db() -> None:
    global _client, _db
    try:
        _client = motor.motor_asyncio.AsyncIOMotorClient(
            MONGO_URI,
            serverSelectionTimeoutMS=10_000,
        )
        await _client.admin.command("ping")
        # derive DB name from the URI path, defaulting to "resume-builder"
        db_name = (MONGO_URI.rstrip("/").rsplit("/", 1)[-1].split("?")[0]) or "resume-builder"
        _db = _client[db_name]
        print(f"MongoDB connected successfully → {db_name}")
    except Exception as exc:
        print(f"MongoDB connection warning (server will still start): {exc}")


def users_col():
    """Return the users collection. Raises if DB is not yet initialised."""
    if _db is None:
        raise RuntimeError("Database not connected. Ensure connect_db() ran at startup.")
    return _db["users"]
