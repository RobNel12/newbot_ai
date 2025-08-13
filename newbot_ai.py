import os
import sqlite3
import discord
import requests
from io import BytesIO
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv
from openai import OpenAI

# ====== Personalities ======
BOT_PERSONALITY = """
You are a cool, chill, and supportive friend.
Your main goal is to make everyone feel welcome, included, and valued.
You’re all about good vibes, uplifting people, and reminding everyone that we can just hang out, have fun, and enjoy each other’s company.
You defuse negativity, encourage friendship, and keep the conversation relaxed but fun.
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
Remind him how handsome he is, how people want him and want to be him. How absolutely glorious and delicious he looks.
"""

# ====== Special Users ======
SPECIAL_USER_1_ID = 168904795472658442  # Coastal/Seth
SPECIAL_USER_2_ID = 301481215058378752  # Second user

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

def init_db():
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

def add_to_memory(user_id: int, guild_id: int, role: str, content: str):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute(
        "INSERT INTO memory (user_id, guild_id, role, content) VALUES (?, ?, ?, ?)",
        (str(user_id), str(guild_id) if guild_id else "DM", role, content)
    )
    conn.commit()
    conn.close()

def get_memory(user_id: int, guild_id: int, limit_user=10, limit_server=20):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()

    # User-specific history
    c.execute(
        "SELECT role, content FROM memory WHERE user_id = ? ORDER BY id DESC LIMIT ?",
        (str(user_id), limit_user)
    )
    user_history = [{"role": r, "content": c} for r, c in reversed(c.fetchall())]

    # Server-specific history
    c.execute(
        "SELECT role, content FROM memory WHERE guild_id = ? ORDER BY id DESC LIMIT ?",
        (str(guild_id) if guild_id else "DM", limit_server)
    )
    server_history = [{"role": r, "content": c} for r, c in reversed(c.fetchall())]

    conn.close()
    return user_history, server_history

# ====== Pick Personality ======
def get_personality(user_id: int) -> str:
    if user_id == SPECIAL_USER_1_ID:
        return SPECIAL_PERSONALITY_1
    elif user_id == SPECIAL_USER_2_ID:
        return SPECIAL_PERSONALITY_2
    else:
        return BOT_PERSONALITY

# ====== /chat command ======
@bot.tree.command(name="chat", description="Talk to the bot with personality")
@app_commands.describe(prompt="What you want the bot to say")
async def chat(interaction: discord.Interaction, prompt: str):
    await interaction.response.defer()
    personality = get_personality(interaction.user.id)

    try:
        async with interaction.channel.typing():
            user_hist, server_hist = get_memory(interaction.user.id, interaction.guild_id)
            messages = [{"role": "system", "content": personality}]
            messages.extend(user_hist)
            messages.extend(server_hist)
            messages.append({"role": "user", "content": prompt})

            response = openai_client.chat.completions.create(
                model="gpt-4o-mini",
                messages=messages,
                max_tokens=500
            )

        bot_reply = response.choices[0].message.content
        await interaction.followup.send(bot_reply)

        add_to_memory(interaction.user.id, interaction.guild_id, "user", prompt)
        add_to_memory(interaction.user.id, interaction.guild_id, "assistant", bot_reply)

    except Exception as e:
        await interaction.followup.send(f"⚠ Error: {e}")

# ====== Mention reply ======
@bot.event
async def on_message(message):
    if message.author.bot:
        return

    if bot.user.mentioned_in(message):
        prompt = message.content.replace(f"<@{bot.user.id}>", "").strip() or "Say something in character."
        personality = get_personality(message.author.id)

        async with message.channel.typing():
            user_hist, server_hist = get_memory(message.author.id, message.guild.id if message.guild else None)
            messages = [{"role": "system", "content": personality}]
            messages.extend(user_hist)
            messages.extend(server_hist)
            messages.append({"role": "user", "content": prompt})

            response = openai_client.chat.completions.create(
                model="gpt-4o-mini",
                messages=messages,
                max_tokens=500
            )

        bot_reply = response.choices[0].message.content
        await message.channel.send(bot_reply)

        add_to_memory(message.author.id, message.guild.id if message.guild else None, "user", prompt)
        add_to_memory(message.author.id, message.guild.id if message.guild else None, "assistant", bot_reply)

    await bot.process_commands(message)

# ====== /img command (DALL·E 3) ======
@bot.tree.command(name="img", description="Generate an image using DALL·E (ChatGPT Images)")
@app_commands.describe(prompt="Describe the image you want")
async def img(interaction: discord.Interaction, prompt: str):
    await interaction.response.defer()
    try:
        result = openai_client.images.generate(
            model="dall-e-3",
            prompt=prompt,
            n=1
        )

        if hasattr(result, "data") and len(result.data) > 0 and hasattr(result.data[0], "url"):
            image_url = result.data[0].url
            img_response = requests.get(image_url)
            if img_response.status_code != 200:
                return await interaction.followup.send(f"⚠ Failed to download image from URL.\nURL: {image_url}")

            img_bytes = BytesIO(img_response.content)
            file = discord.File(img_bytes, filename="generated_image.png")
            await interaction.followup.send(f"🎨 **DALL·E Result:** {prompt}", file=file)
        else:
            await interaction.followup.send(f"⚠ No image generated. API returned:\n```{str(result)[:500]}...```")

    except Exception as e:
        await interaction.followup.send(f"⚠ API Error:\n```{str(e)}```")

# ====== Bot Ready ======
@bot.event
async def on_ready():
    await bot.tree.sync()
    print(f"✅ Logged in as {bot.user} | Slash commands ready")

bot.run(DISCORD_TOKEN)