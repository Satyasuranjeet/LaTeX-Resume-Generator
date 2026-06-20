"""MongoDB connection and helpers using Motor (async driver)."""

import os
from urllib.parse import urlparse
from typing import Optional

import motor.motor_asyncio
from dotenv import load_dotenv

load_dotenv()

MONGO_URI: str = os.getenv("MONGODB_URI", "mongodb://localhost:27017/resume-builder")

_client: Optional[motor.motor_asyncio.AsyncIOMotorClient] = None
_db = None


def get_db():
    """Lazily initialize and return the database client."""
    global _client, _db
    if _db is None:
        try:
            _client = motor.motor_asyncio.AsyncIOMotorClient(
                MONGO_URI,
                serverSelectionTimeoutMS=10_000,
            )
            parsed_uri = urlparse(MONGO_URI)
            db_name = parsed_uri.path.strip("/") or "resume-builder"
            _db = _client[db_name]
        except Exception as exc:
            print(f"MongoDB lazy initialization error: {exc}")
            raise
    return _db


async def connect_db() -> None:
    """Pre-initialize database and ping to verify connectivity on startup."""
    try:
        db = get_db()
        if _client is not None:
            await _client.admin.command("ping")
            parsed_uri = urlparse(MONGO_URI)
            db_name = parsed_uri.path.strip("/") or "resume-builder"
            print(f"MongoDB connected successfully -> {db_name}")
    except Exception as exc:
        print(f"MongoDB startup connection warning: {exc}")


def users_col():
    """Return the users collection. Lazily initializes if needed."""
    db = get_db()
    return db["users"]
