from fastapi import FastAPI, Body
from pydantic import BaseModel
from typing import List, Optional
import sqlite3
#import SQLite_database

# Rename the FastAPI instance
tg_database = FastAPI(title="TeleMessageHub")  # <-- custom name for uvicorn

# Pydantic model for input
class MessageInput(BaseModel):
    message_id: str
    message_media_group_id: Optional[str] = None
    user_id: int
    channel_id: str
    message_media: Optional[str] = None
    message_date: Optional[str] = None
    message_edit_date: Optional[str] = None
    message_forward_from: Optional[str] = None
    message_forward_from_chat: Optional[str] = None
    message_reply_to_message_id: Optional[int] = None
    messages_entities: Optional[str] = None
    text: str
    status: str
    is_protected: Optional[bool] = False

class EditedMessage(BaseModel):
    message_id: str
    message_media_group_id: Optional[str] = None
    message_date: str
    message_edit_date: Optional[str] = None
    messages_entities: Optional[str] = None
    text: str

class UpdateTracking(BaseModel):
    message_id: str             # source message
    target_channel_id: str      # target Telegram channel
    target_message_id: str      # target Telegram message ID

class UpdateCheckTracking(BaseModel):
    message_id: str   # source message(s)

class FilterRequest(BaseModel):
    message_id: str

class UpdatesPayload(BaseModel):
    user_id: str
    channel_id: str
    unknown: List[EditedMessage] = []
    edited: List[EditedMessage] = []

@tg_database.on_event("startup")
def create_tables():
    conn = sqlite3.connect("messages.db")
    c = conn.cursor()
    # Create table with pairs
    c.execute("""
        CREATE TABLE IF NOT EXISTS message_links (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            channel_id TEXT,
            message_id TEXT,
            target_channel_id TEXT,
            target_message_id TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)
    # Create table with message_id
    c.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                message_id TEXT,
                message_media_group_id TEXT,
                user_id INTEGER,
                channel_id TEXT,
                message_media TEXT,
                message_date TEXT,
                message_edit_date TEXT,
                message_forward_from TEXT,
                message_forward_from_chat TEXT,
                message_reply_to_message_id INTEGER,
                messages_entities TEXT,
                text TEXT,
                status TEXT,
                is_protected BOOLEAN DEFAULT FALSE
            )
        """)
    conn.commit()
    conn.close()

