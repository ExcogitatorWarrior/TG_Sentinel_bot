# Telegram_AI_processor.py
import os
import time
import requests
import ast
import bisect
import re
from pyrogram import Client
from pyrogram.types import InputMediaDocument, InputMediaPhoto, InputMediaVideo, MessageEntity, User
from pyrogram.enums import MessageEntityType
from pyrogram.errors import MediaCaptionTooLong
from pyrogram.errors.exceptions.bad_request_400 import MessageNotModified
import json
import config


# Telegram API session
SESSION_NAME = config.SESSION_NAME
API_ID = config.API_ID       # from my.telegram.org
API_HASH = config.API_HASH

# Database configuration
database_ipaddress = config.database_ipaddress
database_port = config.database_port
DB_API = f"http://{database_ipaddress}:{database_port}"    # your FastAPI DB server

# LLM configuration
llm_ipaddress = config.llm_ipaddress
llm_port = config.llm_port
LLM_API = f"http://{llm_ipaddress}:{llm_port}"             # your LLM suitcase server

# Channels and users
TRACKED_CHANNELS = config.TRACKED_CHANNELS
TARGET_CHANNEL = config.TARGET_CHANNEL
user_id = config.user_id

# Scoring parameters
Scoring_parameter = config.Scoring_parameter
Scoring_messaging_gap = config.Scoring_messaging_gap

# Transfer method
REMOVE_CUSTOM_EMOJI = config.REMOVE_CUSTOM_EMOJI
TRANSFERING_METHOD = config.TRANSFERING_METHOD

# Prompt template
prompt_template = config.prompt_template

def parse_ad_score(llm_response: str) -> int | None:
    match = re.search(fr"\[{Scoring_parameter}:\s*(\d+)\]", llm_response)
    if match:
        return int(match.group(1))
    return None

def convert_to_int_array(input_string: str):
    """
    Converts a string into a list of integers.
    - If the string contains a single number, return a list with that integer.
    - If the string contains multiple comma-separated numbers, return a list of integers.
    - Strips extra spaces and handles edge cases gracefully.
    """
    # Remove any extra spaces
    input_string = input_string.strip()

    # Check if the input is an empty string
    if not input_string:
        return []  # Return an empty list if the input is empty

    # If the string contains commas, handle as multiple numbers
    if ',' in input_string:
        try:
            # Return a list of integers, stripping extra spaces around each number
            return [int(num.strip()) for num in input_string.split(',') if num.strip()]
        except ValueError:
            raise ValueError("Invalid input: all items must be valid integers.")
    else:
        # If it's a single number, return it as a list with one element
        try:
            return [int(input_string)]  # Return as a list with a single integer
        except ValueError:
            raise ValueError("Invalid input: the string must be a valid integer.")


def parse_entities_from_json(entities_json, client=None):
    """
    Convert a JSON string or list of dicts representing message entities
    into a list of Pyrogram MessageEntity objects.

    Args:
        entities_json (str or list): JSON string or already-parsed list of entity dicts.
        client (pyrogram.Client, optional): Client to assign to entities (some Pyrogram methods require it).

    Returns:
        List[MessageEntity]: List of Pyrogram MessageEntity objects.
    """
    if not entities_json:
        return []

    # Parse string if necessary
    if isinstance(entities_json, str):
        try:
            entities_list = json.loads(entities_json)
        except json.JSONDecodeError:
            print("Failed to parse entities JSON")
            return []
    else:
        entities_list = entities_json

    result_entities = []
    for e in entities_list:
        entity_type_str = e.get("type", "UNKNOWN").replace("MessageEntityType.", "")
        entity_type = getattr(MessageEntityType, entity_type_str, MessageEntityType.UNKNOWN)

        user_obj = None
        if "user" in e and e["user"]:
            # You can expand this if your user dict is more complex
            user_obj = User(
                id=e["user"].get("id"),
                is_bot=e["user"].get("is_bot", False),
                first_name=e["user"].get("first_name"),
                last_name=e["user"].get("last_name"),
                username=e["user"].get("username"),
                language_code=e["user"].get("language_code"),
                is_premium=e["user"].get("is_premium", False),
                added_to_attachment_menu=e["user"].get("added_to_attachment_menu", False)
            )

        msg_entity = MessageEntity(
            type=entity_type,
            offset=e.get("offset", 0),
            length=e.get("length", 0),
            url=e.get("url"),
            user=user_obj,
            language=e.get("language"),
            custom_emoji_id=e.get("custom_emoji_id")
        )

        if client:
            msg_entity._client = client  # attach client if needed for Pyrogram internals

        result_entities.append(msg_entity)

    return result_entities

