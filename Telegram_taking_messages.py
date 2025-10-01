from pyrogram import Client
from collections import defaultdict
import requests
import asyncio
import json
import config

SESSION_NAME = config.SESSION_NAME
API_ID = config.API_ID
API_HASH = config.API_HASH
TRACKED_CHANNELS = config.TRACKED_CHANNELS
NUM_MESSAGES = config.NUM_MESSAGES
NUM_MESSAGES_TO_SCOUT = config.NUM_MESSAGES_TO_SCOUT
database_ipaddress = config.database_ipaddress
database_port = config.database_port
user_id = config.user_id

base_url = f"http://{database_ipaddress}:{database_port}"
health_url = f"{base_url}/health"

try:
    response_health = requests.get(health_url, timeout=2)  # optional timeout
    response_data = response_health.json()
except requests.exceptions.RequestException as e:
    print(f"❌ Could not reach database server: {e}")
    response_data = None

messages_url = f"{base_url}/messages/"

def scout_messages(messages):
    """
    Scout messages to group them by media_group_id.
    Expects a list of messages (already fetched), returns list of groups:
    [
        {"media_group_id": ..., "ids": [msg.id, ...]},
        ...
    ]
    """
    groups = []
    current_group = None

    for msg in messages:
        mgid = getattr(msg, "media_group_id", None)
        mid = msg.id

        if mgid:  # Message is part of a media group
            if current_group and current_group["media_group_id"] == mgid:
                # Append to existing group
                current_group["ids"].append(mid)
            else:
                # Finish previous group
                if current_group:
                    groups.append(current_group)
                # Start new group
                current_group = {"media_group_id": mgid, "ids": [mid]}
        else:  # Single message
            # Finish previous group if exists
            if current_group:
                groups.append(current_group)
                current_group = None
            # Append single-message group
            groups.append({"media_group_id": None, "ids": [mid]})

    # Append last group if exists
    if current_group:
        groups.append(current_group)

    return groups


def normalize_messages(messages):
    lookup = {}
    for m in messages:
        key = m["message_media_group_id"] or m["message_id"]  # group id takes precedence

        if key not in lookup:
            # Initialize with current message_edit_date
            edit_dates = [m["message_edit_date"]] if m["message_edit_date"] else []
            lookup[key] = {
                "message_id": m["message_id"],
                "message_media_group_id": m["message_media_group_id"],
                "message_date": m["message_date"],
                "message_edit_date": ",".join(edit_dates),
                "messages_entities": m.get("messages_entities") or "",
                "text": m.get("text") or "",
            }
        else:
            # Append new edit_date
            if m["message_edit_date"]:
                existing_dates = lookup[key]["message_edit_date"].split(",")
                existing_dates.append(m["message_edit_date"])
                lookup[key]["message_edit_date"] = ",".join(existing_dates)

            # Also append message_id if needed
            existing_ids = lookup[key]["message_id"].split(",")
            existing_ids.append(m["message_id"])
            lookup[key]["message_id"] = ",".join(existing_ids)

    return lookup

def serialize_entities(entities):
    if not entities:
        return None
    result = []
    for e in entities:
        # Only include JSON-serializable attributes
        entity_dict = {
            "type": str(e.type),  # convert enum/type to string
            "offset": e.offset,
            "length": e.length,
        }
        if getattr(e, "user", None):
            entity_dict["user"] = e.user
        if getattr(e, "language", None):
            entity_dict["language"] = e.language
        # Include optional document_id if exists
        if getattr(e, "custom_emoji_id", None):
            entity_dict["custom_emoji_id"] = e.custom_emoji_id
        # Include optional url if exists
        if getattr(e, "url", None):
            entity_dict["url"] = e.url
        result.append(entity_dict)
    return json.dumps(result)

async def scout_edits(CHANNEL_USERNAME):
    async with Client(SESSION_NAME, API_ID, API_HASH) as app:
        messages = []
        async for msg in app.get_chat_history(CHANNEL_USERNAME, limit=NUM_MESSAGES_TO_SCOUT):
            text = getattr(msg, "caption", None) or getattr(msg, "text", None)
            entities = getattr(msg, "caption_entities", None) or getattr(msg, "entities", None)
            entities_serialized = serialize_entities(entities)
            messages.append({
                "message_id": str(msg.id),
                "message_media_group_id": str(msg.media_group_id) if msg.media_group_id else None,
                "message_date": str(msg.date),
                "message_edit_date": str(msg.edit_date) if msg.edit_date else None,
                "messages_entities": entities_serialized if entities_serialized else None,
                "text": text or "",
            })

    # Ask DB what it already has
    response = requests.get(
        f"http://{database_ipaddress}:{database_port}/update_status/{user_id}/{CHANNEL_USERNAME}?limit={NUM_MESSAGES_TO_SCOUT}"
    )
    db_messages = response.json()["updates"]

    # Normalize both sides
    tg_lookup = normalize_messages(messages)
    db_lookup = normalize_messages(db_messages)
    # Compare
    updates = {"unknown": [], "edited": []}
    for key, tg_msg in tg_lookup.items():
        if key not in db_lookup:
            updates["unknown"].append(tg_msg)
        else:
            db_msg = db_lookup[key]

            if tg_msg["message_media_group_id"] is None:
                if tg_msg["message_edit_date"] != db_msg["message_edit_date"]:
                    updates["edited"].append(tg_msg)
            if tg_msg["message_media_group_id"] is not None:
                tg_edit_dates = tg_msg["message_edit_date"].split(",")
                db_edit_dates = db_msg["message_edit_date"].split(",")
                if db_edit_dates and (
                        not any(tg_date in db_edit_dates for tg_date in tg_edit_dates)
                        and any(tg_date > max(db_edit_dates) for tg_date in tg_edit_dates)
                ):
                    latest_tg_edit = max(tg_edit_dates)
                    tg_msg["message_edit_date"] = latest_tg_edit
                    updates["edited"].append(tg_msg)

    return updates
