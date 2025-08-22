import os
import sqlite3
import discord
import requests
import asyncio
import json
from io import BytesIO
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv
from openai import OpenAI
from typing import Optional, List

# ====== Blocklist for memory safety ======
BLOCKLIST = [
    "nigger", "faggot", "fag",  # Replace with actual terms
]

BLOCKLIST_FILE = "blocklist.json"

def load_blocklist() -> list:
    if not os.path.exists(BLOCKLIST_FILE):
        return []
    with open(BLOCKLIST_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


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

# ============== SANITIZE ===============
def sanitize_content(content: str) -> str:
    """Remove or replace blocklisted words before storing in memory."""
    lowered = content.lower()
    for bad_word in BLOCKLIST:
        if bad_word in lowered:
            content = content.replace(bad_word, "[REDACTED]")
    return content

def sanitize_mentions(text: str) -> str:
    """Prevent @everyone and @here from pinging by inserting a zero-width space."""
    if not text:
        return text
    return text.replace("@everyone", "@\u200beveryone").replace("@here", "@\u200bhere")

# ====== Discord Bot Setup ======
intents = discord.Intents.default()
intents.message_content = True

# Disallow @everyone and role pings globally (NEW)
default_allowed_mentions = discord.AllowedMentions(
    everyone=False, roles=False, users=True, replied_user=False
)

bot = commands.Bot(
    command_prefix="!",
    intents=intents,
    allowed_mentions=default_allowed_mentions,  # NEW
)

INSTANT_SYNC_GUILD_ID = 1304124705896136744

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
    safe_content = sanitize_content(content)
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute(
        "INSERT INTO memory (user_id, guild_id, role, content) VALUES (?, ?, ?, ?)",
        (str(user_id), str(guild_id) if guild_id else "DM", role, safe_content)
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
        bot_reply = sanitize_mentions(bot_reply)  # NEW
        await interaction.followup.send(bot_reply, allowed_mentions=default_allowed_mentions)  # NEW
        add_to_memory(interaction.user.id, interaction.guild_id, "user", prompt)
        add_to_memory(interaction.user.id, interaction.guild_id, "assistant", bot_reply)
    except Exception as e:
        await interaction.followup.send(f"⚠ Error: {e}", allowed_mentions=default_allowed_mentions)  # NEW

# ====== Mention reply ======
@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return

    # Ignore @everyone / @here entirely (NEW)
    if message.mention_everyone:
        return

    if bot.user and bot.user.mentioned_in(message):
        # Even if the bot is mentioned alongside @everyone/@here, we already returned above (NEW)
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
        bot_reply = sanitize_mentions(bot_reply)  # NEW
        await message.channel.send(bot_reply, allowed_mentions=default_allowed_mentions)  # NEW
        add_to_memory(message.author.id, message.guild.id if message.guild else None, "user", prompt)
        add_to_memory(message.author.id, message.guild.id if message.guild else None, "assistant", bot_reply)

    await bot.process_commands(message)

# ====== /image command ======
@bot.tree.command(name="image", description="Generate an image with DALL·E 3")
@app_commands.describe(prompt="What you want the image to be of")
async def image(interaction: discord.Interaction, prompt: str):
    await interaction.response.defer()
    try:
        async with interaction.channel.typing():
            # Call OpenAI Images API
            result = openai_client.images.generate(
                model="gpt-image-1",   # DALL·E 3
                prompt=prompt,
                size="1024x1024",      # You can also allow options: 256x256, 512x512, 1024x1024
                n=1
            )

            image_url = result.data[0].url

        embed = discord.Embed(
            title="🎨 Your Image",
            description=f"Prompt: `{prompt}`",
            color=discord.Color.blurple()
        )
        embed.set_image(url=image_url)

        await interaction.followup.send(embed=embed)

    except Exception as e:
        await interaction.followup.send(f"⚠ Error generating image: `{e}`", ephemeral=True)


# ====== Bot Ready ======
@bot.event
async def on_ready():
    try:
        # Always instantly sync for the specific guild
        guild = discord.Object(id=INSTANT_SYNC_GUILD_ID)
        await bot.tree.sync(guild=guild)
        print(f"✅ Instantly synced commands for guild {INSTANT_SYNC_GUILD_ID}")

        # Also do a global sync if you still want that
        await bot.tree.sync()
        print(f"🌍 Global slash commands synced")

        print(f"🤖 Logged in as {bot.user}")
    except Exception as e:
        print(f"⚠ Failed to sync: {e}")

# ====== Auto Sync for New Guilds ======
@bot.event
async def on_guild_join(guild):
    try:
        await bot.tree.sync(guild=guild)
        print(f"🔄 Synced commands instantly for guild: {guild.name} ({guild.id})")
    except Exception as e:
        print(f"⚠ Failed to sync commands for {guild.name}: {e}")

# ====== Manual Sync Command ======
@bot.tree.command(name="sync", description="Manually sync slash commands. Can target another server by ID.")
@app_commands.describe(guild_id="Optional guild ID to sync instantly")
async def manual_sync(interaction: discord.Interaction, guild_id: Optional[str] = None):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("⛔ You must be an admin to use this command.", ephemeral=True)
        return

    await interaction.response.defer(ephemeral=True)
    try:
        if guild_id:
            target_guild = discord.Object(id=int(guild_id))
            await bot.tree.sync(guild=target_guild)
            await interaction.followup.send(f"✅ Instantly synced commands for guild `{guild_id}`.", ephemeral=True)
        elif interaction.guild:
            await bot.tree.sync(guild=interaction.guild)
            await interaction.followup.send(f"✅ Synced commands for **{interaction.guild.name}**.", ephemeral=True)
        else:
            await bot.tree.sync()
            await interaction.followup.send("✅ Globally synced commands.", ephemeral=True)
    except Exception as e:
        await interaction.followup.send(f"⚠ Failed to sync commands: {e}", ephemeral=True)

@bot.tree.command(name="forget", description="Forget stored memory.")
@app_commands.describe(
    scope="What to forget: user, server, or all",
    target_id="Optional ID of the user or server to target."
)




# ============== FORGET ===============

async def forget_memory(interaction: discord.Interaction, scope: str, target_id: Optional[str] = None):
    """
    Forget memory from the database based on scope:
    - user: Forget your own memory (target_id requires admin in that server)
    - server: Forget current server (target_id requires bot owner)
    - all: Forget ALL memory (bot owner only)
    """
    scope = scope.lower()
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()

    app_info = await bot.application_info()
    bot_owner_id = app_info.owner.id

    # Forget user memory
    if scope == "user":
        if target_id:
            # Admin-only if targeting another user
            if not interaction.user.guild_permissions.administrator:
                await interaction.response.send_message("⛔ Only an admin can forget another user's memory.", ephemeral=True)
                conn.close()
                return
            uid = target_id
        else:
            uid = str(interaction.user.id)

        c.execute("DELETE FROM memory WHERE user_id = ?", (uid,))
        conn.commit()
        await interaction.response.send_message(f"🧹 Forgotten memory for user ID `{uid}`.", ephemeral=True)

    # Forget server memory
    elif scope == "server":
        if target_id:
            # Owner-only if targeting another server
            if interaction.user.id != bot_owner_id:
                await interaction.response.send_message("⛔ Only the bot owner can forget memory for another server.", ephemeral=True)
                conn.close()
                return
            gid = target_id
        else:
            if not interaction.user.guild_permissions.administrator:
                await interaction.response.send_message("⛔ Only an admin can forget this server's memory.", ephemeral=True)
                conn.close()
                return
            gid = str(interaction.guild.id)

        c.execute("DELETE FROM memory WHERE guild_id = ?", (gid,))
        conn.commit()
        await interaction.response.send_message(f"🧹 Forgotten memory for server ID `{gid}`.", ephemeral=True)

    # Forget all memory (bot owner only)
    elif scope == "all":
        if interaction.user.id != bot_owner_id:
            await interaction.response.send_message("⛔ Only the bot owner can forget ALL memory.", ephemeral=True)
            conn.close()
            return
        c.execute("DELETE FROM memory")
        conn.commit()
        await interaction.response.send_message("💣 All memory has been wiped from the database.", ephemeral=True)

    else:
        await interaction.response.send_message("❌ Invalid scope. Use `user`, `server`, or `all`.", ephemeral=True)

    conn.close()

# ====== Start ======
async def load_cogs():
    await bot.load_extension("cogs.poem")

async def main():
    await load_cogs()
    await bot.start(DISCORD_TOKEN)

if __name__ == "__main__":
    asyncio.run(main())

if __name__ == "__main__":
    if not DISCORD_TOKEN:
        raise RuntimeError("Missing DISCORD_TOKEN in environment (.env).")
    print("🚀 Starting bot now...")
    # Using bot.run() keeps allowed_mentions defaults in effect (NEW)
    bot.run(DISCORD_TOKEN)