@tg_database.post("/messages/")
def add_message(msg: MessageInput):
    conn = sqlite3.connect("messages.db")
    c = conn.cursor()

    # Insert new message including message_id
    c.execute(
        """
        INSERT INTO messages (
            message_id, message_media_group_id, user_id, channel_id, message_media, message_date, 
            message_edit_date, message_forward_from, message_forward_from_chat, 
            message_reply_to_message_id, messages_entities, text, status, is_protected
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            msg.message_id,
            getattr(msg, "message_media_group_id", None),
            msg.user_id,
            msg.channel_id,
            getattr(msg, "message_media", None),
            getattr(msg, "message_date", None),
            getattr(msg, "message_edit_date", None),
            getattr(msg, "message_forward_from", None),
            getattr(msg, "message_forward_from_chat", None),
            getattr(msg, "message_reply_to_message_id", None),
            getattr(msg, "messages_entities", None),
            msg.text,
            msg.status,
            msg.is_protected
        )
    )

    conn.commit()
    conn.close()
    return {"status": "success", "message": msg.text}

# Endpoint to get messages
@tg_database.get("/messages/{user_id}/{channel_id}")
def get_messages(user_id: int, channel_id: str, limit: int = 10):
    conn = sqlite3.connect("messages.db")
    c = conn.cursor()
    # Select all relevant columns including user_id and channel_id
    c.execute("""
        SELECT 
            message_id, message_media_group_id, user_id, channel_id, message_media, message_date, 
            message_edit_date, message_forward_from, message_forward_from_chat, 
            message_reply_to_message_id, messages_entities, text, status, is_protected
        FROM messages 
        WHERE user_id=? AND channel_id=? 
        ORDER BY id DESC 
        LIMIT ?
    """, (user_id, channel_id, limit))

    rows = c.fetchall()
    conn.close()

    messages = [
        {
            "message_id": row[0],
            "message_media_group_id": row[1],
            "user_id": row[2],
            "channel_id": row[3],
            "message_media": row[4],
            "message_date": row[5],
            "message_edit_date": row[6],
            "message_forward_from": row[7],
            "message_forward_from_chat": row[8],
            "message_reply_to_message_id": row[9],
            "messages_entities": row[10],
            "text": row[11],
            "status": row[12],
            "is_protected": row[13]
        }
        for row in rows
    ]

    return {
        "user_id": user_id,
        "channel_id": channel_id,
        "messages": messages
    }

@tg_database.get("/update_status/{user_id}/{channel_id}")
def get_update_status(user_id: int, channel_id: str, limit: int = 10):
    conn = sqlite3.connect("messages.db")
    c = conn.cursor()
    # Select only necessary columns with limit
    c.execute("""
           SELECT message_id, message_media_group_id, message_date, message_edit_date
           FROM messages
           WHERE user_id=? AND channel_id=?
           ORDER BY message_date DESC
           LIMIT ?
       """, (user_id, channel_id, limit))

    rows = c.fetchall()
    conn.close()

    updates = [
        {
            "message_id": row[0],
            "message_media_group_id": row[1],
            "message_date": row[2],
            "message_edit_date": row[3]
        }
        for row in rows
    ]

    return {"user_id": user_id, "channel_id": channel_id, "updates": updates}

@tg_database.post("/apply_updates/")
async def apply_updates(updates: UpdatesPayload):
    try:
        conn = sqlite3.connect("messages.db")
        c = conn.cursor()

        for msg in updates.edited:
            c.execute("""
                UPDATE messages
                SET message_edit_date = ?,
                    text = ?,
                    messages_entities = ?,
                    status = 'edited'
                WHERE channel_id = ?
                  AND (
                      (message_media_group_id IS NOT NULL AND message_media_group_id = ?)
                      OR (message_media_group_id IS NULL AND message_id = ?)
                  )
            """, (
                msg.message_edit_date,
                msg.text,
                msg.messages_entities,
                updates.channel_id,
                msg.message_media_group_id,
                msg.message_id
            ))

        conn.commit()
        return {"status": "ok"}

    except Exception as e:
        return {"status": "error", "message": str(e)}

    finally:
        conn.close()

@tg_database.get("/processing/{user_id}/{channel_id}")
def get_messages_to_process(user_id: int, channel_id: str, limit: int = 10):
    conn = sqlite3.connect("messages.db")
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    c.execute("""
            SELECT message_id, user_id, channel_id, messages_entities, text, status, is_protected
            FROM messages
            WHERE user_id = ? AND channel_id = ? 
              AND status IN ('new', 'edited')
            ORDER BY id ASC
            LIMIT ?
        """, (user_id, channel_id, limit))

    rows = [dict(row) for row in c.fetchall()]

    conn.close()
    return {"messages": rows}

@tg_database.post("/filtering/{user_id}/{channel_id}")
async def apply_filtering(user_id: int, channel_id: str, request: FilterRequest):
    message_id = request.message_id
    conn = sqlite3.connect("messages.db")
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    try:
        c.execute("""
            UPDATE messages
            SET status = 'filtered'
            WHERE user_id = ? AND channel_id = ? AND message_id = ?
              AND status IN ('new', 'edited')
        """, (user_id, channel_id, message_id))

        if c.rowcount == 0:
            return {"status": "error", "message missed or status changed for": message_id}

        conn.commit()
        return {"status": "ok", "filtered_message_id": message_id}
    finally:
        conn.close()

@tg_database.post("/tracking/{user_id}/{channel_id}")
async def update_tracking(user_id: int, channel_id: str, request: UpdateTracking):
    conn = sqlite3.connect("messages.db")
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("""
            INSERT INTO message_links (user_id, channel_id, message_id, target_channel_id, target_message_id)
            VALUES (?, ?, ?, ?, ?)
        """, (user_id, channel_id, request.message_id, request.target_channel_id, request.target_message_id))

    conn.commit()
    conn.close()

    return {
        "status": "ok",
        "source_message_id": request.message_id,
        "target_channel_id": request.target_channel_id,
        "target_message_id": request.target_message_id
    }

@tg_database.post("/tracking_check/{user_id}/{channel_id}")
async def tracking_check(user_id: int, channel_id: str, request: UpdateCheckTracking):
    conn = sqlite3.connect("messages.db")
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    c.execute("""
        SELECT * FROM message_links
        WHERE user_id = ? AND channel_id = ? AND message_id = ?
    """, (user_id, channel_id, request.message_id))
    row = c.fetchone()
    conn.close()

    if row:
        return {
            "status": "ok",
            "source_message_id": request.message_id,
            "target_channel_id": row["target_channel_id"],
            "target_message_id": row["target_message_id"]
        }
    else:
        return {
            "status": "not_found",
            "source_message_id": request.message_id
        }

@tg_database.get("/health")
def health():
    return {"status": "ok"}