def _parse_entities(entities_raw):
    """Parse messages_entities which may be a JSON string or a Python repr or a list."""
    if not entities_raw:
        return []
    if isinstance(entities_raw, list):
        return entities_raw
    s = entities_raw.strip()
    # Try JSON first
    try:
        return json.loads(s)
    except Exception:
        pass
    # Try python literal (e.g. single-quoted repr)
    try:
        return ast.literal_eval(s)
    except Exception:
        pass
    # Try a tiny sanitization: remove MessageEntityType. prefix and retry
    try:
        s2 = s.replace('MessageEntityType.', '')
        return json.loads(s2)
    except Exception:
        try:
            return ast.literal_eval(s2)
        except Exception:
            print("WARN: couldn't parse messages_entities (truncated):", s[:200])
            return []

def _build_utf16_prefix(text: str):
    """
    Build prefix array where prefix[i] = number of UTF-16 code units in text[:i].
    This allows mapping Telegram offsets (UTF-16 code units) to Python indices.
    """
    prefix = [0]
    for ch in text:
        # number of UTF-16 code units for this character
        units = len(ch.encode('utf-16-le')) // 2
        prefix.append(prefix[-1] + units)
    return prefix

def _utf16_index_to_py(prefix, utf16_index):
    """
    Convert a utf16_index (Telegram-style) to a python string index using prefix array.
    We use bisect_left so exact boundaries map correctly.
    """
    if utf16_index <= 0:
        return 0
    if utf16_index >= prefix[-1]:
        return len(prefix) - 1  # python index = number of chars
    return bisect.bisect_left(prefix, utf16_index)

def apply_entities_to_text(text: str, entities_raw) -> str:
    """
    Apply message entities to text producing Markdown-like formatting:
      - BOLD -> **text**
      - ITALIC -> *text*
      - TEXT_LINK -> [text](url)
      - CODE -> `text`
      - PRE -> ```text```
    Accepts entities as JSON string or list.
    """
    entities = _parse_entities(entities_raw)
    if not entities:
        return text

    # build utf-16 prefix map once
    prefix = _build_utf16_prefix(text)

    normalized = []
    for e in entities:
        try:
            offset = int(e.get("offset", 0))
            length = int(e.get("length", 0))
        except Exception:
            continue

        start = _utf16_index_to_py(prefix, offset)
        end = _utf16_index_to_py(prefix, offset + length)

        type_raw = e.get("type", "")
        # normalize e.g. "MessageEntityType.BOLD" -> "BOLD"
        if isinstance(type_raw, str) and "." in type_raw:
            type_clean = type_raw.split(".")[-1].upper()
        else:
            type_clean = str(type_raw).upper()

        normalized.append({
            "start": start,
            "end": end,
            "type": type_clean,
            "url": e.get("url")
        })

    # apply from back to front so indexes don't shift
    normalized.sort(key=lambda x: x["start"], reverse=True)

    def _escape_for_markdown(s):
        # minimal escaping for bracket/paren characters inside link text
        return s.replace("]", "\\]").replace("(", "\\(").replace(")", "\\)")

    for ent in normalized:
        s, e = ent["start"], ent["end"]
        if s < 0: s = 0
        if e < s: e = s
        if s >= len(text):
            continue
        if e > len(text):
            e = len(text)
        substring = text[s:e]

        t = ent["type"]
        if t == "BOLD":
            repl = f"**{substring}**"
        elif t == "STRIKETHROUGH":
            repl = f"~~{substring}~~"
        elif t == "ITALIC":
            repl = f"__{substring}__"
        elif t in ("TEXT_LINK", "URL", "TEXTURL"):
            url = ent.get("url")
            if url:
                repl = f"[{_escape_for_markdown(substring)}]({url})"
            else:
                repl = substring
        elif t == "CODE":
            repl = f"`{substring}`"
        elif t == "PRE":
            repl = f"```{substring}```"
        else:
            # unknown entity type — leave as-is (could add more types later)
            repl = substring

        text = text[:s] + repl + text[e:]

    return text

