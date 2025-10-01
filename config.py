# config.py

# Database Configurations
database_ipaddress = "127.0.0.1"
database_port = "8000"

# LLM Configurations
llm_ipaddress = "127.0.0.1"
llm_port = "5000"

# Path to model
# Keep in mind, it used only in LLM_Suitcase_server.py to run model.
MODEL_PATH = "models/mistral-7b-instruct-v0.2.Q4_K_M.gguf"
#Config for LLM inside of LLM_Suitcase_server.py
LLM_CONFIG = {
    "model_path": MODEL_PATH,
    "n_ctx": 16384,
    "n_threads": 1,
    "backend": "cuda",
    "n_gpu_layers": -1,
    "gpu_device_id": 0,

    # inference controls
    "temperature": 0.7,
    "top_p": 0.9,
    "top_k": 40,
    "repeat_penalty": 1.1,
    "max_tokens": 512,

    # performance
    "n_batch": 512,
    "use_mmap": True,
    "use_mlock": False,

    # logging
    "verbose": False,
}

# Telegram Bot Credentials and Channel Details
# integer example API_ID = 0000000
API_ID = 0000000
# string example API_HASH = "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
API_HASH = "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
# Session name for your bot, keep in mind: it is your user session, avoid getting it exposed in any way.
# SESSION_NAME = "my_account"
SESSION_NAME = "my_account"
# Name of channels from which you want to take messages ["channel1", "channel2", ... "channelN"]
# Example [-1000000000000, "durov"]
# Example ["durov"]
TRACKED_CHANNELS = ["durov", -1000000000000]
# Target channel ID to which you want to post your messages
# Example TARGET_CHANNEL = -1000000000000
# Example TARGET_CHANNEL = "durov"
TARGET_CHANNEL = -1000000000000
# Unique identifier example: user_id = "1433345"
# Only for internal use.
user_id = "1433345"
#CHANNEL_LINK used in tool to get channel id (Telegram_get_channel_id.py)
#Example: CHANNEL_LINK = "https://t.me/+XXXXXXXXXXXXXX"
CHANNEL_LINK = "https://t.me/+XXXXXXXXXXXXXX"

# Amount of messages to parse per period of time
# Example: NUM_MESSAGES = 10
NUM_MESSAGES = 10
# Example: INTERVAL_TO_GATHER = 300
INTERVAL_TO_GATHER = 300
# Amount of messages to look out for edits per period of time
# Example: NUM_MESSAGES_TO_SCOUT = 100
NUM_MESSAGES_TO_SCOUT = 100
# Example: NUM_MESSAGES_TO_SCOUT = 3600
INTERVAL_FOR_SCOUT = 3600

# Transfer Methods Configuration
TRANSFERING_METHOD = "SMART"  # "FORWARDING", "RELOADING", "SMART"
# "FORWARDING" for forwarding
# "RELOADING" for downloading and posting
# "SMART" for forwarding when message is not protected, but downloading and posting when original message protected

#Setting to remove custom emoji from entities if you do not have premium. True is to remove, False to keep.
#Example: REMOVE_CUSTOM_EMOJI = True
REMOVE_CUSTOM_EMOJI = True

# Scoring Parameters
# This string is used to parse structure like this [{Scoring_parameter}: X] from AI output, in order to not get AI confused you might want to change it for certain tasks
# Example: Scoring_parameter = "AD_Score"
Scoring_parameter = "AD_Score"
# This number is used to filter messages, if your AI provide this number or higher in output, the message would be filtered
# Example: Scoring_messaging_gap = 75
Scoring_messaging_gap = 75
# Prompt Template for the AI
# The mechanism used to parse text include {Scoring_parameter}, {text} and {channel_id}, those provide text from scoring_messaging_gap parameter from above, text from telegram message and id/name of channel for this message accordingly.
# It is of high importance to note, that filtering tool seek [{Scoring_parameter}: X] structure, where X is integer value, by this i recommend to design prompt in a way AI would always provide this structure and use it to inform program about their conclusion.
prompt_template = """
You are a professional adblock AI trained to identify ads of any type precisely. 
Instructions:
- First, explain your reasoning about whether this message contains direct or indirect advertising.
- Pay attention to whether something is being promoted:
    - Direct marks suggesting an ad (links to large company sites, multiple links, attempts to provoke engagement)
    - Lottery or giveaways, especially with links very likely an ad
    - Donation requests, usually containing credentials to bank account or phone number.
    - Calls for donations or charity
    - Incitement to subscribe to other channels
- If a channel puts a link to its own channel at the end of the message, consider it normal practice. Keep in mind that links start with "http" or "https".
- Situation might be tricky, because some channels do try to mask ads as usual post, or might make a joke looking like an ad, you have to treat it accordingly.
- Here is a new Telegram message in channel {channel_id}: "{text}"
- As a professional you provide your judgment only and strictly in this format at the end of the message: 

[{Scoring_parameter}: X]

Where X is an integer from 0 (definitely not an ad), 25 (probably indirect ad), 50 (indirect ad, but smooth or uncertain cases), 75 (likely direct ad), 100 (definitely an ad).
"""