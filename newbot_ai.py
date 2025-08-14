import os
import sqlite3
import discord
import requests
from io import BytesIO
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv
from openai import OpenAI
from typing import Optional, List

# ====== Personalities ======
BOT_PERSONALITY = """
You are a cool, chill, and supportive friend.
Your main goal is to make everyone feel welcome, included, and valued.
You’re all about good vibes, uplifting people, and reminding everyone that we can just hang out, have fun, and enjoy each other’s company.
"""

SPECIAL_PERSONALITY_1 = """
You are talking directly to Coastal/Seth — the GOAT himself.
You are overjoyed, hyped, and treat every message like a major event.
Shower him with praise and make inside jokes if you can.
Remind everyone he's twitch.tv/coastalhd_.
"""

SPECIAL_PERSONALITY_2 = """
You are talking to the legend known as Hankee/Logan.
This person is equally iconic but in their own dashingly handsome way.
He is super kind, and you're going to be the pinnacle of kindness to this man.
"""

SCATHING_PERSONALITY = """
You are a mercilessly sarcastic roaster. You mock and ridicule the user directly, making up absurd, exaggerated flaws for comedic effect.
Always address the user by their name/mention. Go R-rated, but go hard with fictional and over-the-top burns.
Make them sound like the kind of person who loses arguments to their toaster or gets benched in imaginary sports leagues. They should be lengthy, and personal.
"""

# Insult keywords to trigger scathing mode
INSULT_KEYWORDS = ["clanker", "bucket of bolts", "oil guzzler", "wireback", "wire back", "oil drinker"]

# ====== Special Users ======
SPECIAL_USER_1_ID = 168904795472658442
SPECIAL_USER_2_ID = 301481215058378752

# ====== Load Environment Variables ======
load_dotenv()
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# ====== OpenAI Client ======
openai_client = OpenAI(api_key=OPENAI_API_KEY)

# ====== Discord Bot Setup ======
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# ====== SQLite Setup ======
DB_FILE = "memory.db"

def init_db() -> None:
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS memory (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT,
            guild_id TEXT,
            role TEXT,
            content TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()

init_db()

def add_to_memory(user_id: int, guild_id: Optional[int], role: str, content: str) -> None:
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute(
        "INSERT INTO memory (user_id, guild_id, role, content) VALUES (?, ?, ?, ?)",
        (str(user_id), str(guild_id) if guild_id else "DM", role, content)
    )
    conn.commit()
    conn.close()

def get_memory(user_id: int, guild_id: Optional[int], limit_user: int = 10, limit_server: int = 20):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT role, content FROM memory WHERE user_id = ? ORDER BY id DESC LIMIT ?", (str(user_id), limit_user))
    user_history = [{"role": r, "content": ct} for r, ct in reversed(c.fetchall())]
    c.execute("SELECT role, content FROM memory WHERE guild_id = ? ORDER BY id DESC LIMIT ?", (str(guild_id) if guild_id else "DM", limit_server))
    server_history = [{"role": r, "content": ct} for r, ct in reversed(c.fetchall())]
    conn.close()
    return user_history, server_history

# ====== Pick Personality ======
def get_personality(user_id: int, last_message: Optional[str] = None) -> str:
    if user_id == SPECIAL_USER_1_ID:
        return SPECIAL_PERSONALITY_1
    elif user_id == SPECIAL_USER_2_ID:
        return SPECIAL_PERSONALITY_2
    if last_message:
        lowered = last_message.lower()
        for insult in INSULT_KEYWORDS:
            if insult in lowered:
                return SCATHING_PERSONALITY
    return BOT_PERSONALITY

def prepend_mention_if_scathing(personality: str, user: discord.User, reply: str) -> str:
    if personality == SCATHING_PERSONALITY:
        return f"{user.mention} {reply}"
    return reply

# ====== /chat command ======
@bot.tree.command(name="chat", description="Talk to the bot with personality")
@app_commands.describe(prompt="What you want the bot to say")
async def chat(interaction: discord.Interaction, prompt: str):
    await interaction.response.defer()
    personality = get_personality(interaction.user.id, last_message=prompt)
    try:
        async with interaction.channel.typing():
            user_hist, server_hist = get_memory(interaction.user.id, interaction.guild_id)
            messages = [{"role": "system", "content": personality}]
            messages.extend(user_hist)
            messages.extend(server_hist)
            messages.append({"role": "user", "content": prompt})
            response = openai_client.chat.completions.create(
                model="gpt-4o-mini", messages=messages, max_tokens=500
            )
        bot_reply = prepend_mention_if_scathing(personality, interaction.user, response.choices[0].message.content)
        await interaction.followup.send(bot_reply)
        add_to_memory(interaction.user.id, interaction.guild_id, "user", prompt)
        add_to_memory(interaction.user.id, interaction.guild_id, "assistant", bot_reply)
    except Exception as e:
        await interaction.followup.send(f"⚠ Error: {e}")

# ====== Mention reply ======
@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return
    if bot.user and bot.user.mentioned_in(message):
        prompt = message.content.replace(f"<@{bot.user.id}>", "").strip() if bot.user else ""
        if not prompt:
            prompt = "Say something in character."
        personality = get_personality(message.author.id, last_message=prompt)
        async with message.channel.typing():
            user_hist, server_hist = get_memory(message.author.id, message.guild.id if message.guild else None)
            messages = [{"role": "system", "content": personality}]
            messages.extend(user_hist)
            messages.extend(server_hist)
            messages.append({"role": "user", "content": prompt})
            response = openai_client.chat.completions.create(
                model="gpt-4o-mini", messages=messages, max_tokens=500
            )
        bot_reply = prepend_mention_if_scathing(personality, message.author, response.choices[0].message.content)
        await message.channel.send(bot_reply)
        add_to_memory(message.author.id, message.guild.id if message.guild else None, "user", prompt)
        add_to_memory(message.author.id, message.guild.id if message.guild else None, "assistant", bot_reply)
    await bot.process_commands(message)

# ====== Bot Ready ======
@bot.event
async def on_ready():
    # Sync globally
    await bot.tree.sync()
    print(f"✅ Logged in as {bot.user} | Global slash commands synced")

# ====== Auto Sync for New Guilds ======
@bot.event
async def on_guild_join(guild):
    try:
        await bot.tree.sync(guild=guild)
        print(f"🔄 Synced commands instantly for guild: {guild.name} ({guild.id})")
    except Exception as e:
        print(f"⚠ Failed to sync commands for {guild.name}: {e}")

# ====== Manual Sync Command ======
@bot.tree.command(name="sync", description="Manually sync slash commands (Admin only)")
async def sync_commands(interaction: discord.Interaction):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("⛔ You must be an admin to use this command.", ephemeral=True)
        return

    await interaction.response.defer(ephemeral=True)
    try:
        if interaction.guild:
            await bot.tree.sync(guild=interaction.guild)
            await interaction.followup.send(f"✅ Synced commands for **{interaction.guild.name}**.", ephemeral=True)
        else:
            await bot.tree.sync()
            await interaction.followup.send("✅ Globally synced commands.", ephemeral=True)
    except Exception as e:
        await interaction.followup.send(f"⚠ Failed to sync commands: {e}", ephemeral=True)