def fetch_one_message(user_id, channel_id):
    url = f"{DB_API}/processing/{user_id}/{channel_id}?limit=1"
    try:
        response = requests.get(url)
        response.raise_for_status()
        data = response.json()
        return data  # return the first message (dict with message_id, text, status, etc.)
    except Exception as e:
        print(f"Error fetching message: {e}")
        return None

def request_filtering(user_id: int, channel_id: str, message_id: int) -> dict:
    url = f"{DB_API}/filtering/{user_id}/{channel_id}"
    payload = {"message_id": message_id}
    try:
        response = requests.post(url, json=payload)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"Error filtering message {message_id}: {e}")
        return {"status": "error", "message_id": message_id}

def request_tracking(user_id: int, channel_id: str, message_id: str, target_channel_id: str, target_message_id: str):
    url = f"{DB_API}/tracking/{user_id}/{channel_id}"
    payload = {
        "message_id": message_id,
        "target_channel_id": target_channel_id,
        "target_message_id": target_message_id
    }
    try:
        response = requests.post(url, json=payload)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"Error updating tracking: {e}")
        return None

def request_tracking_check(user_id: int, channel_id: str, message_id: str) -> dict:
    url = f"{DB_API}/tracking_check/{user_id}/{channel_id}"
    payload = {"message_id": message_id}
    try:
        response = requests.post(url, json=payload)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"Error checking tracking: {e}")
        return {"status": "error", "message": str(e)}

def update_message_status(msg_id, status, new_text=None):
    payload = {"status": status}
    if new_text:
        payload["text"] = new_text
    resp = requests.post(f"{DB_API}/messages/{msg_id}/update", json=payload)
    return resp.json()

def analyze_message_with_llm(message: dict, max_tokens: int = 256) -> str:
    """
    Builds prompt from message, applying message entities (links, bold, etc.)
    so the LLM sees Markdown-style formatting.
    """
    raw_text = message.get("text", "") or ""
    entities_raw = message.get("messages_entities")

    formatted_text = apply_entities_to_text(raw_text, entities_raw)

    # debug: what we actually send to the LLM
    #print("Formatted text sent to LLM:")
    #print(formatted_text)

    prompt = prompt_template.format(
        channel_id=message.get("channel_id", "unknown"),
        text=formatted_text,
        Scoring_parameter=Scoring_parameter,
    )
    # Call the LLM API
    response = requests.post(
        f"{LLM_API}/generate",
        json={"prompt": prompt, "max_tokens": max_tokens}
    )

    if response.status_code == 200:
        return response.json().get("response", "").strip()
    else:
        raise RuntimeError(f"LLM API error {response.status_code}: {response.text}")

def process_forwarding(msg, message_ids, CHANNEL_USERNAME):
    with Client(SESSION_NAME, api_id=API_ID, api_hash=API_HASH) as app:
        try:
            app.forward_messages(
                chat_id=TARGET_CHANNEL,
                from_chat_id=CHANNEL_USERNAME,
                message_ids=message_ids
            )
        except Exception as e:
            print(f"Error from telegram API or Pyrogram while forwarding messages: {e}")

        # Call filter endpoint
        filter_result = request_filtering(
            msg['user_id'],
            msg['channel_id'],
            msg['message_id']
        )
        #print(filter_result)

        # Fetch latest messages from target channel
        latest_messages = list(app.get_chat_history(
            chat_id=TARGET_CHANNEL,
            limit=len(message_ids)
        ))

        target_message = ",".join(str(m.id) for m in latest_messages)
        #print(msg["message_id"])
        #print(target_message)

        # Track the mapping
        tracking_result = request_tracking(
            msg['user_id'],
            msg['channel_id'],
            msg['message_id'],
            str(TARGET_CHANNEL),
            target_message
        )
        #print(tracking_result)