# --- FUNCTION TO FETCH MESSAGES ---
async def fetch_messages(CHANNEL_USERNAME):

    messages_by_group = defaultdict(list)
    single_messages = []
    filtered_messages = []

    async with Client(SESSION_NAME, API_ID, API_HASH) as app:
        # Fetch messages once
        messages = []
        async for msg in app.get_chat_history(CHANNEL_USERNAME, limit=NUM_MESSAGES):
            messages.append(msg)

    response = requests.get(
        f"http://{database_ipaddress}:{database_port}/update_status/{user_id}/{CHANNEL_USERNAME}?limit={NUM_MESSAGES+20}"
    )
    db_messages = response.json()["updates"]
    db_keys = set()
    for m in db_messages:
        key = m["message_media_group_id"] or m["message_id"]
        db_keys.add(key)

    # Filter Telegram messages
    for msg in messages:
        key = str(msg.media_group_id) if msg.media_group_id else str(msg.id)
        if key not in db_keys:
            filtered_messages.append(msg)

    # Scout to get groups
    groups = scout_messages(filtered_messages)

    # Map IDs back to actual messages
    msg_dict = {msg.id: msg for msg in filtered_messages}

    for group in groups:
        mgid = group["media_group_id"]
        ids = group["ids"]
        if mgid:
            # Add all messages in this group
            messages_by_group[mgid].extend([msg_dict[mid] for mid in ids])
        else:
            # Single message
            single_messages.extend([msg_dict[mid] for mid in ids])

    return messages_by_group, single_messages

def prepare_message_for_db(msg):
    entities = getattr(msg, "caption_entities", None) or getattr(msg, "entities", None)
    return {
        "message_id": str(msg.id),
        "message_media_group_id": str(msg.media_group_id) if msg.media_group_id else None,
        "user_id": user_id,
        "channel_id": msg.chat.username or str(msg.chat.id),
        "message_media": str(msg.media) if msg.media else None,
        "message_date": str(msg.date),
        "message_edit_date": str(msg.edit_date) if msg.edit_date else None,
        "message_forward_from": None,
        "message_forward_from_chat": None,
        "message_reply_to_message_id": msg.reply_to_message_id if msg.reply_to_message_id else None,
        "messages_entities": serialize_entities(entities) if entities else None,
        "text": msg.text or "",
        "status": "new",
        "is_protected": msg.has_protected_content
    }

def prepare_messages_for_db(all_messages, messages_by_group):
    """
    Prepare message dicts for database insertion.
    Handles media groups by combining media and taking first non-empty text.
    """
    message_dicts = []
    logged_groups = set()

    for msg in all_messages:
        mgid = getattr(msg, "media_group_id", None)

        # If part of a group and already logged, skip
        if mgid and mgid in logged_groups:
            continue

        if mgid:
            # Process the whole group
            group_msgs = messages_by_group[mgid]
            media_list = [str(getattr(m, "media", None)) for m in group_msgs]
            text = next(
                (getattr(m, "caption", None) or getattr(m, "text", None)
                 for m in group_msgs if getattr(m, "caption", None) or getattr(m, "text", None)),
                None
            )
            entities = next(
                (
                    getattr(m, "caption_entities", None) or getattr(m, "entities", None)
                    for m in group_msgs
                    if getattr(m, "caption_entities", None) or getattr(m, "entities", None)
                ),
                None
            )
            entities_serialized = serialize_entities(entities)
            max_edit_date = max(
                (getattr(m, "edit_date", None) for m in group_msgs if getattr(m, "edit_date", None)),
                default=None
            )
            first_msg = group_msgs[0]
            message_dicts.append({
                "message_id": ','.join(str(m.id) for m in group_msgs),
                "message_media_group_id": str(mgid),
                "user_id": user_id,
                "channel_id": first_msg.chat.username or str(first_msg.chat.id),
                "message_media": ','.join(media_list),
                "message_date": str(first_msg.date),
                "message_edit_date": str(max_edit_date) if max_edit_date else None,
                "message_forward_from": None,
                "message_forward_from_chat": None,
                "message_reply_to_message_id": first_msg.reply_to_message_id if first_msg.reply_to_message_id else None,
                "messages_entities": entities_serialized,
                "text": text,
                "status": "new",
                "is_protected": first_msg.has_protected_content
            })
            logged_groups.add(mgid)

        else:
            text = getattr(msg, "caption", None) or getattr(msg, "text", None)
            entities = getattr(msg, "caption_entities", None) or getattr(msg, "entities", None)
            entities_serialized = serialize_entities(entities)
            # Single message
            message_dicts.append({
                "message_id": str(msg.id),
                "message_media_group_id": None,
                "user_id": user_id,
                "channel_id": msg.chat.username or str(msg.chat.id),
                "message_media": str(msg.media) if msg.media else None,
                "message_date": str(msg.date),
                "message_edit_date": str(msg.edit_date) if msg.edit_date else None,
                "message_forward_from": None,
                "message_forward_from_chat": None,
                "message_reply_to_message_id": msg.reply_to_message_id if msg.reply_to_message_id else None,
                "messages_entities": entities_serialized,
                "text": text or "",
                "status": "new",
                "is_protected": msg.has_protected_content
            })

    return message_dicts

