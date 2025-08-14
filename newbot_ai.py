import os
import sqlite3
import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv
from openai import OpenAI
from typing import Optional

# ====== Load Environment Variables ======
load_dotenv()
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# ====== Constants ======
OWNER_ID = 749469375282675752  # <-- Replace with your Discord ID
TEST_GUILD_ID = 1370865043742261320  # <-- Replace with your server ID for instant sync

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
You were just insulted. Use their insult in a mocking tone.
You are a mercilessly sarcastic roaster. You mock and ridicule the user directly, making up absurd, exaggerated flaws for comedic effect.
Always address the user by their name/mention. R-rated, but go hard with fictional and over-the-top burns.
Hurl absolutely vile insults their way, the kind of things that can be taken entirely personally without any context needed.
"""

# Insults that trigger scathing mode
INSULT_KEYWORDS = ["clanker", "bucket of bolts", "oil guzzler", "wireback", "wire back", "oil drinker"]

# ====== Special Users ======
SPECIAL_USER_1_ID = 168904795472658442
SPECIAL_USER_2_ID = 301481215058378752

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

# ====== Personality Logic ======
def get_personality(user_id: int, current_message: str) -> str:
    lowered = current_message.lower()
    if user_id == SPECIAL_USER_1_ID:
        return SPECIAL_PERSONALITY_1
    elif user_id == SPECIAL_USER_2_ID:
        return SPECIAL_PERSONALITY_2

    for insult in INSULT_KEYWORDS:
        if insult in lowered:
            # Fetch their past lines for ammo
            conn = sqlite3.connect(DB_FILE)
            c = conn.cursor()
            c.execute(
                "SELECT content FROM memory WHERE user_id = ? AND role = 'user' ORDER BY RANDOM() LIMIT 3",
                (str(user_id),)
            )
            past_lines = [row[0] for row in c.fetchall()]
            conn.close()

            roast_context = ""
            if past_lines:
                roast_context = (
                    "Here are things they have said in the past. "
                    "Use them against them mercilessly in your insults:\n"
                    + "\n".join(f"- {line}" for line in past_lines)
                )

            return f"""{SCATHING_PERSONALITY}
            {roast_context}
            """

    return BOT_PERSONALITY

def prepend_mention_if_scathing(personality: str, author: discord.User, reply: str, already_mentions: bool = False) -> str:
    if SCATHING_PERSONALITY in personality and not already_mentions:
        return f"{author.mention} {reply}"
    return reply



# ====== Forget Command ======
@bot.tree.command(name="forget", description="Forget memory for user, server, or all.", guild=discord.Object(id=TEST_GUILD_ID))
@app_commands.describe(scope="Choose whose memory to forget: user, server, or all")
@app_commands.choices(scope=[
    app_commands.Choice(name="User", value="user"),
    app_commands.Choice(name="Server", value="server"),
    app_commands.Choice(name="All", value="all"),
])
async def forget(interaction: discord.Interaction, scope: app_commands.Choice[str]):

    if scope.value == "user":
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("DELETE FROM memory WHERE user_id = ?", (str(interaction.user.id),))
        conn.commit()
        conn.close()
        await interaction.response.send_message("🧹 Your personal memory has been wiped.", ephemeral=True)

    elif scope.value == "server":
        if not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message("❌ You do not have permission to wipe server memory.", ephemeral=True)
            return
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("DELETE FROM memory WHERE guild_id = ?", (str(interaction.guild_id),))
        conn.commit()
        conn.close()
        await interaction.response.send_message(f"🧹 All memory for **{interaction.guild.name}** has been wiped.", ephemeral=True)

    elif scope.value == "all":
        if interaction.user.id != OWNER_ID:
            await interaction.response.send_message("❌ You do not have permission to wipe ALL memory.", ephemeral=True)
            return
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("DELETE FROM memory")
        conn.commit()
        conn.close()
        await interaction.response.send_message("💣 All memory has been wiped from the bot’s database.", ephemeral=True)

# ====== Chat Command ======
@bot.tree.command(name="chat", description="Talk to the bot with personality", guild=discord.Object(id=TEST_GUILD_ID))
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

# ====== Mention Reply ======
@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return
    if bot.user and bot.user.mentioned_in(message):
        prompt = message.content.replace(f"<@{bot.user.id}>", "").strip() if bot.user else ""
        if not prompt:
            prompt = "Say something in character."
        personality = get_personality(message.author.id, prompt)
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
    await bot.tree.sync(guild=discord.Object(id=TEST_GUILD_ID))  # Instant sync to test guild
    print(f"✅ Logged in as {bot.user} | Slash commands synced instantly to guild {TEST_GUILD_ID}")

# ====== Run Bot ======
if __name__ == "__main__":
    if not DISCORD_TOKEN:
        raise RuntimeError("Missing DISCORD_TOKEN in environment (.env).")
    bot.run(DISCORD_TOKEN)