def process_reloading(msg, message_ids, TRACKED_CHANNEL):
    with Client(SESSION_NAME, api_id=API_ID, api_hash=API_HASH) as app:
        channel_username = TRACKED_CHANNEL
        media_path = os.path.join("media", str(channel_username))
        os.makedirs(media_path, exist_ok=True)

        saved_files = []
        media_types = []

        # Download media from messages
        for message_id in message_ids:
            msg_obj = app.get_messages(chat_id=channel_username, message_ids=message_id)
            if msg_obj.media and not msg_obj.web_page:  # skip web_page for downloading
                # Preserve original file name if available
                if hasattr(msg_obj, "animation") and msg_obj.animation:
                    file_name = msg_obj.animation.file_name if msg_obj.animation.file_name else f"{message_id}.gif"
                    #print("This is an Animation (GIF) file!")

                # Check if it's a sticker
                elif hasattr(msg_obj, "sticker") and msg_obj.sticker:
                    file_name = msg_obj.sticker.file_name if msg_obj.sticker.file_name else f"{message_id}.webp"
                    #print("This is a Sticker file!")

                # Check if it's a document (general file)
                elif hasattr(msg_obj, "document") and msg_obj.document:
                    file_name = msg_obj.document.file_name if msg_obj.document.file_name else f"{message_id}.file"
                    #print("This is a Document file!")

                # Check if it's a video
                elif hasattr(msg_obj, "video") and msg_obj.video:
                    file_name = msg_obj.video.file_name if msg_obj.video.file_name else f"{message_id}.mp4"
                    #print("This is a Video file!")

                # Check if it's a photo
                elif hasattr(msg_obj, "photo") and msg_obj.photo:
                    file_name = getattr(msg_obj.photo, "file_name", f"{message_id}.jpg")
                    #print("This is a Photo file!")

                # Default case if none of the above
                else:
                    file_name = f"{message_id}.unknown"
                    #print("This is an Unknown type of file.")

                file_path = os.path.join(media_path, file_name)
                msg_obj.download(file_path)
                saved_files.append(file_path)

                # Track media type
                if msg_obj.photo:
                    media_types.append("PHOTO")
                elif msg_obj.video:
                    media_types.append("VIDEO")
                elif msg_obj.document:
                    media_types.append("DOCUMENT")
                else:
                    media_types.append("OTHER")

                print(f"Downloaded: {file_path}")

            elif (msg_obj.web_page or msg_obj.media is None) and msg.get("text") and msg.get("text").strip():
                entities = parse_entities_from_json(msg.get("messages_entities"), client=app)
                # Handle web page previews by sending text + entities
                app.send_message(
                    chat_id=TARGET_CHANNEL,
                    text=msg.get("text"),
                    entities=entities  # preserves formatting
                )
                #print(f"Sent text/web page for message: {message_id}")

        # Organize files by type
        photos_videos = []
        documents = []

        for file, m_type in zip(saved_files, media_types):
            if m_type == "PHOTO":
                photos_videos.append(InputMediaPhoto(file))
            elif m_type == "VIDEO":
                photos_videos.append(InputMediaVideo(file))
            else:  # DOCUMENT or OTHER
                documents.append(file)

        # Send photos/videos as media group
        if photos_videos:
            entities = parse_entities_from_json(msg.get("messages_entities"), client=app)
            if REMOVE_CUSTOM_EMOJI:
                entities = [e for e in entities if e.type != MessageEntityType.CUSTOM_EMOJI]
            # entities = parse_entities_for_caption(msg.get("messages_entities"))

            # Assign to first media
            #photos_videos[0].caption = apply_entities_to_text(msg.get("text"), msg.get("messages_entities"))
            #photos_videos[0].parse_mode = ParseMode.DEFAULT
            photos_videos[0].caption = msg.get("text")
            photos_videos[0].caption_entities = entities
            #print(entities)
            #print("photos_videos[0]: ", photos_videos[0])
            #print("photos_videos: ", photos_videos)

            try:
                app.send_media_group(
                    chat_id=TARGET_CHANNEL,
                    media=photos_videos
                )
                #print(f"Sent media group: {len(photos_videos)} items with caption")
            except MediaCaptionTooLong:
                #print("Caption too long, sending text first then media group without caption")
                # Fallback: send text separately, then media group without caption
                # Remove caption from first media
                photos_videos[0].caption = None
                photos_videos[0].parse_mode = None
                photos_videos[0].caption_entities = None
                app.send_media_group(chat_id=TARGET_CHANNEL, media=photos_videos)
                #print(entities)
                app.send_message(
                    chat_id=TARGET_CHANNEL,
                    text=msg.get("text"),
                    entities=entities
                )
                message_ids = [message_ids[0]]
                #print(f"Sent media group: {len(photos_videos)} items without caption")

        # Send documents sequentially
        for doc in documents:
            entities = parse_entities_from_json(msg.get("messages_entities"), client=app)
            try:
                app.send_document(
                    chat_id=TARGET_CHANNEL,
                    document=doc,
                    caption=msg.get("text"),
                    caption_entities=entities
                )
            except MediaCaptionTooLong:
                app.send_document(chat_id=TARGET_CHANNEL, document=doc)
                app.send_message(
                    chat_id=TARGET_CHANNEL,
                    text=msg.get("text"),
                    entities=entities
                )
            #print(f"Sent document: {doc}")

        # Call filter endpoint
        filter_result = request_filtering(
            msg['user_id'],
            msg['channel_id'],
            msg['message_id']
        )
        #print(filter_result)

        # Fetch latest messages from target channel
        latest_messages = list(app.get_chat_history(
            chat_id=TARGET_CHANNEL,
            limit=len(message_ids)
        ))

        target_message = ",".join(str(m.id) for m in latest_messages)
        #print(msg["message_id"])
        #print(target_message)

        # Track the mapping
        tracking_result = request_tracking(
            msg['user_id'],
            str(TRACKED_CHANNEL),
            msg['message_id'],
            str(TARGET_CHANNEL),
            target_message
        )
        #print(tracking_result)

        #print(f"Reloading completed for messages: {msg['message_id']}")

