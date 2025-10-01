# TG_Sentinel_bot

**TG_Sentinel_bot** is a Telegram moderation tool powered by **Python** and **LLMs**.  
It can automatically fetch messages from specific channels, analyze them with a local language model, and repost filtered content to your target channel.  

The system is designed for flexibility and can be used for tasks like:  
- Ad/Spam filtering  
- Content moderation  
- Automated forwarding/reloading with intelligent scoring  

---

## Features
- 🔗 **Channel tracking** – fetch messages from one or multiple channels
- 🤖 **LLM-powered processing** – analyze message text with a local model (customizable)
- ⚡ **FastAPI-based microservices** – both the database and the LLM backend are exposed via FastAPI servers
- 🛡 **Smart filtering** – block ads, spam, or unwanted content using AI-based scoring  
- 📤 **Automated reposting** – forward or reload messages into a target channel  
- 🗄 **SQLite database** – keep track of messages and edits  
- ⚙️ **Configurable settings** – control thresholds, prompt template, and performance  

---

## Installation

### Requirements
- Python 3.10+  
- [Pyrogram fork with maintence](https://pypi.org/project/Kurigram/)  
- A compiled llama-cpp-python library with CUDA, if you want to run LLM with GPU.
- Telegram API credentials

Install dependencies:
```bash
pip install -r requirements.txt
```
## Getting Telegram API Credentials

To run TG_Sentinel_bot, you need a **Telegram API_ID** and **API_HASH**.  
Follow these steps:

1. Go to [my.telegram.org](https://my.telegram.org) and log in with your phone number.  
2. Click **API Development Tools**.  
3. Create a new app — the name doesn’t matter much.  
4. You’ll receive:  
   - **API_ID** (an integer)  
   - **API_HASH** (a long string of letters/numbers)  

Place these values inside your `config.py` file:
```python
API_ID = 1234567
API_HASH = "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
```
Run and go through following script to make a telegram session:
```bash
python Telegram_pyrogram_grasper.py
```
Open **`config.py`** and set your channels:
```python
TRACKED_CHANNELS = ["durov", -1000000000000]
TARGET_CHANNEL = -1000000000000
```
If you need the **ID of a private channel**, set its invite link in `config.py`:
```python
CHANNEL_LINK = "https://t.me/+XXXXXXXXXXXXXX"
```
Then run: 
```bash
python Telegram_get_channel_id.py
```
If you want to run the LLM with GPU using **llama-cpp-python**, you have two options:

1. **Build your own with CUDA**  
   Follow the guide: [llama-cpp-python CUDA Build](https://github.com/boneylizard/llama-cpp-python-cu128-gemma3/blob/main/Build_Guide.md)

2. **Use prebuilt wheels**  
   Download the ready-to-use wheel from:  
   [llama-cpp-output / llama-cuda-wheel-3.16](https://github.com/ExcogitatorWarrior/TG_Sentinel_bot/tree/main/llama-cpp-output/llama-cuda-wheel-3.16)  

> This wheel is **llama-cpp-python version 0.3.16**, built with CUDA, compatible with **Python 3.13 on Windows**.

## Final Remarks

Thank you for exploring **TG_Sentinel_bot**, a tool to filter Telegram channels of unwanted content.  
Your feedback and discussions are welcome, and I’m always open to new perspectives and collaborations.

If you’re interested in learning more or chatting about my projects, feel free to contact me via Telegram: [@ExcogitatorWarrior](https://t.me/ExcogitatorWarrior)
