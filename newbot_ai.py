import os
import re
import logging
import asyncio
from collections import defaultdict, deque
from typing import Dict, Deque

import discord
from discord import Message
from dotenv import load_dotenv
from openai import OpenAI

# ---------------------- Setup ----------------------
load_dotenv()
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
HELP_CHANNEL_ID = int(os.getenv("HELP_CHANNEL_ID", "0"))
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

intents = discord.Intents.default()
intents.message_content = True
bot = discord.Client(intents=intents)

oa = OpenAI(api_key=OPENAI_API_KEY)

# Store short per-user conversation history
RECENT_QA: Dict[int, Deque] = defaultdict(lambda: deque(maxlen=4))
MAX_DISCORD_LEN = 2000

# ---------------------- Helpers ----------------------
def is_help_context(channel: discord.abc.GuildChannel) -> bool:
    """Return True if channel is the help channel or a thread under it."""
    if channel.id == HELP_CHANNEL_ID:
        return True
    if isinstance(channel, discord.Thread) and getattr(channel, "parent_id", None) == HELP_CHANNEL_ID:
        return True
    return False

def strip_bot_mention(text: str, bot_user: discord.User) -> str:
    """Remove mention of bot from start of message."""
    pattern = rf"^<@!?(?:{bot_user.id})>\s*"
    return re.sub(pattern, "", text).strip()

def sanitize_for_discord(text: str) -> str:
    """Remove zero-width chars and trim whitespace."""
    if not text:
        return ""
    cleaned = (
        text.replace("\u200b", "")
            .replace("\u200e", "")
            .replace("\u200f", "")
            .replace("\ufeff", "")
            .strip()
    )
    return cleaned

async def send_safe(msg: Message, content: str):
    """Send content safely, chunking and ensuring it's non-empty."""
    safe = sanitize_for_discord(content)

    # Only replace with fallback if the *original* content was empty
    if not safe:
        safe = (
            "I couldn’t generate a full response just now. Quick fundamentals while we sort this out:\n"
            "- **Parry late, riposte immediately.**\n"
            "- Keep your distance; make them whiff, then step in.\n"
            "- Watch stamina—wins often come from out-stamming.\n"
            "Ask again in a moment!"
        )

    logging.info(f"[SEND] len={len(safe)} preview={repr(safe[:120])}")

    # Send in chunks (if needed)
    for i in range(0, len(safe), MAX_DISCORD_LEN - 10):
        await msg.reply(safe[i:i + (MAX_DISCORD_LEN - 10)], mention_author=False)

async def ask_openai(user_id: int, question: str) -> str:
    """Ask OpenAI with a Mordhau mentor system prompt + short history."""
    history = RECENT_QA[user_id]
    messages = [
        {"role": "system", "content": (
            "You are NewbBot AI, a friendly expert Mordhau mentor for brand-new players. "
            "Give high-quality, structured coaching answers in this format:\n"
            "TL;DR (1 line)\nWhy it matters (1–2 bullets)\nDo this (steps)\nPractice drill\nCommon mistakes (3 bullets)\nNext skill to learn (1 line)\n"
            "Avoid toxicity, cheats, or patch-volatile specifics. Emphasize fundamentals."
        )}
    ]
    for q, a in history:
        messages.append({"role": "user", "content": q})
        messages.append({"role": "assistant", "content": a})
    messages.append({"role": "user", "content": question})

    try:
        resp = await asyncio.to_thread(
            oa.chat.completions.create,
            model=OPENAI_MODEL,
            messages=messages,
            max_tokens=900
        )
        answer = resp.choices[0].message.content.strip()
        if answer:
            history.append((question, answer))
        return answer
    except Exception as e:
        logging.error(f"OpenAI error: {e}")
        return ""

# ---------------------- Events ----------------------
@bot.event
async def on_ready():
    logging.info(f"Logged in as {bot.user} (ID: {bot.user.id})")

@bot.event
async def on_message(message: Message):
    if message.author.bot:
        return
    if not is_help_context(message.channel):
        return
    if not bot.user or not message.content:
        return
    if not bot.user.mentioned_in(message):
        return

    question = strip_bot_mention(message.content, bot.user)
    if not sanitize_for_discord(question):
        return await send_safe(message, f"Hi! Mention me with your Mordhau question here in <#{HELP_CHANNEL_ID}>.")

    async with message.channel.typing():
        answer = await ask_openai(message.author.id, question)
        await send_safe(message, answer)

# ---------------------- Main ----------------------
if __name__ == "__main__":
    if not DISCORD_TOKEN or not OPENAI_API_KEY or not HELP_CHANNEL_ID:
        logging.error("Missing required .env variables.")
        exit(1)
    bot.run(DISCORD_TOKEN)