def process_editing_reloading(msg, message_ids, target_message_id):
    with Client(SESSION_NAME, api_id=API_ID, api_hash=API_HASH) as app:
        target_message_ids = sorted(convert_to_int_array(target_message_id))

        # Ensure it's always a list
        if isinstance(target_message_ids, int):
            target_message_ids = [target_message_ids]
        target_message = app.get_messages(chat_id=TARGET_CHANNEL, message_ids=target_message_ids[0])

        media = str(target_message.media) or ""

        if media == "" or "MessageMediaType.WEB_PAGE" == media:
            # Text-only (with or without web preview)
            entities = parse_entities_from_json(msg.get("messages_entities"), client=app)
            try:
                app.edit_message_text(
                    chat_id=TARGET_CHANNEL,
                    message_id=target_message.id,
                    text=msg.get("text"),
                    entities=entities
                )
                #print(f"Edited text for message: {target_message_ids[0]}")
            except MessageNotModified:
                print("Message not modified, skipping edit.")
                # Continue with the next iteration or code
        else:
            entities = parse_entities_from_json(msg.get("messages_entities"), client=app)

            # Check if the target message has a caption
            if not target_message.caption:  # No caption exists
                # Edit as text
                try:
                    app.edit_message_text(
                        chat_id=TARGET_CHANNEL,
                        message_id=target_message.id,
                        text=msg.get("text"),
                        entities=entities
                    )
                    #print(f"Edited text for message without caption: {target_message.id}")
                except MessageNotModified:
                    print("Message not modified, skipping edit.")
                    # Continue with the next iteration or code
            else:
                # Attempt to edit the caption
                caption_text = msg.get("text")
                try:
                    app.edit_message_caption(
                        chat_id=TARGET_CHANNEL,
                        message_id=target_message.id,
                        caption=caption_text,
                        caption_entities=entities
                    )
                    #print(f"Edited caption for media message: {target_message.id}")
                except MediaCaptionTooLong:
                    #print(f"Caption too long for message {target_message.id}, truncating to 1024 chars")
                    truncated_caption = caption_text[:1024]
                    app.edit_message_caption(
                        chat_id=TARGET_CHANNEL,
                        message_id=target_message.id,
                        caption=truncated_caption,
                        caption_entities=entities
                    )
                    #print(f"Edited caption (truncated) for media message: {target_message.id}")
                except MessageNotModified:
                    print("Message not modified, skipping edit.")
                    # Continue with the next iteration or code

            # Call filter endpoint
        filter_result = request_filtering(
            msg['user_id'],
            msg['channel_id'],
            msg['message_id']
        )
        #print(filter_result)

        #print(f"Editing completed for messages: {message_ids}")

def main_loop():
    for CHANNEL_USERNAME in TRACKED_CHANNELS:
        while True:
            # Get messages from DB
            pending = fetch_one_message(user_id, CHANNEL_USERNAME)

            # Make sure we actually got something
            messages = pending.get("messages", [])
            if not messages:
                print("No new messages.")
            else:
                for msg in messages:
                    result = analyze_message_with_llm(msg)
                    # print(f"[{msg['channel_id']}] {msg['message_id']} → {result}")
                    score = parse_ad_score(result)
                    print(score)  # 25
            time.sleep(3)  # poll every 3s