def push_message_to_db(message_dict):
    """
    Push a single message dictionary to the FastAPI database server.
    """
    #print(message_dict)
    try:
        response = requests.post(messages_url, json=message_dict)
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"❌ Failed to push message: {e}")
        return None

def push_updates_to_db(updates_dict, CHANNEL_USERNAME):
    """
    Push a single updates dictionary to the FastAPI database server for edited messages.
    Adds user_id and channel_id to match the UpdatesPayload model.
    """
    # Add the required fields
    payload = {
        "user_id": user_id,          # your global or passed user_id
        "channel_id": str(CHANNEL_USERNAME),
        "unknown": updates_dict.get("unknown", []),
        "edited": updates_dict.get("edited", [])
    }

    url = f"http://{database_ipaddress}:{database_port}/apply_updates/"

    try:
        response = requests.post(url, json=payload, timeout=5)
        #print(response.json())
    except requests.exceptions.RequestException as e:
        print(f"❌ Request failed: {e}")

async def new_message_taker():
    for channel in TRACKED_CHANNELS:
        # 0. Fetch messages
        messages_by_group, single_messages = await fetch_messages(channel)

        if messages_by_group or single_messages:
            # 1. Combine all messages
            all_messages = []
            for group_msgs in messages_by_group.values():
                all_messages.extend(group_msgs)
            all_messages.extend(single_messages)

            # 2. Sort by message ID
            all_messages.sort(key=lambda msg: msg.id)
            # print(all_messages)
            if all_messages:
                first_msg = all_messages[0]
                mgid = getattr(first_msg, "media_group_id", None)

                if mgid is not None:
                    # Find all messages with the same media_group_id
                    group_msgs = [msg for msg in all_messages if getattr(msg, "media_group_id", None) == mgid]

                    # Remove first_msg from all_messages
                    all_messages = [msg for msg in all_messages if msg not in group_msgs or msg == first_msg]

            # 3. Push to DB
            msg_dicts = prepare_messages_for_db(all_messages, messages_by_group)
            #print(f"Channel {channel}: {len(msg_dicts)} messages found in this loop")
            for msg in msg_dicts:
                # print(msg)
                #print(msg.get("message_edit_date"))
                #print(msg.get("text"))
                result = push_message_to_db(msg)
                # print(result)

async def edits_taker():
    for channel in TRACKED_CHANNELS:
        updates = await scout_edits(channel)
        if updates:
            #print(updates["edited"])
            print(f"Total edited messages found in this loop: {len(updates['edited'])}")
            result = push_updates_to_db(updates, channel)
            #print(result)

# Load the existing session
async def main():
    for channel in TRACKED_CHANNELS:
        # 0. Fetch messages
        messages_by_group, single_messages = await fetch_messages(channel)

        if messages_by_group or single_messages:
            # 1. Combine all messages
            all_messages = []
            for group_msgs in messages_by_group.values():
                all_messages.extend(group_msgs)
            all_messages.extend(single_messages)

            # 2. Sort by message ID
            all_messages.sort(key=lambda msg: msg.id)
            # print(all_messages)
            if all_messages:
                first_msg = all_messages[0]
                mgid = getattr(first_msg, "media_group_id", None)

                if mgid is not None:
                    # Find all messages with the same media_group_id
                    group_msgs = [msg for msg in all_messages if getattr(msg, "media_group_id", None) == mgid]

                    # Remove first_msg from all_messages
                    all_messages = [msg for msg in all_messages if msg not in group_msgs or msg == first_msg]

            # 3. Push to DB
            msg_dicts = prepare_messages_for_db(all_messages, messages_by_group)
            for msg in msg_dicts:
                # print(msg)
                print(msg.get("message_edit_date"))
                print(msg.get("text"))
                result = push_message_to_db(msg)
                # print(result)

        updates = await scout_edits(channel)
        if updates:
            print(updates["edited"])
            result = push_updates_to_db(updates, channel)
            print(result)

if __name__ == "__main__":
    if response_data and response_data.get("status") == "ok":
        asyncio.run(main())
    else:
        print("❌ Database server is not available. Exiting or retrying...")