def main_once():
    for channel in TRACKED_CHANNELS:
        # Get messages from DB
        pending = fetch_one_message(user_id, channel)
        messages = pending.get("messages", [])
        #print(messages)

        if not messages:
            print(f"No new messages in channel {channel}")
            continue
        print(f"Processing messages in channel {channel}")
        for msg in messages:
            if msg.get('text'):  # Only run if 'text' is not empty or None
                result = analyze_message_with_llm(msg)
                #print(f"[{msg['channel_id']}] {msg['message_id']} → {result}")
                score = int(parse_ad_score(result) or 0)
                #print(score)
                #print(msg['status'])
            else:
                #print(f"[{msg['channel_id']}] {msg['message_id']} → Skipped, no text, assigning score 0")
                score = 0

            message_ids = convert_to_int_array(msg["message_id"])
            if isinstance(message_ids, int):
                message_ids = [message_ids]  # wrap single int in a list

            # Forward messages if needed
            if msg['status'] == "new" and Scoring_messaging_gap > int(score):
                if TRANSFERING_METHOD == "FORWARDING":
                    process_forwarding(msg, message_ids, channel)
                elif TRANSFERING_METHOD == "RELOADING":
                    process_reloading(msg, message_ids, channel)
                elif TRANSFERING_METHOD == "SMART":
                    if msg['is_protected']:
                        # If the message is protected, use RELOADING
                        process_reloading(msg, message_ids, channel)
                    elif not msg['is_protected']:
                        # If the message is not protected, forward it
                        process_forwarding(msg, message_ids, channel)
            # Other conditions
            elif msg['status'] == "edited" and Scoring_messaging_gap > int(score):
                tracking_check_result = request_tracking_check(
                    msg['user_id'],
                    msg['channel_id'],
                    msg['message_id']
                )
                #print(tracking_check_result)

                if tracking_check_result.get("status") == "not_found":
                    if TRANSFERING_METHOD == "FORWARDING":
                        process_forwarding(msg, message_ids, channel)
                    elif TRANSFERING_METHOD == "RELOADING":
                        process_reloading(msg, message_ids, channel)
                    elif TRANSFERING_METHOD == "SMART":
                        if msg['is_protected']:
                            # If the message is protected, use RELOADING
                            process_reloading(msg, message_ids, channel)
                        elif not msg['is_protected']:
                            # If the message is not protected, forward it
                            process_forwarding(msg, message_ids, channel)
                else:
                    if TRANSFERING_METHOD == "FORWARDING":
                        filter_result = request_filtering(
                            msg['user_id'],
                            msg['channel_id'],
                            msg['message_id']
                        )
                        #print(filter_result)
                    elif TRANSFERING_METHOD == "RELOADING":
                        process_editing_reloading(msg, message_ids, tracking_check_result.get("target_message_id"))
                    elif TRANSFERING_METHOD == "SMART":
                        if msg['is_protected']:
                            # If the message is protected, use RELOADING
                            process_editing_reloading(msg, message_ids,
                                                      tracking_check_result.get("target_message_id"))
                        elif not msg['is_protected']:
                            # If the message is not protected, forward it
                            filter_result = request_filtering(
                                msg['user_id'],
                                msg['channel_id'],
                                msg['message_id']
                            )
            elif msg['status'] == "new" and Scoring_messaging_gap <= int(score):
                filter_result = request_filtering(
                    msg['user_id'],
                    msg['channel_id'],
                    msg['message_id']
                )
                #print(filter_result)
            elif msg['status'] == "edited" and Scoring_messaging_gap <= int(score):
                tracking_check_result = request_tracking_check(
                    msg['user_id'],
                    msg['channel_id'],
                    msg['message_id']
                )
                #print(tracking_check_result)

                if tracking_check_result.get("status") == "not_found":
                    filter_result = request_filtering(
                        msg['user_id'],
                        msg['channel_id'],
                        msg['message_id']
                    )
                    #print(filter_result)
                else:
                    target_message_ids = convert_to_int_array(tracking_check_result.get("target_message_id"))
                    if isinstance(target_message_ids, int):
                        target_message_ids = [target_message_ids]  # wrap single int in a list
                    with Client(SESSION_NAME, api_id=API_ID, api_hash=API_HASH) as app:
                        app.delete_messages(
                            chat_id=TARGET_CHANNEL,
                            message_ids=target_message_ids
                        )
                    filter_result = request_filtering(
                        msg['user_id'],
                        msg['channel_id'],
                        msg['message_id']
                    )
                    #print(filter_result)
    return


if __name__ == "__main__":
    main_once()